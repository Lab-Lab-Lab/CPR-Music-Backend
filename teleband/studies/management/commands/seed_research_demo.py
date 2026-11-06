import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from teleband.studies.models import Study, StudyParticipant, Survey

DEMO_SURVEY_URL = "https://jmu.co1.qualtrics.com/jfe/form/SV_bC2q9q1gVH3sDEG"


class Command(BaseCommand):
    help = (
        "Local demo data for studies + teacher onboarding: a study with three "
        "follow-up surveys and a brand-new teacher meteacher1 / meteacher1 who "
        "consented 8 days ago."
    )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo data is for local development only (DEBUG).")

        study, _ = Study.objects.get_or_create(
            slug="demo",
            defaults={
                "name": "Demo Study",
                "status": Study.Status.RECRUITING,
                "qualtrics_survey_id": "SV_bC2q9q1gVH3sDEG",
                "qualtrics_base_url": "https://jmu.co1.qualtrics.com",
                "callback_secret_ref": "DEMO_STUDY_SECRET",
                "current_consent_version": "demo-v1",
            },
        )
        for title, days in [("Intake", 0), ("Week 1", 7), ("Week 4", 28)]:
            Survey.objects.update_or_create(
                study=study,
                title=title,
                defaults={"url": DEMO_SURVEY_URL, "due_after_days": days},
            )

        User = get_user_model()
        teacher, _ = User.objects.get_or_create(
            username="meteacher1",
            defaults={"name": "Demo Teacher", "email": "meteacher1@example.com"},
        )
        teacher.set_password("meteacher1")
        teacher.onboarded_at = None
        teacher.save()
        teacher.groups.add(Group.objects.get_or_create(name="Teacher")[0])

        # Consented 8 days ago, so Intake and Week 1 are due and Week 4 is not.
        StudyParticipant.objects.update_or_create(
            study=study,
            user=teacher,
            defaults={
                "status": StudyParticipant.Status.ACTIVE,
                "consented_outside_app": True,
                "consent_version": study.current_consent_version,
                "consented_at": timezone.now() - datetime.timedelta(days=8),
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Demo ready: log in as meteacher1 / meteacher1 at /courses"
            )
        )
