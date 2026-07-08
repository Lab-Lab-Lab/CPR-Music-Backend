"""Roster CSV import tests (Phase 1b #19).

The enrollment creation now bulk_creates the new enrollments after a single
existence query, instead of a get()+create() per user. User creation itself
stays per-row (password hashing can't be bulked), so these assert correctness
and idempotency rather than a constant query count.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from teleband.courses.models import Enrollment
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.users.models import Role
from teleband.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
User = get_user_model()


def _csv(rows):
    body = "fullname,username,password,grade\n" + "".join(
        f"{name},{username},{pw},{grade}\n" for name, username, pw, grade in rows
    )
    return SimpleUploadedFile(
        "roster.csv", body.encode("utf-8"), content_type="text/csv"
    )


def _post_roster(course, teacher, rows):
    client = APIClient()
    client.force_authenticate(user=teacher)
    return client.post(
        f"/api/courses/{course.slug}/roster/",
        {"file": _csv(rows)},
        format="multipart",
    )


def _course_with_teacher():
    # Use the seeded roles (the roster view does Role.objects.get(name="Student"),
    # which requires exactly one Student role -- don't create a duplicate).
    teacher_role, _ = Role.objects.get_or_create(name="Teacher")
    Role.objects.get_or_create(name="Student")
    course = CourseFactory()
    teacher = UserFactory()
    EnrollmentFactory(user=teacher, course=course, role=teacher_role)
    return course, teacher


def test_roster_import_creates_users_and_enrollments():
    course, teacher = _course_with_teacher()
    rows = [
        ("Alice A", "alice", "alicepass1", "5"),
        ("Bob B", "bob", "bobpass1", "6"),
        ("Cara C", "cara", "carapass1", "7"),
    ]
    resp = _post_roster(course, teacher, rows)
    assert resp.status_code == 200, resp.content

    for _, username, _, _ in rows:
        assert User.objects.filter(username=username).exists()
        assert Enrollment.objects.filter(
            course=course, user__username=username, role__name="Student"
        ).exists()
    # 3 students + the teacher.
    assert Enrollment.objects.filter(course=course).count() == 4


def test_roster_import_is_idempotent_on_reupload():
    course, teacher = _course_with_teacher()
    rows = [
        ("Alice A", "alice", "alicepass1", "5"),
        ("Bob B", "bob", "bobpass1", "6"),
    ]
    _post_roster(course, teacher, rows)
    first = Enrollment.objects.filter(course=course, role__name="Student").count()

    resp = _post_roster(course, teacher, rows)
    assert resp.status_code == 200, resp.content
    # Re-uploading the same roster must not duplicate enrollments.
    second = Enrollment.objects.filter(course=course, role__name="Student").count()
    assert first == second == 2
    # The reupload reports them as existing, not created.
    assert len(resp.data["enrollments"]["created"]) == 0
    assert len(resp.data["enrollments"]["existing"]) == 2
