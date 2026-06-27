"""Write-count + behavior test for change_piece_instrument (Phase 1b #17)."""

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework.test import APIClient

from teleband.assignments.models import Assignment
from teleband.assignments.tests.factories import ActivityFactory, AssignmentFactory
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.instruments.tests.factories import InstrumentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.users.tests.factories import RoleFactory, UserFactory

pytestmark = pytest.mark.django_db


def _build(num_students):
    teacher_role = RoleFactory(name="Teacher")
    student_role = RoleFactory(name="Student")
    course = CourseFactory(can_edit_instruments=True)
    teacher = UserFactory()
    EnrollmentFactory(user=teacher, course=course, role=teacher_role)
    piece = PieceFactory()
    for _ in range(num_students):
        part = PartFactory(piece=piece)
        enrollment = EnrollmentFactory(course=course, role=student_role)
        AssignmentFactory(
            activity=ActivityFactory(part_type=part.part_type),
            enrollment=enrollment,
            part=part,
            instrument=enrollment.instrument,
            piece=piece,
        )
    return course, teacher, piece


def _patch(course, teacher, piece, instrument):
    client = APIClient()
    client.force_authenticate(user=teacher)
    with CaptureQueriesContext(connection) as ctx:
        resp = client.patch(
            f"/api/courses/{course.slug}/change_piece_instrument/",
            {"piece_id": piece.id, "instrument_id": instrument.id},
            format="json",
        )
    assert resp.status_code == 200, resp.content
    return len(ctx.captured_queries)


def test_change_instrument_query_count_constant_in_roster():
    new_instrument = InstrumentFactory()
    small_course, small_teacher, small_piece = _build(2)
    large_course, large_teacher, large_piece = _build(20)

    small = _patch(small_course, small_teacher, small_piece, new_instrument)
    large = _patch(large_course, large_teacher, large_piece, new_instrument)

    assert small == large, (
        f"change_piece_instrument query count grows with roster "
        f"({small} vs {large}) -- per-row save() not collapsed to one UPDATE."
    )


def test_change_instrument_updates_all_assignments():
    new_instrument = InstrumentFactory()
    course, teacher, piece = _build(4)
    _patch(course, teacher, piece, new_instrument)
    instruments = set(
        Assignment.objects.filter(piece=piece, enrollment__course=course).values_list(
            "instrument_id", flat=True
        )
    )
    assert instruments == {new_instrument.id}
