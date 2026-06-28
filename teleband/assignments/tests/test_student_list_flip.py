"""Phase 2 step 7: AssignmentViewSet.list student path resolves from CourseAssignment.

Covers the contract (ids are CourseAssignment ids, grouped by piece slug), the
late-joiner fix (a student with no Assignment rows still sees the course's
CourseAssignments), and telephone_fixed group scoping (grouped CourseAssignments
only appear for the enrollment named in their GroupAssignment).
"""

import pytest
from rest_framework.test import APIClient

from teleband.assignments.models import CourseAssignment
from teleband.assignments.tests.factories import (
    ActivityFactory,
    AssignmentFactory,
    AssignmentGroupFactory,
    GroupAssignmentFactory,
)
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.users.tests.factories import RoleFactory

pytestmark = pytest.mark.django_db


def _student(course):
    return EnrollmentFactory(course=course, role=RoleFactory(name="Student"))


def _ca_with_assignment(course, enrollment):
    """A CourseAssignment plus the matching legacy Assignment for `enrollment`."""
    piece = PieceFactory()
    part = PartFactory(piece=piece)
    activity = ActivityFactory(part_type=part.part_type)
    AssignmentFactory(
        activity=activity,
        enrollment=enrollment,
        part=part,
        instrument=enrollment.instrument,
        piece=piece,
    )
    ca = CourseAssignment.objects.create(course=course, activity=activity, piece=piece)
    return ca, piece


def _list(enrollment):
    client = APIClient()
    client.force_authenticate(user=enrollment.user)
    resp = client.get(f"/api/courses/{enrollment.course.slug}/assignments/")
    assert resp.status_code == 200, resp.content
    return resp.json()


def _all_ids(grouped):
    return {item["id"] for items in grouped.values() for item in items}


def test_student_list_returns_course_assignment_ids_grouped_by_piece():
    course = CourseFactory()
    student = _student(course)
    ca1, piece1 = _ca_with_assignment(course, student)
    ca2, piece2 = _ca_with_assignment(course, student)

    grouped = _list(student)

    assert set(grouped.keys()) == {piece1.slug, piece2.slug}
    assert _all_ids(grouped) == {ca1.id, ca2.id}
    assert grouped[piece1.slug][0]["piece_id"] == piece1.id


def test_student_retrieve_resolves_course_assignment_by_id():
    course = CourseFactory()
    student = _student(course)
    ca, piece = _ca_with_assignment(course, student)

    client = APIClient()
    client.force_authenticate(user=student.user)
    resp = client.get(f"/api/courses/{course.slug}/assignments/{ca.id}/")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["id"] == ca.id
    assert body["enrollment"]["id"] == student.id


def test_late_joiner_can_retrieve_course_assignment():
    course = CourseFactory()
    early = _student(course)
    ca, piece = _ca_with_assignment(course, early)
    late = _student(course)

    client = APIClient()
    client.force_authenticate(user=late.user)
    resp = client.get(f"/api/courses/{course.slug}/assignments/{ca.id}/")
    assert resp.status_code == 200, resp.content
    assert resp.json()["id"] == ca.id


def test_late_joiner_sees_course_assignments_without_assignment_rows():
    course = CourseFactory()
    early = _student(course)
    ca, piece = _ca_with_assignment(course, early)

    # A student who enrolls after the piece was assigned has NO Assignment row,
    # but must still see the course's CourseAssignment (the correctness fix).
    late = _student(course)
    grouped = _list(late)

    assert _all_ids(grouped) == {ca.id}


def test_group_members_payload_built_from_group_assignments():
    """GroupSerializer.get_members (now reading GroupAssignment) lists the group's
    members with their submission status for the member viewing the list."""
    course = CourseFactory()
    piece = PieceFactory()
    part = PartFactory(piece=piece)
    activity = ActivityFactory(part_type=part.part_type)
    ca = CourseAssignment.objects.create(course=course, activity=activity, piece=piece)
    group = AssignmentGroupFactory()
    a = _student(course)
    b = _student(course)
    for enr in (a, b):
        GroupAssignmentFactory(group=group, enrollment=enr, course_assignment=ca)

    grouped = _list(a)
    row = grouped[piece.slug][0]
    members = row["group"]["members"]
    by_id = {m["enrollment_id"]: m for m in members}
    assert set(by_id) == {a.id, b.id}
    assert by_id[a.id]["enrollment_username"] == a.user.username
    assert by_id[a.id]["activity_type_name"] == activity.activity_type_name
    assert all(m["assignment_submitted"] is False for m in members)


def test_grouped_course_assignments_are_scoped_to_their_enrollment():
    course = CourseFactory()
    member = _student(course)
    outsider = _student(course)

    normal_ca, normal_piece = _ca_with_assignment(course, member)

    # A telephone_fixed CourseAssignment scoped to `member` via GroupAssignment.
    grouped_piece = PieceFactory()
    grouped_activity = ActivityFactory(
        part_type=PartFactory(piece=grouped_piece).part_type
    )
    grouped_ca = CourseAssignment.objects.create(
        course=course, activity=grouped_activity, piece=grouped_piece
    )
    group = AssignmentGroupFactory()
    GroupAssignmentFactory(group=group, enrollment=member, course_assignment=grouped_ca)

    member_ids = _all_ids(_list(member))
    outsider_ids = _all_ids(_list(outsider))

    # Member sees both the normal and the grouped CourseAssignment.
    assert member_ids == {normal_ca.id, grouped_ca.id}
    # Outsider sees only the normal one; the grouped CA is hidden.
    assert outsider_ids == {normal_ca.id}
