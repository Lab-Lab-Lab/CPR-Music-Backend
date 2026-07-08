# Generated manually on 2025-10-17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("submissions", "0010_activity_progress"),
    ]

    operations = [
        migrations.AddField(
            model_name="activityprogress",
            name="participant_email",
            field=models.EmailField(
                blank=True,
                null=True,
                help_text="Email from Qualtrics for survey matching",
            ),
        ),
    ]
