import pytest
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient

from teleband.assignments.models import (
    CourseAssignment,
    Curriculum,
    CurriculumEntry,
    PiecePlan,
    PlannedActivity,
)
from teleband.assignments.tests.factories import ActivityFactory
from teleband.courses.models import Course, Enrollment
from teleband.courses.tests.factories import CourseFactory
from teleband.musics.tests.factories import PieceFactory
from teleband.studies.models import Study, StudyParticipant, hash_callback_secret
from teleband.studies.services import get_or_create_teacher
from teleband.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def set_secrets(study, current, previous=""):
    study.callback_secret_hash = hash_callback_secret(current)
    study.previous_callback_secret_hash = previous and hash_callback_secret(previous)
    study.save()
    return study


@pytest.fixture
def study():
    study = Study.objects.create(
        slug="pilot",
        name="Pilot Study",
        status=Study.Status.RECRUITING,
        qualtrics_survey_id="SV_abc123",
        qualtrics_base_url="https://jmu.qualtrics.com",
        current_consent_version="v1",
    )
    return set_secrets(study, "new-secret", previous="old-secret")


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


def make_curriculum(*piece_plans, name="Template", course=None):
    curriculum = Curriculum.objects.create(name=name, course=course or CourseFactory())
    for order, plan in enumerate(piece_plans):
        CurriculumEntry.objects.create(
            curriculum=curriculum, piece_plan=plan, order=order
        )
    return curriculum


def make_piece_plan(n_activities=2, type=None):
    plan = PiecePlan.objects.create(name="Plan", piece=PieceFactory(), type=type)
    for order in range(n_activities):
        PlannedActivity.objects.create(
            piece_plan=plan, activity=ActivityFactory(), order=order
        )
    return plan


def _admin_add(admin_client, study, email, **extra):
    data = {
        "study": study.pk,
        "teacher_email": email,
        "curriculum_choice": "new",
    }
    data.update(extra)
    return admin_client.post(reverse("admin:studies_studyparticipant_add"), data)


def test_admin_invite_copies_curriculum_to_new_course(
    admin_client, study, django_capture_on_commit_callbacks
):
    plans = [make_piece_plan(), make_piece_plan()]
    template = make_curriculum(*plans)
    with django_capture_on_commit_callbacks(execute=True):
        response = _admin_add(
            admin_client,
            study,
            "new.teacher@example.com",
            curriculum_choice="copy",
            copy_from=template.pk,
        )
    assert response.status_code == 302, response.content
    assert response.url == reverse("admin:studies_studyparticipant_changelist")
    p = StudyParticipant.objects.get(study=study)
    assert p.user.email == "new.teacher@example.com"
    assert not p.user.has_usable_password()
    assert p.user.groups.filter(name="Teacher").exists()

    # A course the teacher owns and teaches, named after the participant.
    course = p.curriculum.course
    assert course.name == "Pilot Study: new.teacher@example.com"
    assert course.owner == p.user
    assert Enrollment.objects.get(course=course).user == p.user
    assert Enrollment.objects.get(course=course).role.name == "Teacher"

    # A copy of the template, on that course. Nothing is assigned; the
    # teacher does that when they're ready.
    assert p.curriculum != template
    assert p.curriculum.name == course.name
    assert list(
        p.curriculum.curriculumentry_set.values_list("piece_plan", flat=True)
    ) == [plan.pk for plan in plans]
    assert not CourseAssignment.objects.filter(
        course__in=[course, template.course]
    ).exists()

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["new.teacher@example.com"]
    assert study.qualtrics_survey_url(p.pid) in mail.outbox[0].body


def test_admin_invite_new_curriculum_goes_to_it(admin_client, study):
    response = _admin_add(
        admin_client, study, "t@example.com", new_curriculum_name="Fall plan"
    )
    p = StudyParticipant.objects.get(study=study)
    curriculum = p.curriculum
    assert curriculum.name == "Fall plan"
    assert curriculum.course.owner == p.user
    assert not curriculum.piece_plans.exists()
    assert response.url == reverse(
        "admin:assignments_curriculum_change", args=[curriculum.pk]
    )


def test_admin_invite_copy_requires_curriculum(admin_client, study):
    courses, curricula = Course.objects.count(), Curriculum.objects.count()
    response = _admin_add(
        admin_client, study, "t@example.com", curriculum_choice="copy"
    )
    assert response.status_code == 200
    assert b"Choose a curriculum to copy" in response.content
    assert not StudyParticipant.objects.exists()
    assert Course.objects.count() == courses
    assert Curriculum.objects.count() == curricula


def test_admin_change_page_links_curriculum_and_course(admin_client, study):
    curriculum = make_curriculum(name="Mine")
    p = StudyParticipant.objects.create(study=study, curriculum=curriculum)
    response = admin_client.get(
        reverse("admin:studies_studyparticipant_change", args=[p.pk])
    )
    assert response.status_code == 200
    html = response.content.decode()
    assert reverse("admin:assignments_curriculum_change", args=[curriculum.pk]) in html
    assert reverse("admin:courses_course_change", args=[curriculum.course.pk]) in html


def test_admin_add_consented_outside_app(
    admin_client, study, django_capture_on_commit_callbacks
):
    user = UserFactory(email="known@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        response = _admin_add(
            admin_client, study, "known@example.com", consented_outside_app="on"
        )
    assert response.status_code == 302, response.content
    p = StudyParticipant.objects.get(study=study)
    assert p.user == user
    assert p.status == StudyParticipant.Status.ACTIVE
    assert p.consented_outside_app
    assert p.consented_at is not None
    assert p.consent_version == study.current_consent_version
    assert mail.outbox == []


def test_admin_add_consented_requires_existing_account(admin_client, study):
    response = _admin_add(
        admin_client, study, "nobody@example.com", consented_outside_app="on"
    )
    assert response.status_code == 200
    assert b"No account has this email" in response.content
    assert not StudyParticipant.objects.exists()


class TestCallbackSecret:
    def test_only_hash_is_stored(self, study):
        secret = study.generate_callback_secret()
        study.save()
        study.refresh_from_db()
        assert secret not in (
            study.callback_secret_hash,
            study.previous_callback_secret_hash,
        )
        assert study.check_callback_secret(secret)
        assert not study.check_callback_secret("new-secret")

    def test_rotation_keeps_previous_until_revoked(self, study):
        secret = study.generate_callback_secret(keep_previous=True)
        assert study.check_callback_secret(secret)
        assert study.check_callback_secret("new-secret")
        assert not study.check_callback_secret("old-secret")

    def test_empty_secret_never_matches(self, study):
        study.previous_callback_secret_hash = hash_callback_secret("")
        assert not study.check_callback_secret("")

    def test_new_study_always_has_a_secret(self):
        study = Study.objects.create(
            slug="s", name="S", qualtrics_survey_id="SV_1", current_consent_version="v1"
        )
        assert study.callback_secret_hash

    def test_admin_shows_secret_once_on_add(self, admin_client):
        response = admin_client.post(
            reverse("admin:studies_study_add"),
            {
                "slug": "new",
                "name": "New",
                "status": "draft",
                "qualtrics_survey_id": "SV_1",
                "qualtrics_base_url": "https://jmu.qualtrics.com",
                "current_consent_version": "v1",
                "config": "{}",
                "surveys-TOTAL_FORMS": "0",
                "surveys-INITIAL_FORMS": "0",
            },
            follow=True,
        )
        msgs = [str(m) for m in response.context["messages"]]
        secret_msg = next(m for m in msgs if "X-Study-Secret for new:" in m)
        secret = secret_msg.split(": ", 1)[1].split(" ")[0]
        assert Study.objects.get(slug="new").check_callback_secret(secret)

    def test_admin_rotate_and_revoke(self, admin_client, study):
        url = reverse("admin:studies_study_changelist")
        response = admin_client.post(
            url,
            {"action": "rotate_callback_secret", "_selected_action": [study.pk]},
            follow=True,
        )
        msg = next(
            str(m) for m in response.context["messages"] if "X-Study-Secret" in str(m)
        )
        secret = msg.split(": ", 1)[1].split(" ")[0]
        study.refresh_from_db()
        assert study.check_callback_secret(secret)
        assert study.check_callback_secret("new-secret")

        admin_client.post(
            url,
            {
                "action": "revoke_previous_callback_secret",
                "_selected_action": [study.pk],
            },
        )
        study.refresh_from_db()
        assert study.check_callback_secret(secret)
        assert not study.check_callback_secret("new-secret")
