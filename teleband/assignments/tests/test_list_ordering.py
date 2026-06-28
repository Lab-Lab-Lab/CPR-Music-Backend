"""AssignmentViewSet.list ordering test (Phase 1c #23/#24).

The list groups assignments by piece and sorts each group by the assignment's
PlannedActivity.order. After moving that order from a Python-built dict to a
correlated-subquery annotation, this pins that the response is still sorted by
plan order regardless of assignment creation order.
"""

import pytest
from rest_framework.test import APIClient

from teleband.assignments.models import CourseAssignment, PiecePlan, PlannedActivity
from teleband.assignments.tests.factories import ActivityFactory, AssignmentFactory
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.users.tests.factories import RoleFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_list_sorted_by_planned_activity_order():
    teacher_role = RoleFactory(name="Teacher")
    student_role = RoleFactory(name="Student")
    course = CourseFactory()
    teacher = UserFactory()
    EnrollmentFactory(user=teacher, course=course, role=teacher_role)
    student = EnrollmentFactory(course=course, role=student_role)

    piece = PieceFactory()
    plan = PiecePlan.objects.create(name="p", piece=piece)

    # Three activities with explicit plan order 0,1,2.
    activities = []
    for order in range(3):
        part = PartFactory(piece=piece)
        activity = ActivityFactory(
            part_type=part.part_type, activity_type_name=f"A{order}"
        )
        PlannedActivity.objects.create(piece_plan=plan, activity=activity, order=order)
        activities.append((activity, part))

    # Create the assignments in REVERSE order so DB/creation order != plan order.
    # The list now reads CourseAssignment; dual-write a CA per activity (carrying
    # piece_plan so the plan-order annotation resolves) plus the legacy Assignment.
    for activity, part in reversed(activities):
        AssignmentFactory(
            activity=activity,
            enrollment=student,
            part=part,
            instrument=student.instrument,
            piece=piece,
            piece_plan=plan,
        )
        CourseAssignment.objects.create(
            course=course, activity=activity, piece=piece, piece_plan=plan
        )

    client = APIClient()
    client.force_authenticate(user=teacher)
    resp = client.get(f"/api/courses/{course.slug}/assignments/")
    assert resp.status_code == 200, resp.content

    group = resp.data[piece.slug]
    names = [a["activity_type_name"] for a in group]
    assert names == ["A0", "A1", "A2"], names
