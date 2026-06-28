"""Phase 2 step 7: AssignmentViewSet.list teacher path resolves from CourseAssignment.

The teacher view returns one row per CourseAssignment (every assigned
(piece, activity)) instead of one per student -- verified against the frontend
(getAssignedPieces only derives the distinct (piece, activity) set per piece).
These tests pin that new cardinality, that the fields getAssignedPieces reads are
populated, and that per-student fields come back null/empty.
"""

import pytest
from rest_framework.test import APIClient

from teleband.assignments.models import CourseAssignment
from teleband.assignments.tests.factories import ActivityFactory
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.users.tests.factories import RoleFactory, UserFactory

pytestmark = pytest.mark.django_db


def _teacher(course):
    teacher = UserFactory()
    EnrollmentFactory(user=teacher, course=course, role=RoleFactory(name="Teacher"))
    return teacher


def _assign(course, activity, piece):
    """One CourseAssignment for (course, activity, piece). Every enrolled student
    is implicitly assigned it -- there are no per-student assignment rows."""
    return CourseAssignment.objects.create(
        course=course, activity=activity, piece=piece
    )


def _list(course, teacher):
    client = APIClient()
    client.force_authenticate(user=teacher)
    resp = client.get(f"/api/courses/{course.slug}/assignments/")
    assert resp.status_code == 200, resp.content
    return resp.json()


def test_teacher_list_is_one_row_per_course_assignment_not_per_student():
    course = CourseFactory()
    teacher = _teacher(course)
    # Multiple students enrolled: a per-student implementation would emit 4x rows.
    for _ in range(4):
        EnrollmentFactory(course=course, role=RoleFactory(name="Student"))
    piece = PieceFactory()
    part1 = PartFactory(piece=piece)
    part2 = PartFactory(piece=piece)
    act1 = ActivityFactory(part_type=part1.part_type)
    act2 = ActivityFactory(part_type=part2.part_type)
    ca1 = _assign(course, act1, piece)
    ca2 = _assign(course, act2, piece)

    grouped = _list(course, teacher)

    # One group for the piece, with exactly two rows (one per CourseAssignment),
    # NOT two-per-student.
    assert set(grouped.keys()) == {piece.slug}
    rows = grouped[piece.slug]
    assert len(rows) == 2
    assert {r["id"] for r in rows} == {ca1.id, ca2.id}


def test_teacher_list_populates_getassignedpieces_fields():
    course = CourseFactory()
    teacher = _teacher(course)
    EnrollmentFactory(course=course, role=RoleFactory(name="Student"))
    piece = PieceFactory()
    part = PartFactory(piece=piece)
    activity = ActivityFactory(part_type=part.part_type)
    ca = _assign(course, activity, piece)

    row = _list(course, teacher)[piece.slug][0]

    # Fields the frontend's getAssignedPieces reads:
    assert row["piece_id"] == piece.id
    assert row["piece_name"] == piece.name
    assert row["piece_slug"] == piece.slug
    assert row["activity_type_name"] == activity.activity_type_name
    assert row["activity_type_category"] == activity.category
    # Per-student fields are null/empty for the teacher (no enrollment context).
    assert row["instrument"] is None
    assert row["transposition"] is None
    assert row["submissions"] == []
    assert row["group"] is None


def test_teacher_list_distinct_piece_activity_set_matches_assignments():
    """The (piece_slug, activity_type) set a teacher sees equals the distinct set
    across all student assignments -- i.e. no assigned activity is lost by
    collapsing per-student rows."""
    course = CourseFactory()
    teacher = _teacher(course)
    for _ in range(3):
        EnrollmentFactory(course=course, role=RoleFactory(name="Student"))
    piece = PieceFactory()
    parts = [PartFactory(piece=piece) for _ in range(3)]
    activities = [ActivityFactory(part_type=p.part_type) for p in parts]
    for activity in activities:
        _assign(course, activity, piece)

    grouped = _list(course, teacher)
    seen = {
        (slug, row["activity_type_name"])
        for slug, rows in grouped.items()
        for row in rows
    }
    expected = {(piece.slug, a.activity_type_name) for a in activities}
    assert seen == expected
