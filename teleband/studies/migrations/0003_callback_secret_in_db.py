import hashlib
import os
import secrets

from django.db import migrations, models


def hash_secret(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def import_env_secrets(apps, schema_editor):
    """Carry each study's secret over from the environment variable named by
    callback_secret_ref, so Qualtrics keeps working without changes. With
    "old,new" in the variable, the last value becomes current and the one
    before it previous. Studies with nothing to import get a random secret
    nobody knows; rotate it in the admin to get one to use."""
    Study = apps.get_model("studies", "Study")
    for study in Study.objects.all():
        values = [
            v.strip()
            for v in os.environ.get(study.callback_secret_ref or "", "").split(",")
            if v.strip()
        ]
        if not values:
            values = [secrets.token_urlsafe(32)]
        study.callback_secret_hash = hash_secret(values[-1])
        study.previous_callback_secret_hash = (
            hash_secret(values[-2]) if len(values) > 1 else ""
        )
        study.save(
            update_fields=["callback_secret_hash", "previous_callback_secret_hash"]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("studies", "0002_follow_up_surveys"),
        # research.0002 creates Study rows with callback_secret_ref, so it must
        # run before that field is removed.
        ("research", "0002_move_to_studies"),
    ]

    operations = [
        migrations.AddField(
            model_name="study",
            name="callback_secret_hash",
            field=models.CharField(blank=True, editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name="study",
            name="previous_callback_secret_hash",
            field=models.CharField(blank=True, editable=False, max_length=64),
        ),
        migrations.RunPython(import_env_secrets, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="study",
            name="callback_secret_ref",
        ),
    ]
