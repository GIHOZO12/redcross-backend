"""Rename the "partiarity" family to "impartiality".

The seven Fundamental Principles of the Red Cross are Humanity,
Impartiality, Neutrality, Independence, Voluntary Service, Unity and
Universality. This family was stored as "partiarity", which is both a
misspelling and the wrong word - "partiality" is the opposite of the
principle it is meant to name.

`Family.name` is a plain CharField with no choices, and FamilyActivities
and Members both reach Family through a ForeignKey, so renaming the row
carries their records with it. The string is not hardcoded anywhere in
the codebase; it is only ever read out of the database.

The frontend resolves a family by this exact name (`/family_list/<name>/`)
and `create_activity` builds its redirect as "/families/" + family_name,
so the frontend route must change in step with this migration.
"""

from django.db import migrations

OLD_NAME = "partiarity"
NEW_NAME = "impartiality"


def rename_forward(apps, schema_editor):
    Family = apps.get_model("crouirouge", "Family")
    # Guard against a second family already holding the new name, which
    # would otherwise leave two rows the lookup cannot tell apart.
    if Family.objects.filter(name=NEW_NAME).exists():
        return
    Family.objects.filter(name=OLD_NAME).update(name=NEW_NAME)


def rename_backward(apps, schema_editor):
    Family = apps.get_model("crouirouge", "Family")
    if Family.objects.filter(name=OLD_NAME).exists():
        return
    Family.objects.filter(name=NEW_NAME).update(name=OLD_NAME)


class Migration(migrations.Migration):

    dependencies = [
        ("crouirouge", "0015_alter_generalinformation_nationalid"),
    ]

    operations = [
        migrations.RunPython(rename_forward, rename_backward),
    ]
