"""Model tests for the Phase 2 CourseAssignment / GroupAssignment tables."""

import pytest
from django.db import IntegrityError

from teleband.assignments.models import CourseAssignment, GroupAssignment
from teleband.assignments.tests.factories import (
    ActivityFactory,
    AssignmentGroupFactory,
    CourseAssignmentFactory,
    GroupAssignmentFactory,
)
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PieceFactory

pytestmark = pytest.mark.django_db


def test_course_assignment_unique_per_course_activity_piece():
    course = CourseFactory()
    activity = ActivityFactory()
    piece = PieceFactory()
    CourseAssignmentFactory(course=course, activity=activity, piece=piece)

    # A second row with the same (course, activity, piece) is rejected.
    with pytest.raises(IntegrityError):
        CourseAssignment.objects.create(course=course, activity=activity, piece=piece)


def test_course_assignment_allows_same_activity_different_piece():
    course = CourseFactory()
    activity = ActivityFactory()
    CourseAssignmentFactory(course=course, activity=activity, piece=PieceFactory())
    # Different piece -> allowed.
    CourseAssignmentFactory(course=course, activity=activity, piece=PieceFactory())
    assert (
        CourseAssignment.objects.filter(course=course, activity=activity).count() == 2
    )


def test_group_assignment_unique_per_enrollment_course_assignment():
    enrollment = EnrollmentFactory()
    ca = CourseAssignmentFactory()
    group = AssignmentGroupFactory()
    GroupAssignmentFactory(group=group, enrollment=enrollment, course_assignment=ca)

    with pytest.raises(IntegrityError):
        GroupAssignment.objects.create(
            group=group, enrollment=enrollment, course_assignment=ca
        )
