from django.utils import timezone
from factory import Faker, LazyFunction, Sequence, SubFactory
from factory.django import DjangoModelFactory

from teleband.studies.models import Study, StudyParticipant, Survey
from teleband.users.tests.factories import UserFactory


class StudyFactory(DjangoModelFactory):

    slug = Sequence(lambda n: f"study-{n}")
    name = Sequence(lambda n: f"Study {n}")
    status = Study.Status.RECRUITING
    qualtrics_survey_id = "SV_abc123"
    current_consent_version = "v1"

    class Meta:
        model = Study


class SurveyFactory(DjangoModelFactory):

    study = SubFactory(StudyFactory)
    title = Faker("sentence", nb_words=3)
    url = "https://jmu.co1.qualtrics.com/jfe/form/SV_abc123"

    class Meta:
        model = Survey


class StudyParticipantFactory(DjangoModelFactory):
    """An active participant who has already consented."""

    study = SubFactory(StudyFactory)
    user = SubFactory(UserFactory)
    status = StudyParticipant.Status.ACTIVE
    consented_at = LazyFunction(timezone.now)

    class Meta:
        model = StudyParticipant
