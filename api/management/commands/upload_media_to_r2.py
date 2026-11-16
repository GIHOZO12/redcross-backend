"""
Upload everything under MEDIA_ROOT into the configured Cloudflare R2 bucket.

    python manage.py upload_media_to_r2 --dry-run
    python manage.py upload_media_to_r2

Object keys are the paths stored in the database - the part after MEDIA_ROOT,
e.g. `profile_images/avatar.png` - so existing FileField values keep resolving
without touching a single row.

This talks to boto3 directly rather than going through django-storages, for two
reasons: the storage backend is configured with `file_overwrite = False` and
would rename a key that already exists, and uploading by hand lets us set
Content-Type per object. Objects stored without a Content-Type come back as
application/octet-stream, which makes browsers download images instead of
displaying them.
"""

import mimetypes
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Legacy copies of the upload folders sit at the project root, left over from
# before MEDIA_ROOT pointed at media/. They are not served today; --include-legacy
# uploads any key from them that the authoritative media/ tree does not provide.
LEGACY_DIRS = [
    'profile_images',
    'activity_images',
    'fellowership_images',
    'firstaid_images',
    'firstaid_videos',
    'instructor_images',
    'leaders_image',
    'redcross_activities_images',
]


class Command(BaseCommand):
    help = 'Copy local MEDIA_ROOT files into the Cloudflare R2 bucket.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='List what would be uploaded without sending anything.',
        )
        parser.add_argument(
            '--overwrite', action='store_true',
            help='Re-upload keys that already exist in the bucket.',
        )
        parser.add_argument(
            '--include-legacy', action='store_true',
            help='Also upload from the duplicate upload folders at the project '
                 'root, for keys that media/ does not already provide.',
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'USE_R2', False):
            raise CommandError(
                'R2 is not configured. Set R2_BUCKET_NAME, R2_ENDPOINT_URL, '
                'R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY in .env first.'
            )

        dry_run = options['dry_run']
        overwrite = options['overwrite']

        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.is_dir():
            raise CommandError('MEDIA_ROOT does not exist: %s' % media_root)

        # key -> local path. media/ wins; legacy folders only fill in gaps.
        targets = {}
        for path in sorted(media_root.rglob('*')):
            if path.is_file():
                key = path.relative_to(media_root).as_posix()
                targets[key] = path

        from_media = len(targets)
        added_legacy = 0
        if options['include_legacy']:
            base = Path(settings.BASE_DIR)
            for folder in LEGACY_DIRS:
                root = base / folder
                if not root.is_dir():
                    continue
                for path in sorted(root.rglob('*')):
                    if not path.is_file():
                        continue
                    key = path.relative_to(base).as_posix()
                    if key not in targets:
                        targets[key] = path
                        added_legacy += 1

        if not targets:
            self.stdout.write('Nothing to upload.')
            return

        options_dict = settings.STORAGES['default']['OPTIONS']
        bucket = options_dict['bucket_name']

        self.stdout.write(
            '%d file(s) from media/%s -> bucket %r' % (
                from_media,
                (' + %d legacy' % added_legacy) if added_legacy else '',
                bucket,
            )
        )

        client = self._client(options_dict)

        existing = set()
        if not overwrite:
            existing = self._list_keys(client, bucket)
            self.stdout.write('%d object(s) already in the bucket' % len(existing))

        uploaded = skipped = failed = 0
        sent_bytes = 0

        for key, path in sorted(targets.items()):
            if key in existing:
                skipped += 1
                continue

            size = path.stat().st_size
            content_type = (
                mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            )

            if dry_run:
                self.stdout.write('  would upload %s (%s, %s)' % (
                    key, content_type, self._human(size)))
                uploaded += 1
                sent_bytes += size
                continue

            try:
                with path.open('rb') as handle:
                    client.put_object(
                        Bucket=bucket,
                        Key=key,
                        Body=handle,
                        ContentType=content_type,
                        CacheControl='public, max-age=31536000',
                    )
            except Exception as exc:                       # noqa: BLE001
                failed += 1
                self.stderr.write(self.style.ERROR('  FAILED %s: %s' % (key, exc)))
                continue

            uploaded += 1
            sent_bytes += size
            self.stdout.write('  %s (%s)' % (key, self._human(size)))

        verb = 'would upload' if dry_run else 'uploaded'
        summary = '%s %d file(s), %s' % (verb, uploaded, self._human(sent_bytes))
        if skipped:
            summary += '; skipped %d already present' % skipped
        if failed:
            summary += '; %d failed' % failed

        style = self.style.ERROR if failed else self.style.SUCCESS
        self.stdout.write(style('\n' + summary))

        if not dry_run and not failed and uploaded:
            domain = options_dict.get('custom_domain')
            if domain:
                sample = sorted(targets)[0]
                self.stdout.write('\nSpot-check one in a browser:\n  https://%s/%s'
                                  % (domain, sample))
            else:
                self.stdout.write(
                    '\nR2_CUSTOM_DOMAIN is not set, so Django will hand out '
                    'signed, expiring URLs.\nSet it to an R2 custom domain (or '
                    'the bucket r2.dev address) for public files.'
                )

    # -- helpers ---------------------------------------------------------- #

    def _client(self, options_dict):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover
            raise CommandError('boto3 is not installed: %s' % exc)

        # Mirror the checksum workaround settings.py applies, in case this
        # command is the first thing to build a client in the process.
        os.environ.setdefault('AWS_REQUEST_CHECKSUM_CALCULATION', 'when_required')
        os.environ.setdefault('AWS_RESPONSE_CHECKSUM_VALIDATION', 'when_required')

        return boto3.client(
            's3',
            endpoint_url=options_dict['endpoint_url'],
            aws_access_key_id=options_dict['access_key'],
            aws_secret_access_key=options_dict['secret_key'],
            region_name=options_dict.get('region_name', 'auto'),
            config=Config(signature_version='s3v4'),
        )

    def _list_keys(self, client, bucket):
        keys = set()
        token = None
        while True:
            kwargs = {'Bucket': bucket}
            if token:
                kwargs['ContinuationToken'] = token
            try:
                response = client.list_objects_v2(**kwargs)
            except Exception as exc:                       # noqa: BLE001
                raise CommandError(
                    'Could not list bucket %r: %s\nCheck the endpoint URL and '
                    'that the API token has read access.' % (bucket, exc)
                )
            for item in response.get('Contents', []):
                keys.add(item['Key'])
            if not response.get('IsTruncated'):
                return keys
            token = response.get('NextContinuationToken')

    @staticmethod
    def _human(size):
        value = float(size)
        for unit in ('B', 'KB', 'MB', 'GB'):
            if value < 1024 or unit == 'GB':
                return '%.1f %s' % (value, unit)
            value /= 1024
