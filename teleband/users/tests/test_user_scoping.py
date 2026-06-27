"""Scoping + query-count tests for UserViewSet.get_queryset (Phase 1a #13).

The update/partial_update queryset previously hardcoded username="admin" (a bug)
and built its course list with a per-row Python loop. These tests pin the correct
behavior -- a teacher may update students in their OWN courses, nobody else's --
and that the queryset does not fan out per course.
"""

import pytest
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.db import connection

from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.users.api.views import UserViewSet
from teleband.users.tests.factories import RoleFactory, UserFactory

pytestmark = pytest.mark.django_db


def _update_queryset_for(teacher):
    view = UserViewSet()
    request = RequestFactory().patch("/fake/")
    request.user = teacher
    view.request = request
    view.action = "partial_update"
    view.kwargs = {}
    return view.get_queryset()


def test_teacher_update_queryset_scopes_to_own_students():
    teacher_role = RoleFactory(name="Teacher")
    student_role = RoleFactory(name="Student")

    teacher = UserFactory()
    course = CourseFactory()
    EnrollmentFactory(user=teacher, course=course, role=teacher_role)

    my_student = UserFactory()
    EnrollmentFactory(user=my_student, course=course, role=student_role)

    # A student in some other teacher's course must not be in scope.
    other_course = CourseFactory()
    EnrollmentFactory(user=UserFactory(), course=other_course, role=teacher_role)
    foreign_student = UserFactory()
    EnrollmentFactory(user=foreign_student, course=other_course, role=student_role)

    qs = _update_queryset_for(teacher)
    usernames = set(qs.values_list("username", flat=True))

    assert my_student.username in usernames
    assert foreign_student.username not in usernames
    # Not scoped to a hardcoded "admin" user.
    assert teacher.username in usernames or my_student.username in usernames


def test_teacher_update_queryset_is_constant_in_course_count():
    teacher_role = RoleFactory(name="Teacher")
    student_role = RoleFactory(name="Student")

    def teacher_with_courses(n):
        teacher = UserFactory()
        for _ in range(n):
            course = CourseFactory()
            EnrollmentFactory(user=teacher, course=course, role=teacher_role)
            EnrollmentFactory(course=course, role=student_role)
        return teacher

    few_teacher = teacher_with_courses(2)
    many_teacher = teacher_with_courses(20)

    with CaptureQueriesContext(connection) as ctx_few:
        list(_update_queryset_for(few_teacher))
    with CaptureQueriesContext(connection) as ctx_many:
        list(_update_queryset_for(many_teacher))

    assert len(ctx_few.captured_queries) == len(ctx_many.captured_queries), (
        f"update queryset grows with #courses "
        f"({len(ctx_few.captured_queries)} vs {len(ctx_many.captured_queries)}) -- N+1."
    )
