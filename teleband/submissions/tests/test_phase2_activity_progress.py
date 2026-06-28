"""Phase 2 step 6: ActivityProgress course_assignment/enrollment dual-key."""

import pytest
from django.db import IntegrityError
from rest_framework.test import APIClient

from teleband.assignments.models import CourseAssignment
from teleband.assignments.tests.factories import ActivityFactory
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.submissions.models import ActivityProgress
from teleband.users.tests.factories import RoleFactory

pytestmark = pytest.mark.django_db


def _course_assignment():
    course = CourseFactory()
    piece = PieceFactory()
    part = PartFactory(piece=piece)
    enrollment = EnrollmentFactory(course=course, role=RoleFactory(name="Student"))
    activity = ActivityFactory(part_type=part.part_type)
    ca = CourseAssignment.objects.create(course=course, activity=activity, piece=piece)
    return enrollment, ca


def test_activity_progress_unique_per_course_assignment_and_enrollment():
    enrollment, ca = _course_assignment()
    ActivityProgress.objects.create(course_assignment=ca, enrollment=enrollment)
    with pytest.raises(IntegrityError):
        ActivityProgress.objects.create(course_assignment=ca, enrollment=enrollment)


def test_progress_created_via_api_is_dual_keyed():
    enrollment, ca = _course_assignment()
    client = APIClient()
    client.force_authenticate(user=enrollment.user)
    # Phase 2: the nested route id is the CourseAssignment id.
    resp = client.get(
        f"/api/courses/{enrollment.course.slug}/assignments/{ca.id}/activity-progress/"
    )
    assert resp.status_code == 200, resp.content

    progress = ActivityProgress.objects.get(course_assignment=ca, enrollment=enrollment)
    assert progress.course_assignment_id == ca.id
    assert progress.enrollment_id == enrollment.id
