"""Phase 2 step 7: response-equivalence for the read-path flip.

Pins that CourseAssignmentReadSerializer (resolves a CourseAssignment against a
student enrollment) produces byte-identical output to the legacy per-student
AssignmentViewSetSerializer for every field EXCEPT `id` (which legitimately
changes from assignment.id to course_assignment.id). This is the safety net for
swapping the list/retrieve read path off Assignment without touching the
frontend contract.
"""

import pytest
from rest_framework.test import APIRequestFactory

from teleband.assignments.api.serializers import (
    AssignmentViewSetSerializer,
    CourseAssignmentReadSerializer,
)
from teleband.assignments.models import CourseAssignment
from teleband.assignments.tests.factories import ActivityFactory, AssignmentFactory
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.submissions.tests.factories import SubmissionFactory
from teleband.users.tests.factories import RoleFactory

pytestmark = pytest.mark.django_db


def _setup():
    """A student with an Assignment + its dual-written CourseAssignment, set up so
    Part.for_activity(activity, piece) resolves to the same part the Assignment
    carries (activity.part_type == part.part_type, part.piece == piece)."""
    course = CourseFactory()
    piece = PieceFactory()
    part = PartFactory(piece=piece)
    activity = ActivityFactory(part_type=part.part_type)
    enrollment = EnrollmentFactory(course=course, role=RoleFactory(name="Student"))
    assignment = AssignmentFactory(
        activity=activity,
        enrollment=enrollment,
        part=part,
        instrument=enrollment.instrument,
        piece=piece,
    )
    ca = CourseAssignment.objects.create(course=course, activity=activity, piece=piece)
    return course, piece, part, activity, enrollment, assignment, ca


def _request():
    return APIRequestFactory().get("/")


def test_read_serializer_matches_legacy_except_id():
    _, _, _, _, enrollment, assignment, ca = _setup()
    request = _request()

    legacy = AssignmentViewSetSerializer(assignment, context={"request": request}).data
    new = CourseAssignmentReadSerializer(
        ca, context={"request": request, "enrollment": enrollment}
    ).data

    # id legitimately differs: per-student assignment id -> course-level ca id.
    assert legacy["id"] == assignment.id
    assert new["id"] == ca.id

    legacy_no_id = {k: v for k, v in legacy.items() if k != "id"}
    new_no_id = {k: v for k, v in new.items() if k != "id"}
    assert legacy_no_id.keys() == new_no_id.keys()
    assert legacy_no_id == new_no_id


def test_read_serializer_matches_legacy_with_submission():
    _, _, part, _, enrollment, assignment, ca = _setup()
    SubmissionFactory(
        assignment=assignment,
        course_assignment=ca,
        enrollment=enrollment,
        instrument=enrollment.instrument,
        part=part,
        content="hello",
    )
    request = _request()

    legacy = AssignmentViewSetSerializer(assignment, context={"request": request}).data
    new = CourseAssignmentReadSerializer(
        ca, context={"request": request, "enrollment": enrollment}
    ).data

    assert len(new["submissions"]) == 1
    assert legacy["submissions"] == new["submissions"]
    assert {k: v for k, v in legacy.items() if k != "id"} == {
        k: v for k, v in new.items() if k != "id"
    }


def test_read_serializer_scopes_submissions_to_enrollment():
    """A submission belonging to a different enrollment on the same CourseAssignment
    must not leak into this student's view."""
    course, piece, part, activity, enrollment, assignment, ca = _setup()
    other = EnrollmentFactory(course=course, role=RoleFactory(name="Student"))
    other_assignment = AssignmentFactory(
        activity=activity,
        enrollment=other,
        part=part,
        instrument=other.instrument,
        piece=piece,
    )
    SubmissionFactory(
        assignment=other_assignment,
        course_assignment=ca,
        enrollment=other,
        instrument=other.instrument,
        part=part,
    )
    request = _request()

    new = CourseAssignmentReadSerializer(
        ca, context={"request": request, "enrollment": enrollment}
    ).data
    assert new["submissions"] == []
