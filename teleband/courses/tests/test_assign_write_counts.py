"""Write-count regression tests for assignment creation (Phase 1b).

assign_one_piece_activity previously ran update_or_create per student (2 queries
each); now it bulk_creates the missing rows, so the query count is constant in
roster size and only the missing rows are written (idempotent re-assign).
"""

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection

from teleband.assignments.models import Assignment
from teleband.assignments.tests.factories import ActivityFactory
from teleband.courses.helper import assign_one_piece_activity
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.users.tests.factories import RoleFactory

pytestmark = pytest.mark.django_db


def _course_with_students(num_students):
    student_role = RoleFactory(name="Student")
    course = CourseFactory()
    for _ in range(num_students):
        EnrollmentFactory(course=course, role=student_role)
    return course


def _setup(num_students):
    course = _course_with_students(num_students)
    piece = PieceFactory()
    part = PartFactory(piece=piece)
    activity = ActivityFactory(part_type=part.part_type)
    return course, piece, activity


def test_assign_one_activity_query_count_constant_in_roster():
    small_course, small_piece, small_activity = _setup(2)
    large_course, large_piece, large_activity = _setup(20)

    with CaptureQueriesContext(connection) as ctx_small:
        assign_one_piece_activity(small_course, small_piece, small_activity)
    with CaptureQueriesContext(connection) as ctx_large:
        assign_one_piece_activity(large_course, large_piece, large_activity)

    assert len(ctx_small.captured_queries) == len(ctx_large.captured_queries), (
        f"assign query count grows with roster "
        f"({len(ctx_small.captured_queries)} vs {len(ctx_large.captured_queries)}) "
        f"-- write explosion."
    )


def test_assign_one_activity_creates_one_row_per_student():
    course, piece, activity = _setup(5)
    created = assign_one_piece_activity(course, piece, activity)
    assert len(created) == 5
    assert (
        Assignment.objects.filter(
            activity=activity, piece=piece, enrollment__course=course
        ).count()
        == 5
    )


def test_assign_one_activity_is_idempotent():
    course, piece, activity = _setup(5)
    assign_one_piece_activity(course, piece, activity)
    # Re-assigning the same piece activity must not duplicate or error.
    second = assign_one_piece_activity(course, piece, activity)
    assert second == []
    assert (
        Assignment.objects.filter(
            activity=activity, piece=piece, enrollment__course=course
        ).count()
        == 5
    )
