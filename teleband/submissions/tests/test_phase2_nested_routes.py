"""Phase 2 step 7: nested submission / activity-progress routes resolve the URL id
as a CourseAssignment scoped to the requesting student.

Covers the late-joiner correctness win (a student with no Assignment row can submit
and track progress against a CourseAssignment) and cross-student isolation (a
student only sees their own work for a shared CourseAssignment).
"""

import pytest
from rest_framework.test import APIClient

from teleband.assignments.models import CourseAssignment
from teleband.assignments.tests.factories import ActivityFactory, AssignmentFactory
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.submissions.models import ActivityProgress, Submission
from teleband.users.tests.factories import RoleFactory

pytestmark = pytest.mark.django_db


def _course_with_ca():
    course = CourseFactory()
    piece = PieceFactory()
    part = PartFactory(piece=piece)
    activity = ActivityFactory(part_type=part.part_type)
    ca = CourseAssignment.objects.create(course=course, activity=activity, piece=piece)
    return course, piece, part, activity, ca


def _student(course):
    return EnrollmentFactory(course=course, role=RoleFactory(name="Student"))


def _client(enrollment):
    client = APIClient()
    client.force_authenticate(user=enrollment.user)
    return client


def test_late_joiner_can_submit_against_course_assignment():
    """A student with no Assignment row submits against the CourseAssignment; the
    submission is keyed by (course_assignment, enrollment) with a null assignment."""
    course, piece, part, activity, ca = _course_with_ca()
    late = _student(course)

    resp = _client(late).post(
        f"/api/courses/{course.slug}/assignments/{ca.id}/submissions/",
        {"content": "late work"},
        format="json",
    )
    assert resp.status_code == 201, resp.content

    sub = Submission.objects.get(id=resp.data["id"])
    assert sub.assignment_id is None
    assert sub.course_assignment_id == ca.id
    assert sub.enrollment_id == late.id
    assert sub.instrument_id == late.instrument_id
    assert sub.part_id == part.id


def test_submission_list_is_scoped_to_requesting_student():
    course, piece, part, activity, ca = _course_with_ca()
    mine = _student(course)
    theirs = _student(course)

    _client(mine).post(
        f"/api/courses/{course.slug}/assignments/{ca.id}/submissions/",
        {"content": "mine"},
        format="json",
    )
    _client(theirs).post(
        f"/api/courses/{course.slug}/assignments/{ca.id}/submissions/",
        {"content": "theirs"},
        format="json",
    )

    resp = _client(mine).get(
        f"/api/courses/{course.slug}/assignments/{ca.id}/submissions/"
    )
    assert resp.status_code == 200, resp.content
    contents = {s["content"] for s in resp.json()}
    assert contents == {"mine"}


def test_late_joiner_activity_progress_keyed_by_enrollment():
    course, piece, part, activity, ca = _course_with_ca()
    late = _student(course)

    resp = _client(late).get(
        f"/api/courses/{course.slug}/assignments/{ca.id}/activity-progress/"
    )
    assert resp.status_code == 200, resp.content

    progress = ActivityProgress.objects.get(course_assignment=ca, enrollment=late)
    assert progress.assignment_id is None


def test_activity_progress_is_distinct_per_student():
    course, piece, part, activity, ca = _course_with_ca()
    a = _student(course)
    b = _student(course)

    _client(a).get(f"/api/courses/{course.slug}/assignments/{ca.id}/activity-progress/")
    _client(b).get(f"/api/courses/{course.slug}/assignments/{ca.id}/activity-progress/")

    assert ActivityProgress.objects.filter(course_assignment=ca).count() == 2
    assert (
        ActivityProgress.objects.filter(course_assignment=ca, enrollment=a).count() == 1
    )
    assert (
        ActivityProgress.objects.filter(course_assignment=ca, enrollment=b).count() == 1
    )


def test_unknown_course_assignment_returns_404():
    course, piece, part, activity, ca = _course_with_ca()
    student = _student(course)

    resp = _client(student).get(
        f"/api/courses/{course.slug}/assignments/{ca.id + 999}/activity-progress/"
    )
    assert resp.status_code == 404, resp.content
