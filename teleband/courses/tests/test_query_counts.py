"""Query-count regression tests for course/enrollment list endpoints (Phase 1a)."""

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework.test import APIClient

from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.users.tests.factories import RoleFactory, UserFactory

pytestmark = pytest.mark.django_db


def _count(url, user):
    client = APIClient()
    client.force_authenticate(user=user)
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(url)
    assert response.status_code == 200, response.content
    return len(ctx.captured_queries)


def test_enrollment_list_constant_in_enrollment_count():
    """EnrollmentViewSet.list must not grow per enrollment of the user."""
    role = RoleFactory(name="Student")

    def make_user_with_enrollments(n):
        user = UserFactory()
        for _ in range(n):
            EnrollmentFactory(user=user, course=CourseFactory(), role=role)
        return user

    few_user = make_user_with_enrollments(2)
    many_user = make_user_with_enrollments(20)

    few = _count("/api/enrollments/", few_user)
    many = _count("/api/enrollments/", many_user)

    assert few == many, (
        f"enrollment list query count grows with #enrollments "
        f"({few} vs {many}) -- N+1 regression."
    )
