import pytest
from rest_framework.test import APIClient

from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.research.tests.factories import StudyParticipantFactory, SurveyFactory
from teleband.users.models import Role
from teleband.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/users/onboarding/"


@pytest.fixture
def teacher():
    return UserFactory(onboarded_at=None)


@pytest.fixture
def api(teacher):
    client = APIClient()
    client.force_authenticate(teacher)
    return client


def test_new_teacher_has_nothing_set_up(api):
    response = api.get(URL)

    assert response.status_code == 200
    assert response.data == {
        "onboarded_at": None,
        "surveys_due": 0,
        "course": None,
        "student_count": 0,
    }


def make_course(teacher, students):
    teacher_role, _ = Role.objects.get_or_create(name="Teacher")
    student_role, _ = Role.objects.get_or_create(name="Student")
    course = CourseFactory(owner=teacher, name="Band")
    EnrollmentFactory(user=teacher, course=course, role=teacher_role)
    for _ in range(students):
        EnrollmentFactory(course=course, role=student_role)
    return course


def test_reports_course_students_and_surveys(api, teacher):
    course = make_course(teacher, students=2)
    participant = StudyParticipantFactory(user=teacher)
    SurveyFactory(study=participant.study)

    data = api.get(URL).data

    assert data["course"] == {"slug": course.slug, "name": "Band"}
    assert data["student_count"] == 2
    assert data["surveys_due"] == 1


@pytest.mark.parametrize("has_course", [False, True])
def test_cannot_finish_without_students(api, teacher, has_course):
    if has_course:
        make_course(teacher, students=0)

    assert api.post(URL).status_code == 400
    teacher.refresh_from_db()
    assert teacher.onboarded_at is None


def test_post_marks_onboarded_once(api, teacher):
    make_course(teacher, students=1)
    # an outstanding survey does not block finishing
    SurveyFactory(study=StudyParticipantFactory(user=teacher).study)

    first = api.post(URL).data["onboarded_at"]
    assert first is not None

    second = api.post(URL).data["onboarded_at"]
    assert second == first
    teacher.refresh_from_db()
    assert teacher.onboarded_at is not None


def test_requires_login():
    assert APIClient().get(URL).status_code in (401, 403)
