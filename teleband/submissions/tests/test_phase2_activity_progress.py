"""Phase 2 step 6: ActivityProgress course_assignment/enrollment dual-key."""

import importlib

import pytest
from django.apps import apps as global_apps
from rest_framework.test import APIClient

from teleband.assignments.models import CourseAssignment
from teleband.assignments.tests.factories import ActivityFactory, AssignmentFactory
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.submissions.models import ActivityProgress
from teleband.users.tests.factories import RoleFactory

pytestmark = pytest.mark.django_db


def _assignment_with_ca():
    course = CourseFactory()
    piece = PieceFactory()
    part = PartFactory(piece=piece)
    enrollment = EnrollmentFactory(course=course, role=RoleFactory(name="Student"))
    assignment = AssignmentFactory(
        activity=ActivityFactory(part_type=part.part_type),
        enrollment=enrollment,
        part=part,
        instrument=enrollment.instrument,
        piece=piece,
    )
    ca = CourseAssignment.objects.create(
        course=course, activity=assignment.activity, piece=piece
    )
    return assignment, enrollment, ca


def test_progress_created_via_api_is_dual_keyed():
    assignment, enrollment, ca = _assignment_with_ca()
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


def test_backfill_activity_progress():
    assignment, enrollment, ca = _assignment_with_ca()
    progress = ActivityProgress.objects.create(assignment=assignment)
    assert progress.course_assignment_id is None

    mod = importlib.import_module(
        "teleband.submissions.migrations.0017_backfill_activity_progress"
    )
    mod.backfill_activity_progress(global_apps, None)

    progress.refresh_from_db()
    assert progress.course_assignment_id == ca.id
    assert progress.enrollment_id == enrollment.id
