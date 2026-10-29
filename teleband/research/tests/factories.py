from factory import Faker, Sequence, SubFactory
from factory.django import DjangoModelFactory

from teleband.research.models import Study, StudyParticipant, Survey
from teleband.users.tests.factories import UserFactory


class StudyFactory(DjangoModelFactory):

    name = Sequence(lambda n: f"Study {n}")

    class Meta:
        model = Study


class SurveyFactory(DjangoModelFactory):

    study = SubFactory(StudyFactory)
    title = Faker("sentence", nb_words=3)
    url = "https://jmu.co1.qualtrics.com/jfe/form/SV_abc123"

    class Meta:
        model = Survey


class StudyParticipantFactory(DjangoModelFactory):

    study = SubFactory(StudyFactory)
    user = SubFactory(UserFactory)

    class Meta:
        model = StudyParticipant
