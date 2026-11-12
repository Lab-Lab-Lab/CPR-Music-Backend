import datetime
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from teleband.studies.models import (
    Study,
    StudyParticipant,
    SurveyCompletion,
    hash_callback_secret,
)
from teleband.studies.services import due_surveys
from teleband.users.tests.factories import UserFactory

from .factories import StudyParticipantFactory, SurveyFactory

pytestmark = pytest.mark.django_db

START = datetime.date(2026, 10, 1)


@pytest.fixture
def participant():
    consented_at = timezone.make_aware(
        datetime.datetime.combine(START, datetime.time(12))
    )
    return StudyParticipantFactory(consented_at=consented_at)


def due(participant, today):
    return [s for s, _, _ in due_surveys(participant.user, today=today)]


def test_due_surveys_count_from_consent(participant):
    now = SurveyFactory(study=participant.study, due_after_days=0)
    week = SurveyFactory(study=participant.study, due_after_days=7)

    assert due(participant, START - datetime.timedelta(1)) == []
    assert due(participant, START) == [now]
    on_day_7 = due_surveys(participant.user, today=START + datetime.timedelta(7))
    assert [s for s, _, _ in on_day_7] == [now, week]
    assert on_day_7[1][2] == START + datetime.timedelta(7)


def test_due_surveys_excludes_completed_inactive_and_other_studies(participant):
    done = SurveyFactory(study=participant.study)
    SurveyCompletion.objects.create(survey=done, participant=participant)
    SurveyFactory(study=participant.study, is_active=False)
    SurveyFactory()  # a study this user is not in

    assert due(participant, START) == []


@pytest.mark.parametrize(
    "study_status,expected",
    [
        (Study.Status.RECRUITING, 1),
        (Study.Status.CLOSED, 1),
        (Study.Status.ENDED, 0),
        (Study.Status.DRAFT, 0),
    ],
)
def test_due_surveys_by_study_status(participant, study_status, expected):
    SurveyFactory(study=participant.study)
    participant.study.status = study_status
    participant.study.save()

    assert len(due(participant, START)) == expected


@pytest.mark.parametrize(
    "participant_status",
    [StudyParticipant.Status.PENDING, StudyParticipant.Status.WITHDRAWN],
)
def test_due_surveys_need_access(participant, participant_status):
    SurveyFactory(study=participant.study)
    participant.status = participant_status
    participant.save()

    assert due(participant, START) == []


def test_non_participant_has_no_surveys():
    SurveyFactory()
    assert due_surveys(UserFactory()) == []


def test_link_carries_pid_and_keeps_existing_query_params(participant):
    survey = SurveyFactory(
        study=participant.study, url="https://example.qualtrics.com/jfe/form/SV_x?Q=1"
    )
    query = parse_qs(urlparse(survey.link_for(participant)).query)
    assert query == {
        "Q": ["1"],
        "pid": [participant.pid],
        "study": [participant.study.slug],
    }


def test_api_lists_due_surveys(participant):
    survey = SurveyFactory(study=participant.study, title="Intake")
    client = APIClient()
    client.force_authenticate(participant.user)

    response = client.get("/api/surveys/")

    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["id"] == survey.id
    assert response.data[0]["title"] == "Intake"
    assert response.data[0]["study"] == participant.study.name
    assert response.data[0]["url"] == survey.link_for(participant)


def test_api_requires_login():
    assert APIClient().get("/api/surveys/").status_code in (401, 403)


class TestSurveyCompleteCallback:
    @pytest.fixture(autouse=True)
    def secret(self, participant):
        study = participant.study
        study.callback_secret_hash = hash_callback_secret("s3cret")
        study.save()

    def post(self, survey, pid, secret="s3cret", **data):
        return APIClient(enforce_csrf_checks=True).post(
            reverse(
                "qualtrics:survey_complete",
                kwargs={"slug": survey.study.slug, "survey_id": survey.pk},
            ),
            {"pid": pid, **data},
            format="json",
            HTTP_X_STUDY_SECRET=secret,
        )

    def test_records_completion(self, participant):
        survey = SurveyFactory(study=participant.study)

        assert self.post(survey, participant.pid, responseId="R_1").status_code == 200

        completion = SurveyCompletion.objects.get()
        assert (completion.participant, completion.survey) == (participant, survey)
        assert completion.response_id == "R_1"

    def test_idempotent(self, participant):
        survey = SurveyFactory(study=participant.study)
        self.post(survey, participant.pid, responseId="R_1")

        assert self.post(survey, participant.pid, responseId="R_2").status_code == 200
        assert SurveyCompletion.objects.get().response_id == "R_1"

    def test_accepted_while_study_closed(self, participant):
        survey = SurveyFactory(study=participant.study)
        participant.study.status = Study.Status.CLOSED
        participant.study.save()

        assert self.post(survey, participant.pid).status_code == 200

    def test_rejects_bad_secret(self, participant):
        survey = SurveyFactory(study=participant.study)

        assert self.post(survey, participant.pid, secret="nope").status_code == 401
        assert not SurveyCompletion.objects.exists()

    def test_rejects_survey_from_another_study(self, participant):
        other = SurveyFactory()

        response = APIClient().post(
            reverse(
                "qualtrics:survey_complete",
                kwargs={"slug": participant.study.slug, "survey_id": other.pk},
            ),
            {"pid": participant.pid},
            format="json",
            HTTP_X_STUDY_SECRET="s3cret",
        )
        assert response.status_code == 404

    def test_rejects_withdrawn_participant(self, participant):
        survey = SurveyFactory(study=participant.study)
        participant.status = StudyParticipant.Status.WITHDRAWN
        participant.save()

        assert self.post(survey, participant.pid).status_code == 409


def test_survey_done_page_links_to_app(client, settings, participant):
    settings.STUDIES_APP_HOME_URL = "https://app.example/courses"

    response = client.get(
        reverse("studies:survey_done", kwargs={"slug": participant.study.slug})
    )

    assert response.status_code == 200
    assert b"https://app.example/courses" in response.content


def test_status_page_is_superuser_only(client, participant):
    SurveyFactory(study=participant.study, title="Intake")
    url = reverse("studies:survey_status")

    client.force_login(UserFactory())
    assert client.get(url).status_code == 403

    client.force_login(UserFactory(is_superuser=True, is_staff=True))
    response = client.get(url)
    assert response.status_code == 200
    assert b"Intake" in response.content
    assert participant.user.email.encode() in response.content
    assert participant.pid.encode() in response.content
