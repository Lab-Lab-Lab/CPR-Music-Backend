"""Write-count + behavior tests for assign_telephone_fixed (Phase 1b #18, #21).

The telephone_fixed path created an AssignmentGroup and an Assignment per row,
re-derived Part inside the loop, and re-evaluated activities.all() per group. It
now resolves activities/parts once and bulk_creates groups and assignments, so
the query count is constant in roster size.
"""

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection

from teleband.assignments.models import (
    Assignment,
    AssignmentGroup,
    CourseAssignment,
    GroupAssignment,
    PiecePlan,
    PlannedActivity,
)
from teleband.assignments.tests.factories import ActivityFactory
from teleband.courses.helper import assign_telephone_fixed
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.users.tests.factories import RoleFactory

pytestmark = pytest.mark.django_db

NUM_ACTIVITIES = 3


def _telephone_plan(piece):
    plan = PiecePlan.objects.create(name="tele", piece=piece, type="telephone_fixed")
    for order in range(NUM_ACTIVITIES):
        part = PartFactory(piece=piece)
        activity = ActivityFactory(part_type=part.part_type)
        PlannedActivity.objects.create(piece_plan=plan, activity=activity, order=order)
    return plan


def _setup(num_students):
    student_role = RoleFactory(name="Student")
    course = CourseFactory()
    for _ in range(num_students):
        EnrollmentFactory(course=course, role=student_role)
    piece = PieceFactory()
    plan = _telephone_plan(piece)
    return course, plan


def test_telephone_query_count_constant_in_roster():
    # Multiples of NUM_ACTIVITIES so grouping is even in both cases.
    small_course, small_plan = _setup(NUM_ACTIVITIES * 2)
    large_course, large_plan = _setup(NUM_ACTIVITIES * 10)

    with CaptureQueriesContext(connection) as ctx_small:
        assign_telephone_fixed(small_course, small_plan)
    with CaptureQueriesContext(connection) as ctx_large:
        assign_telephone_fixed(large_course, large_plan)

    assert len(ctx_small.captured_queries) == len(ctx_large.captured_queries), (
        f"telephone assign query count grows with roster "
        f"({len(ctx_small.captured_queries)} vs {len(ctx_large.captured_queries)}) "
        f"-- per-row create/Part not batched."
    )


def test_telephone_creates_one_group_membership_per_student_and_no_assignments():
    num_students = NUM_ACTIVITIES * 4
    course, plan = _setup(num_students)

    before_groups = AssignmentGroup.objects.count()
    created = assign_telephone_fixed(course, plan)

    # Phase 2: one GroupAssignment per student, one group per block of
    # NUM_ACTIVITIES students, and NO per-student Assignment rows.
    assert len(created) == num_students
    assert (
        AssignmentGroup.objects.count() - before_groups
        == num_students // NUM_ACTIVITIES
    )
    assert all(ga.group_id is not None for ga in created)
    assert Assignment.objects.filter(piece_plan=plan).count() == 0


def test_telephone_dual_writes_course_and_group_assignments():
    num_students = NUM_ACTIVITIES * 4
    course, plan = _setup(num_students)
    assign_telephone_fixed(course, plan)

    # One CourseAssignment per activity in the plan (not per student).
    assert (
        CourseAssignment.objects.filter(course=course, piece=plan.piece).count()
        == NUM_ACTIVITIES
    )
    # One GroupAssignment per student (each student gets exactly one activity).
    assert (
        GroupAssignment.objects.filter(course_assignment__course=course).count()
        == num_students
    )
