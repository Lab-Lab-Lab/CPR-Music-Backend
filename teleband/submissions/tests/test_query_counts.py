"""Query-count regression tests for the teacher grading endpoints.

Phase 1a remodel guard: TeacherSubmissionViewSet.recent serializes a deeply
nested tree (submission -> assignment -> enrollment -> course/owner, part tree,
activity tree, grades, attachments). Without select_related/prefetch this fanned
out per submitting student. These tests assert the count is constant in the
number of students who submitted.
"""

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework.test import APIClient

from teleband.assignments.tests.factories import (
    ActivityFactory,
    ActivityTypeFactory,
    AssignmentFactory,
)
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.instruments.tests.factories import InstrumentFactory
from teleband.musics.models import PartTransposition
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.submissions.models import SubmissionAttachment
from teleband.submissions.tests.factories import SubmissionFactory
from teleband.users.tests.factories import RoleFactory, UserFactory

pytestmark = pytest.mark.django_db


def _build_recent_scenario(num_students):
    """A course where ``num_students`` each have a graded submission for the
    same piece+activity. Returns (course, teacher, activity_name, piece_slug)."""
    teacher_role = RoleFactory(name="Teacher")
    student_role = RoleFactory(name="Student")
    course = CourseFactory()
    teacher = UserFactory()
    EnrollmentFactory(user=teacher, course=course, role=teacher_role)

    piece = PieceFactory()
    activity_type = ActivityTypeFactory(name="Melody")
    part = PartFactory(piece=piece)
    PartTransposition.objects.create(
        part=part, transposition=InstrumentFactory().transposition
    )
    activity = ActivityFactory(activity_type=activity_type, part_type=part.part_type)

    for _ in range(num_students):
        enrollment = EnrollmentFactory(course=course, role=student_role)
        assignment = AssignmentFactory(
            activity=activity,
            enrollment=enrollment,
            part=part,
            instrument=enrollment.instrument,
            piece=piece,
        )
        submission = SubmissionFactory(assignment=assignment)
        SubmissionAttachment.objects.create(submission=submission, file="a.wav")

    return course, teacher, activity_type.name, piece.slug


def _count_recent_queries(course, user, activity_name, piece_slug):
    client = APIClient()
    client.force_authenticate(user=user)
    url = (
        f"/api/courses/{course.slug}/submissions/recent/"
        f"?activity_name={activity_name}&piece_slug={piece_slug}"
    )
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url)
    assert response.status_code == 200, response.content
    return len(ctx.captured_queries), response.data


def test_recent_constant_in_student_count():
    small_course, small_teacher, a_name, p_slug = _build_recent_scenario(2)
    large_course, large_teacher, a_name2, p_slug2 = _build_recent_scenario(20)

    small, small_data = _count_recent_queries(
        small_course, small_teacher, a_name, p_slug
    )
    large, large_data = _count_recent_queries(
        large_course, large_teacher, a_name2, p_slug2
    )

    assert len(small_data) == 2 and len(large_data) == 20
    assert small == large, (
        f"recent grading query count grows with #students who submitted "
        f"({small} vs {large}) -- N+1 regression."
    )
