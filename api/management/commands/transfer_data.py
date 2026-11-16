"""
Move the contents of db.sqlite3 into Postgres (Supabase), in two passes.

The two passes run in separate processes because each needs a different
DATABASE_URL, which settings.py reads at import time:

    # 1. with DATABASE_URL unset, so this reads db.sqlite3
    python manage.py transfer_data dump

    # 2. put the Supabase session-pooler URL in .env, then
    python manage.py transfer_data load

What `load` does, in order: `migrate` to build the schema, `loaddata` to insert
the rows, then reset every sequence. That last step is the one most guides
leave out - `loaddata` writes explicit primary keys without advancing
Postgres's sequences, so the next insert through the ORM collides with an
existing id and raises IntegrityError.
"""

from io import StringIO
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

# Tables that must not travel.
#   contenttypes / auth.Permission - rebuilt by migrate; copying them collides
#     with the fresh rows, which is why the dump uses natural keys instead
#   admin.logentry               - points at contenttypes rows that will differ
#   sessions.session             - ephemeral, and every session is invalid after
#                                  a database move anyway
#   token_blacklist              - ephemeral JWT bookkeeping
EXCLUDED = [
    'contenttypes',
    'auth.Permission',
    'admin.logentry',
    'sessions.session',
    'token_blacklist',
]

DEFAULT_DUMP = 'sqlite_dump.json'


class Command(BaseCommand):
    help = 'Copy data from SQLite to Postgres. Run "dump" then "load".'

    def add_arguments(self, parser):
        parser.add_argument('step', choices=['dump', 'load'])
        parser.add_argument(
            '--file',
            default=DEFAULT_DUMP,
            help='Path of the intermediate JSON dump (default: %s).' % DEFAULT_DUMP,
        )

    def handle(self, *args, **options):
        step = options['step']
        path = Path(options['file'])
        engine = settings.DATABASES['default']['ENGINE']

        if step == 'dump':
            self._dump(path, engine)
        else:
            self._load(path, engine)

    # -- dump ------------------------------------------------------------- #

    def _dump(self, path, engine):
        if 'sqlite' not in engine:
            raise CommandError(
                'The "dump" step must read SQLite, but the active database is '
                '%s.\nUnset DATABASE_URL (comment it out in .env) and run this '
                'again.' % engine
            )

        self.stdout.write('Dumping from %s' % settings.DATABASES['default']['NAME'])
        with path.open('w', encoding='utf-8') as handle:
            call_command(
                'dumpdata',
                *('--exclude=%s' % name for name in EXCLUDED),
                # Serialise foreign keys by natural key where a model supports
                # it, so references survive the permission/contenttype rebuild.
                natural_foreign=True,
                natural_primary=True,
                indent=2,
                stdout=handle,
            )

        size = path.stat().st_size
        self.stdout.write(self.style.SUCCESS(
            'Wrote %s (%.1f KB)' % (path, size / 1024)
        ))
        self.stdout.write(
            '\nNext: put the Supabase session-pooler URL in DATABASE_URL '
            '(port 5432,\nuser postgres.<project-ref>), then run:\n'
            '    python manage.py transfer_data load --file %s' % path
        )

    # -- load ------------------------------------------------------------- #

    def _load(self, path, engine):
        if 'postgresql' not in engine:
            raise CommandError(
                'The "load" step expects Postgres, but the active database is '
                '%s.\nSet DATABASE_URL to your Supabase session-pooler '
                'connection string first.' % engine
            )
        if not path.exists():
            raise CommandError(
                '%s does not exist. Run "python manage.py transfer_data dump" '
                'first.' % path
            )

        host = settings.DATABASES['default'].get('HOST', '')
        port = str(settings.DATABASES['default'].get('PORT', ''))
        self.stdout.write('Target: %s:%s' % (host, port))

        if port == '6543':
            self.stderr.write(self.style.WARNING(
                'Port 6543 is Supabase transaction mode, which does not support '
                'the prepared statements migrate needs. Switch to port 5432 '
                '(session mode) on the same pooler host.'
            ))

        self.stdout.write('\n[1/3] migrate')
        call_command('migrate', interactive=False, verbosity=1)

        self.stdout.write('\n[2/3] loaddata %s' % path)
        call_command('loaddata', str(path), verbosity=1)

        self.stdout.write('\n[3/3] resetting sequences')
        self._reset_sequences()

        self.stdout.write(self.style.SUCCESS('\nDone.'))
        self.stdout.write(
            'Create a fresh admin login with: python manage.py createsuperuser\n'
            '(existing password hashes carry over, so old accounts still work)'
        )

    def _reset_sequences(self):
        """Advance each table's id sequence past the highest imported id."""
        labels = sorted({
            model._meta.app_label
            for model in apps.get_models()
            if model._meta.managed and not model._meta.proxy
        })

        buffer = StringIO()
        call_command('sqlsequencereset', *labels, stdout=buffer, no_color=True)
        statements = [s.strip() for s in buffer.getvalue().split(';') if s.strip()]

        if not statements:
            self.stdout.write('  nothing to reset')
            return

        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

        self.stdout.write('  reset %d sequence(s)' % len(statements))
