"""Phase 2 step 5: Submission course_assignment/enrollment/instrument/part."""

import importlib

import pytest
from django.apps import apps as global_apps
from rest_framework.test import APIClient

from teleband.assignments.models import CourseAssignment
from teleband.assignments.tests.factories import ActivityFactory, AssignmentFactory
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.submissions.models import Submission
from teleband.users.tests.factories import RoleFactory

pytestmark = pytest.mark.django_db


def _assignment_in_course():
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
    # The CourseAssignment the dual-populate should resolve to.
    ca = CourseAssignment.objects.create(
        course=course, activity=assignment.activity, piece=piece
    )
    return assignment, enrollment, ca


def test_create_submission_dual_populates_phase2_fields():
    assignment, enrollment, ca = _assignment_in_course()
    client = APIClient()
    client.force_authenticate(user=enrollment.user)
    resp = client.post(
        f"/api/courses/{enrollment.course.slug}/assignments/{assignment.id}/submissions/",
        {"content": "hi"},
        format="json",
    )
    assert resp.status_code == 201, resp.content

    sub = Submission.objects.get(id=resp.data["id"])
    assert sub.course_assignment_id == ca.id
    assert sub.enrollment_id == enrollment.id
    assert sub.instrument_id == assignment.instrument_id
    assert sub.part_id == assignment.part_id


def test_backfill_submission_fields():
    assignment, enrollment, ca = _assignment_in_course()
    # A pre-existing submission with only the old assignment FK set.
    sub = Submission.objects.create(assignment=assignment, content="old")
    assert sub.course_assignment_id is None

    mod = importlib.import_module(
        "teleband.submissions.migrations.0015_backfill_submission_course_assignment"
    )
    mod.backfill_submission_fields(global_apps, None)

    sub.refresh_from_db()
    assert sub.course_assignment_id == ca.id
    assert sub.enrollment_id == enrollment.id
    assert sub.instrument_id == assignment.instrument_id
    assert sub.part_id == assignment.part_id
