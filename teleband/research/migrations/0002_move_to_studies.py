import datetime

from django.db import migrations
from django.utils import timezone
from django.utils.text import slugify


def copy_to_studies(apps, schema_editor):
    """Copy research's studies, participants, surveys and completions into
    teleband.studies.

    research had no consent tracking (consent was handled outside the app), so
    participants become active participants consented outside the app, with
    their start_date as the consent date. Copied studies have no Qualtrics
    consent survey or callback secret; fill those in before recruiting.
    """
    OldStudy = apps.get_model("research", "Study")
    OldParticipant = apps.get_model("research", "StudyParticipant")
    OldSurvey = apps.get_model("research", "Survey")
    OldCompletion = apps.get_model("research", "SurveyCompletion")
    Study = apps.get_model("studies", "Study")
    StudyParticipant = apps.get_model("studies", "StudyParticipant")
    Survey = apps.get_model("studies", "Survey")
    SurveyCompletion = apps.get_model("studies", "SurveyCompletion")

    tz = timezone.get_current_timezone()
    studies = {}
    for old in OldStudy.objects.all():
        base = slugify(old.name)[:40] or "study"
        slug, n = base, 1
        while Study.objects.filter(slug=slug).exists():
            n += 1
            slug = f"{base}-{n}"
        study = Study.objects.create(
            slug=slug,
            name=old.name,
            description=old.description,
            status="closed" if old.is_active else "ended",
            qualtrics_survey_id="",
            callback_secret_ref="",
            current_consent_version="",
        )
        Study.objects.filter(pk=study.pk).update(created_at=old.created_at)
        studies[old.pk] = study

    participants = {}
    for old in OldParticipant.objects.all():
        consented_at = datetime.datetime.combine(
            old.start_date, datetime.time.min, tzinfo=tz
        )
        participant = StudyParticipant.objects.create(
            study=studies[old.study_id],
            user_id=old.user_id,
            status="active",
            consented_outside_app=True,
            consented_at=consented_at,
        )
        participants[(old.study_id, old.user_id)] = participant

    surveys = {}
    for old in OldSurvey.objects.all():
        surveys[old.pk] = (
            old.study_id,
            Survey.objects.create(
                study=studies[old.study_id],
                title=old.title,
                description=old.description,
                url=old.url,
                due_after_days=old.due_after_days,
                order=old.order,
                is_active=old.is_active,
            ),
        )

    for old in OldCompletion.objects.all():
        study_id, survey = surveys[old.survey_id]
        participant = participants.get((study_id, old.user_id))
        if participant is None:
            # Completed without being a participant; there is no pid to attach it to.
            continue
        SurveyCompletion.objects.create(
            survey=survey,
            participant=participant,
            completed_at=old.completed_at,
            response_id=old.response_id[:64],
        )


class Migration(migrations.Migration):

    dependencies = [
        ("research", "0001_initial"),
        ("studies", "0002_follow_up_surveys"),
    ]

    operations = [
        migrations.RunPython(copy_to_studies, migrations.RunPython.noop),
        migrations.DeleteModel(name="SurveyCompletion"),
        migrations.DeleteModel(name="StudyParticipant"),
        migrations.DeleteModel(name="Survey"),
        migrations.DeleteModel(name="Study"),
    ]
