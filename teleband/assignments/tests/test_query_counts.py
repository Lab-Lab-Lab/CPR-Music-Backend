"""Query-count regression tests for the assignment list path.

Phase 1a remodel guard: the teacher/student assignment list must issue a number
of SQL queries that is CONSTANT with respect to roster size and group size.
Before the remodel, AssignmentViewSetSerializer triggered N+1s on the part tree,
submissions/attachments, and (worst) GroupSerializer.get_members at O(M^2) per
group. These tests fail loudly if any of those regress.
"""

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework.test import APIClient

from teleband.assignments.models import CourseAssignment
from teleband.assignments.tests.factories import (
    ActivityFactory,
    AssignmentFactory,
    AssignmentGroupFactory,
)
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.instruments.tests.factories import InstrumentFactory
from teleband.musics.models import PartTransposition
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.submissions.models import SubmissionAttachment
from teleband.submissions.tests.factories import SubmissionFactory
from teleband.users.tests.factories import RoleFactory, UserFactory

pytestmark = pytest.mark.django_db


def _build_course(num_students, num_activities=3, group=None):
    """Create a course with a teacher and ``num_students`` students, each with
    one assignment per activity on a shared piece. Returns (course, teacher)."""
    teacher_role = RoleFactory(name="Teacher")
    student_role = RoleFactory(name="Student")
    course = CourseFactory()
    teacher = UserFactory()
    EnrollmentFactory(user=teacher, course=course, role=teacher_role)

    piece = PieceFactory()
    parts = [PartFactory(piece=piece) for _ in range(num_activities)]
    # Exercise the part-tree prefetch (transpositions + their transposition).
    for part in parts:
        PartTransposition.objects.create(
            part=part, transposition=InstrumentFactory().transposition
        )
    activities = [
        ActivityFactory(part_type=parts[i].part_type) for i in range(num_activities)
    ]

    for _ in range(num_students):
        enrollment = EnrollmentFactory(course=course, role=student_role)
        for i, activity in enumerate(activities):
            assignment = AssignmentFactory(
                activity=activity,
                enrollment=enrollment,
                part=parts[i],
                instrument=enrollment.instrument,
                piece=piece,
                group=group,
            )
            # Some submitted work + attachments to exercise those prefetches.
            submission = SubmissionFactory(assignment=assignment)
            SubmissionAttachment.objects.create(submission=submission, file="a.wav")

    return course, teacher


def _count_list_queries(course, user):
    client = APIClient()
    client.force_authenticate(user=user)
    url = f"/api/courses/{course.slug}/assignments/"
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url)
    assert response.status_code == 200, response.content
    return len(ctx.captured_queries)


class TestAssignmentListQueryCounts:
    def test_teacher_list_constant_in_roster_size(self):
        """The teacher list query count must not grow with the number of
        students. This is the highest-leverage N+1 fix in Phase 1a."""
        small_course, small_teacher = _build_course(num_students=2)
        large_course, large_teacher = _build_course(num_students=20)

        small = _count_list_queries(small_course, small_teacher)
        large = _count_list_queries(large_course, large_teacher)

        assert small == large, (
            f"Teacher list query count grows with roster size "
            f"({small} queries for 2 students vs {large} for 20) -- N+1 regression."
        )

    def test_student_list_constant_in_assignment_count(self):
        """A student's own list must not grow per assignment."""
        course = CourseFactory()
        student_role = RoleFactory(name="Student")
        teacher_role = RoleFactory(name="Teacher")
        EnrollmentFactory(user=UserFactory(), course=course, role=teacher_role)
        student = UserFactory()
        enrollment = EnrollmentFactory(user=student, course=course, role=student_role)
        piece = PieceFactory()

        def add_assignments(n):
            for _ in range(n):
                part = PartFactory(piece=piece)
                PartTransposition.objects.create(
                    part=part, transposition=InstrumentFactory().transposition
                )
                activity = ActivityFactory(part_type=part.part_type)
                assignment = AssignmentFactory(
                    activity=activity,
                    enrollment=enrollment,
                    part=part,
                    instrument=enrollment.instrument,
                    piece=piece,
                )
                # Phase 2 student list reads from CourseAssignment; dual-write it
                # (as the assign helpers do) plus a matching submission so this
                # test actually exercises the flipped read path's scaling.
                ca = CourseAssignment.objects.create(
                    course=course, activity=activity, piece=piece
                )
                SubmissionFactory(
                    assignment=assignment,
                    course_assignment=ca,
                    enrollment=enrollment,
                    instrument=enrollment.instrument,
                    part=part,
                )

        add_assignments(2)
        few = _count_list_queries(course, student)
        add_assignments(18)
        many = _count_list_queries(course, student)

        assert few == many, (
            f"Student list query count grows with assignment count "
            f"({few} vs {many}) -- N+1 regression."
        )

    def test_activity_list_constant_in_distinct_activities(self):
        """ActivityViewSet (distinct activities used in a course) must not grow
        per activity."""
        teacher_role = RoleFactory(name="Teacher")
        student_role = RoleFactory(name="Student")

        def build(num_activities):
            course = CourseFactory()
            teacher = UserFactory()
            EnrollmentFactory(user=teacher, course=course, role=teacher_role)
            piece = PieceFactory()
            enrollment = EnrollmentFactory(course=course, role=student_role)
            for _ in range(num_activities):
                part = PartFactory(piece=piece)
                AssignmentFactory(
                    activity=ActivityFactory(part_type=part.part_type),
                    enrollment=enrollment,
                    part=part,
                    instrument=enrollment.instrument,
                    piece=piece,
                )
            return course, teacher

        small_course, small_teacher = build(2)
        large_course, large_teacher = build(20)

        client_small = APIClient()
        client_small.force_authenticate(user=small_teacher)
        with CaptureQueriesContext(connection) as ctx_s:
            r_s = client_small.get(f"/api/courses/{small_course.slug}/activities/")
        assert r_s.status_code == 200, r_s.content

        client_large = APIClient()
        client_large.force_authenticate(user=large_teacher)
        with CaptureQueriesContext(connection) as ctx_l:
            r_l = client_large.get(f"/api/courses/{large_course.slug}/activities/")
        assert r_l.status_code == 200, r_l.content

        assert len(ctx_s.captured_queries) == len(ctx_l.captured_queries), (
            f"activity list query count grows with #activities "
            f"({len(ctx_s.captured_queries)} vs {len(ctx_l.captured_queries)})."
        )

    def test_grouped_assignments_constant_in_group_size(self):
        """GroupSerializer.get_members must be memoized: query count must not
        grow quadratically (or at all) with group membership size."""
        teacher_role = RoleFactory(name="Teacher")
        student_role = RoleFactory(name="Student")

        def build_group_course(group_size):
            course = CourseFactory()
            teacher = UserFactory()
            EnrollmentFactory(user=teacher, course=course, role=teacher_role)
            group = AssignmentGroupFactory()
            piece = PieceFactory()
            for _ in range(group_size):
                part = PartFactory(piece=piece)
                enrollment = EnrollmentFactory(course=course, role=student_role)
                AssignmentFactory(
                    activity=ActivityFactory(part_type=part.part_type),
                    enrollment=enrollment,
                    part=part,
                    instrument=enrollment.instrument,
                    piece=piece,
                    group=group,
                )
            return course, teacher

        small_course, small_teacher = build_group_course(2)
        large_course, large_teacher = build_group_course(15)

        small = _count_list_queries(small_course, small_teacher)
        large = _count_list_queries(large_course, large_teacher)

        assert small == large, (
            f"Grouped-assignment list query count grows with group size "
            f"({small} vs {large}) -- GroupSerializer N+1 regression."
        )
