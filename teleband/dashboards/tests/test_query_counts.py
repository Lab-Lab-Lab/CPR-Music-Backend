"""Query-count regression test for the CSV export dashboard (Phase 1a #11).

The CSV export streams the entire Assignment table unfiltered, so the right
guarantee is that it issues O(1) queries, not O(rows). The test DB is seeded with
thousands of assignments by a data migration; this asserts the export stays under
a small constant ceiling regardless, which only holds if every relation the row
loop (and the Activity/PiecePlan __str__) walks is select_related/prefetched.
"""

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.test import Client

from teleband.assignments.models import CourseAssignment
from teleband.assignments.tests.factories import ActivityFactory
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.submissions.models import SubmissionAttachment
from teleband.submissions.tests.factories import SubmissionFactory
from teleband.users.tests.factories import RoleFactory

pytestmark = pytest.mark.django_db

# Generous ceiling: the export should be a handful of queries (base + one per
# prefetched relation, chunked). Anything near the row count is an N+1.
MAX_QUERIES = 25


def test_csv_export_is_constant_query_count():
    # Phase 2: rows are (student, CourseAssignment) pairs. Build a course with
    # students, course assignments, and submissions to exercise both the
    # has-submissions and the unsubmitted branches.
    course = CourseFactory()
    student_role = RoleFactory(name="Student")
    piece = PieceFactory()
    students = [EnrollmentFactory(course=course, role=student_role) for _ in range(5)]
    for _ in range(4):
        part = PartFactory(piece=piece)
        activity = ActivityFactory(part_type=part.part_type)
        ca = CourseAssignment.objects.create(
            course=course, activity=activity, piece=piece
        )
        for enrollment in students[:2]:
            submission = SubmissionFactory(
                course_assignment=ca,
                enrollment=enrollment,
                instrument=enrollment.instrument,
                part=part,
            )
            SubmissionAttachment.objects.create(submission=submission, file="a.wav")

    client = Client()
    with CaptureQueriesContext(connection) as ctx:
        response = client.get("/dashboards/export/csv/")
    assert response.status_code == 200
    # 5 students x 4 course assignments = 20 per-student rows in the body.
    assert response.content.decode().count("\n") >= 20

    n = len(ctx.captured_queries)
    assert n <= MAX_QUERIES, (
        f"CSV export issued {n} queries (ceiling {MAX_QUERIES}) -- N+1 regression: "
        f"the export should be O(1) in queries, not O(rows)."
    )
