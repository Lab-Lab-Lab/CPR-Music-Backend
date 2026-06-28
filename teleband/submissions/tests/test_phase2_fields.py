"""Phase 2 step 5: Submission course_assignment/enrollment/instrument/part."""

import pytest
from rest_framework.test import APIClient

from teleband.assignments.api.serializers import resolve_instrument
from teleband.assignments.models import CourseAssignment
from teleband.assignments.tests.factories import ActivityFactory
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.models import Part
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.submissions.models import Submission
from teleband.users.tests.factories import RoleFactory

pytestmark = pytest.mark.django_db


def _course_assignment():
    course = CourseFactory()
    piece = PieceFactory()
    part = PartFactory(piece=piece)
    activity = ActivityFactory(part_type=part.part_type)
    enrollment = EnrollmentFactory(course=course, role=RoleFactory(name="Student"))
    ca = CourseAssignment.objects.create(course=course, activity=activity, piece=piece)
    return enrollment, ca, part


def test_create_submission_populates_phase2_fields():
    enrollment, ca, part = _course_assignment()
    client = APIClient()
    client.force_authenticate(user=enrollment.user)
    # Phase 2: the nested route id is the CourseAssignment id.
    resp = client.post(
        f"/api/courses/{enrollment.course.slug}/assignments/{ca.id}/submissions/",
        {"content": "hi"},
        format="json",
    )
    assert resp.status_code == 201, resp.content

    sub = Submission.objects.get(id=resp.data["id"])
    assert sub.course_assignment_id == ca.id
    assert sub.enrollment_id == enrollment.id
    # instrument/part are resolved at write time from the enrollment + CA.
    assert sub.instrument_id == resolve_instrument(enrollment, ca).id
    assert sub.part_id == Part.for_activity(ca.activity, ca.piece).id
