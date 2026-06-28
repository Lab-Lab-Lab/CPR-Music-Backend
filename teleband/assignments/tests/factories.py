from factory import Faker, SubFactory
from factory.django import DjangoModelFactory

from teleband.assignments.models import (
    Activity,
    ActivityCategory,
    ActivityType,
    AssignmentGroup,
    CourseAssignment,
    GroupAssignment,
)
from teleband.courses.tests.factories import CourseFactory
from teleband.courses.tests.factories import EnrollmentFactory
from teleband.musics.tests.factories import PartTypeFactory, PieceFactory


class ActivityCategoryFactory(DjangoModelFactory):
    name = Faker("word")

    class Meta:
        model = ActivityCategory


class ActivityTypeFactory(DjangoModelFactory):
    name = Faker("word")
    category = SubFactory(ActivityCategoryFactory)

    class Meta:
        model = ActivityType
        django_get_or_create = ["name"]


class ActivityFactory(DjangoModelFactory):
    activity_type = SubFactory(ActivityTypeFactory)
    part_type = SubFactory(PartTypeFactory)
    body = Faker("sentence")
    activity_type_name = Faker("word")
    category = Faker("word")

    class Meta:
        model = Activity


class AssignmentGroupFactory(DjangoModelFactory):
    type = "telephone_fixed"

    class Meta:
        model = AssignmentGroup


class CourseAssignmentFactory(DjangoModelFactory):
    course = SubFactory(CourseFactory)
    activity = SubFactory(ActivityFactory)
    piece = SubFactory(PieceFactory)

    class Meta:
        model = CourseAssignment


class GroupAssignmentFactory(DjangoModelFactory):
    group = SubFactory(AssignmentGroupFactory)
    enrollment = SubFactory(EnrollmentFactory)
    course_assignment = SubFactory(CourseAssignmentFactory)

    class Meta:
        model = GroupAssignment
