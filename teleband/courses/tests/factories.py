import datetime

from factory import Faker, SubFactory, LazyFunction
from factory.django import DjangoModelFactory

from teleband.courses.models import Enrollment, Course
from teleband.instruments.tests.factories import InstrumentFactory
from teleband.users.tests.factories import UserFactory, RoleFactory


class CourseFactory(DjangoModelFactory):

    name = Faker("color")
    owner = SubFactory(UserFactory)
    # Course.start_date/end_date are DateFields; use dates (utcnow() is a datetime,
    # which Postgres truncates on write but SQLite keeps, tripping DRF's DateField).
    start_date = LazyFunction(lambda: datetime.datetime.utcnow().date())
    end_date = LazyFunction(lambda: datetime.datetime.utcnow().date())

    class Meta:
        model = Course


class EnrollmentFactory(DjangoModelFactory):

    user = SubFactory(UserFactory)
    course = SubFactory(CourseFactory)
    instrument = SubFactory(InstrumentFactory)
    role = SubFactory(RoleFactory)

    class Meta:
        model = Enrollment
