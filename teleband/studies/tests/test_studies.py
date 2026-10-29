import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient

from teleband.assignments.models import CourseAssignment
from teleband.assignments.tests.factories import ActivityFactory
from teleband.courses.tests.factories import CourseFactory
from teleband.musics.tests.factories import PieceFactory
from teleband.studies.models import PlannedPiece, Study, StudyParticipant
from teleband.studies.services import apply_planned_pieces, get_or_create_teacher
from teleband.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

SECRET_ENV = "TEST_STUDY_SECRET"


@pytest.fixture
def study(monkeypatch):
    monkeypatch.setenv(SECRET_ENV, "old-secret,new-secret")
    return Study.objects.create(
        slug="pilot",
        name="Pilot Study",
        status=Study.Status.RECRUITING,
        qualtrics_survey_id="SV_abc123",
        qualtrics_base_url="https://jmu.qualtrics.com",
        callback_secret_ref=SECRET_ENV,
        current_consent_version="v1",
    )


def post_callback(study, pid, kind="consent", secret="new-secret", **data):
    client = APIClient(enforce_csrf_checks=True)
    return client.post(
        reverse(f"qualtrics:{kind}", kwargs={"slug": study.slug}),
        {"pid": pid, **data},
        format="json",
        HTTP_X_STUDY_SECRET=secret,
    )


class TestConsentCallback:
    def test_marks_participant_consented(self, study):
        p = StudyParticipant.objects.create(study=study)
        response = post_callback(study, p.pid, responseId="R_1")
        assert response.status_code == 200
        p.refresh_from_db()
        assert p.status == StudyParticipant.Status.CONSENTED
        assert p.qualtrics_response_id == "R_1"
        assert p.consent_version == "v1"
        assert p.consented_at is not None

    def test_accepts_either_secret_during_rotation(self, study):
        p = StudyParticipant.objects.create(study=study)
        assert post_callback(study, p.pid, secret="old-secret").status_code == 200

    def test_rejects_bad_secret(self, study):
        p = StudyParticipant.objects.create(study=study)
        assert post_callback(study, p.pid, secret="nope").status_code == 401
        assert post_callback(study, p.pid, secret="").status_code == 401
        p.refresh_from_db()
        assert p.status == StudyParticipant.Status.PENDING

    def test_rejects_pid_from_another_study(self, study):
        other = Study.objects.create(
            slug="other",
            name="Other",
            status=Study.Status.RECRUITING,
            qualtrics_survey_id="SV_other",
            callback_secret_ref=SECRET_ENV,
            current_consent_version="v1",
        )
        p = StudyParticipant.objects.create(study=other)
        assert post_callback(study, p.pid).status_code == 404

    def test_404_when_study_not_recruiting(self, study):
        p = StudyParticipant.objects.create(study=study)
        study.status = Study.Status.CLOSED
        study.save()
        assert post_callback(study, p.pid).status_code == 404

    def test_idempotent_and_conflicts(self, study):
        p = StudyParticipant.objects.create(study=study)
        assert post_callback(study, p.pid, responseId="R_1").status_code == 200
        assert post_callback(study, p.pid, responseId="R_1").status_code == 200
        assert post_callback(study, p.pid, responseId="R_2").status_code == 409

    def test_app_assignment_balances_conditions(self, study):
        study.config = {"conditions": ["a", "b"], "assignment": "app"}
        study.save()
        conditions = []
        for i in range(4):
            p = StudyParticipant.objects.create(study=study)
            post_callback(study, p.pid, responseId=f"R_{i}")
            p.refresh_from_db()
            conditions.append(p.condition)
        assert sorted(conditions) == ["a", "a", "b", "b"]

    def test_qualtrics_assignment_validates_condition(self, study):
        study.config = {"conditions": ["a", "b"], "assignment": "qualtrics"}
        study.save()
        p = StudyParticipant.objects.create(study=study)
        assert post_callback(study, p.pid, condition="c").status_code == 400
        assert post_callback(study, p.pid, condition="b").status_code == 200
        p.refresh_from_db()
        assert p.condition == "b"

    def test_declined(self, study):
        p = StudyParticipant.objects.create(study=study)
        response = post_callback(study, p.pid, kind="declined", reason="screened_out")
        assert response.status_code == 200
        p.refresh_from_db()
        assert p.status == StudyParticipant.Status.SCREENED_OUT


class TestJoin:
    def test_logged_in_user_redirected_to_qualtrics_and_reused(self, client, study):
        user = UserFactory()
        client.force_login(user)
        url = reverse("studies:join", kwargs={"slug": study.slug})
        first = client.get(url)
        second = client.get(url)
        p = StudyParticipant.objects.get(study=study, user=user)
        expected = (
            f"https://jmu.qualtrics.com/jfe/form/SV_abc123?pid={p.pid}&study=pilot"
        )
        assert first.url == expected
        assert second.url == expected

    def test_anonymous_requires_login_unless_allowed(self, client, study):
        url = reverse("studies:join", kwargs={"slug": study.slug})
        assert "/accounts/login/" in client.get(url).url
        study.config = {"allow_anonymous": True}
        study.save()
        response = client.get(url)
        assert response.url.startswith("https://jmu.qualtrics.com/")
        assert StudyParticipant.objects.get(study=study).user is None

    def test_full_and_excluded(self, client, study):
        user = UserFactory()
        client.force_login(user)
        url = reverse("studies:join", kwargs={"slug": study.slug})

        pilot2 = Study.objects.create(
            slug="pilot-2",
            name="Pilot 2",
            status=Study.Status.RECRUITING,
            qualtrics_survey_id="SV_2",
            callback_secret_ref=SECRET_ENV,
            current_consent_version="v1",
            config={"exclude_if_enrolled_in": ["pilot"]},
        )
        StudyParticipant.objects.create(
            study=study, user=user, status=StudyParticipant.Status.CONSENTED
        )
        response = client.get(reverse("studies:join", kwargs={"slug": pilot2.slug}))
        assert b"Not eligible" in response.content

        study.max_enrollment = 1
        study.save()
        client.force_login(UserFactory())
        assert b"Study full" in client.get(url).content


class TestOnboard:
    def test_pending_polls(self, client, study):
        p = StudyParticipant.objects.create(study=study)
        url = reverse("studies:onboard", kwargs={"slug": study.slug})
        response = client.get(url, {"pid": p.pid})
        assert b'http-equiv="refresh"' in response.content
        response = client.get(url, {"pid": p.pid, "attempt": 99})
        assert b'http-equiv="refresh"' not in response.content
        assert b"Check again" in response.content

    def test_consented_new_teacher_goes_to_set_password(self, client, study):
        teacher = get_or_create_teacher("teacher@example.com")
        p = StudyParticipant.objects.create(
            study=study, user=teacher, status=StudyParticipant.Status.CONSENTED
        )
        url = reverse("studies:onboard", kwargs={"slug": study.slug})
        response = client.get(url, {"pid": p.pid})
        assert response.status_code == 302
        assert "/accounts/password/reset/key/" in response.url
        # allauth stores the key in the session and redirects to a set-password form.
        follow = client.get(response.url, follow=True)
        assert b"password1" in follow.content

    def test_consented_existing_user_sees_enrolled(self, client, study):
        p = StudyParticipant.objects.create(
            study=study, user=UserFactory(), status=StudyParticipant.Status.CONSENTED
        )
        url = reverse("studies:onboard", kwargs={"slug": study.slug})
        assert b"enrolled" in client.get(url, {"pid": p.pid}).content

    def test_unknown_pid_404(self, client, study):
        url = reverse("studies:onboard", kwargs={"slug": study.slug})
        assert client.get(url, {"pid": "p_nope"}).status_code == 404


def test_withdraw(client, study):
    user = UserFactory()
    p = StudyParticipant.objects.create(
        study=study, user=user, status=StudyParticipant.Status.CONSENTED
    )
    url = reverse("studies:withdraw", kwargs={"slug": study.slug})
    client.force_login(UserFactory())
    assert client.post(url, {"pid": p.pid}).status_code == 404
    client.force_login(user)
    assert client.post(url, {"pid": p.pid}).status_code == 200
    p.refresh_from_db()
    assert p.status == StudyParticipant.Status.WITHDRAWN
    assert p.withdrawn_at is not None


def test_admin_invite_creates_teacher_and_emails_survey_link(
    admin_client, study, django_capture_on_commit_callbacks
):
    piece = PieceFactory()
    activity = ActivityFactory()
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            reverse("admin:studies_studyparticipant_add"),
            {
                "study": study.pk,
                "teacher_email": "new.teacher@example.com",
                "planned_pieces-TOTAL_FORMS": "1",
                "planned_pieces-INITIAL_FORMS": "0",
                "planned_pieces-0-piece": piece.pk,
                "planned_pieces-0-activities": [activity.pk],
            },
        )
    assert response.status_code == 302, response.content
    p = StudyParticipant.objects.get(study=study)
    assert p.user.email == "new.teacher@example.com"
    assert not p.user.has_usable_password()
    assert p.user.groups.filter(name="Teacher").exists()
    assert list(p.planned_pieces.get().activities.all()) == [activity]
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["new.teacher@example.com"]
    assert study.qualtrics_survey_url(p.pid) in mail.outbox[0].body


def test_planned_pieces_assigned_to_new_course(study):
    teacher = get_or_create_teacher("t@example.com")
    p = StudyParticipant.objects.create(
        study=study, user=teacher, status=StudyParticipant.Status.CONSENTED
    )
    piece = PieceFactory()
    activities = [ActivityFactory(), ActivityFactory()]
    planned = PlannedPiece.objects.create(participant=p, piece=piece)
    planned.activities.set(activities)

    course = CourseFactory(owner=teacher)
    apply_planned_pieces(course, teacher)
    assert set(
        CourseAssignment.objects.filter(course=course).values_list(
            "activity_id", flat=True
        )
    ) == {a.id for a in activities}

    # Not applied while consent is still pending.
    p.status = StudyParticipant.Status.PENDING
    p.save()
    other_course = CourseFactory(owner=teacher)
    apply_planned_pieces(other_course, teacher)
    assert not CourseAssignment.objects.filter(course=other_course).exists()


def test_course_create_endpoint_applies_plan(study):
    teacher = get_or_create_teacher("t2@example.com")
    assert Group.objects.get(name="Teacher") in teacher.groups.all()
    p = StudyParticipant.objects.create(
        study=study, user=teacher, status=StudyParticipant.Status.CONSENTED
    )
    planned = PlannedPiece.objects.create(participant=p, piece=PieceFactory())
    planned.activities.set([ActivityFactory()])

    client = APIClient()
    client.force_authenticate(teacher)
    response = client.post(
        "/api/courses/",
        {
            "name": "Band",
            "slug": "band",
            "start_date": "2026-01-01",
            "end_date": "2026-06-01",
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    assert CourseAssignment.objects.filter(course__owner=teacher).count() == 1
