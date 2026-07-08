"""Phase 2: unassign removes a piece's CourseAssignments (was per-student Assignments)."""

import pytest
from rest_framework.test import APIClient

from teleband.assignments.models import CourseAssignment
from teleband.assignments.tests.factories import ActivityFactory
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.users.tests.factories import RoleFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_unassign_deletes_course_assignments_for_piece():
    course = CourseFactory()
    teacher = UserFactory()
    EnrollmentFactory(user=teacher, course=course, role=RoleFactory(name="Teacher"))
    EnrollmentFactory(course=course, role=RoleFactory(name="Student"))

    piece = PieceFactory()
    other_piece = PieceFactory()
    for p in (piece, other_piece):
        part = PartFactory(piece=p)
        CourseAssignment.objects.create(
            course=course, activity=ActivityFactory(part_type=part.part_type), piece=p
        )

    client = APIClient()
    client.force_authenticate(user=teacher)
    resp = client.post(
        f"/api/courses/{course.slug}/unassign/", {"piece_id": piece.id}, format="json"
    )
    assert resp.status_code == 200, resp.content

    assert not CourseAssignment.objects.filter(course=course, piece=piece).exists()
    # Other pieces are untouched.
    assert CourseAssignment.objects.filter(course=course, piece=other_piece).exists()
