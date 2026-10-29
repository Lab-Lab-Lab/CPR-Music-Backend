import datetime
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from teleband.research.models import SurveyCompletion, due_surveys
from teleband.users.tests.factories import UserFactory

from .factories import StudyParticipantFactory, SurveyFactory

pytestmark = pytest.mark.django_db

START = datetime.date(2026, 10, 1)


@pytest.fixture
def participant():
    return StudyParticipantFactory(start_date=START)


def token_from(url):
    return parse_qs(urlparse(url).query)["mcpr"][0]


def test_due_surveys_respects_due_after_days(participant):
    now = SurveyFactory(study=participant.study, due_after_days=0)
    week = SurveyFactory(study=participant.study, due_after_days=7)

    assert [s for s, _ in due_surveys(participant.user, today=START)] == [now]
    on_day_7 = due_surveys(participant.user, today=START + datetime.timedelta(7))
    assert [s for s, _ in on_day_7] == [now, week]
    assert on_day_7[1][1] == START + datetime.timedelta(7)


def test_due_surveys_excludes_completed_inactive_and_other_studies(participant):
    done = SurveyFactory(study=participant.study)
    SurveyCompletion.objects.create(survey=done, user=participant.user)
    SurveyFactory(study=participant.study, is_active=False)
    SurveyFactory()  # a study this user is not in

    assert due_surveys(participant.user, today=START) == []


def test_due_surveys_skips_inactive_study(participant):
    SurveyFactory(study=participant.study)
    participant.study.is_active = False
    participant.study.save()

    assert due_surveys(participant.user, today=START) == []


def test_non_participant_has_no_surveys():
    SurveyFactory()
    assert due_surveys(UserFactory()) == []


def test_link_keeps_existing_query_params(participant):
    survey = SurveyFactory(
        study=participant.study, url="https://example.qualtrics.com/jfe/form/SV_x?Q=1"
    )
    query = parse_qs(urlparse(survey.link_for(participant.user)).query)
    assert query["Q"] == ["1"]
    assert "mcpr" in query


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
    assert response.data[0]["url"].startswith(survey.url)


def test_api_requires_login():
    assert APIClient().get("/api/surveys/").status_code in (401, 403)


def test_complete_records_completion_and_redirects(client, settings, participant):
    settings.RESEARCH_SURVEY_RETURN_URL = "https://app.example/courses"
    survey = SurveyFactory(study=participant.study)
    token = token_from(survey.link_for(participant.user))

    response = client.get(
        reverse("research:survey_complete"), {"mcpr": token, "rid": "R_123"}
    )

    assert response.status_code == 302
    assert response.url == "https://app.example/courses?survey=completed"
    completion = SurveyCompletion.objects.get()
    assert (completion.user, completion.survey) == (participant.user, survey)
    assert completion.response_id == "R_123"


def test_complete_twice_keeps_one_completion(client, participant):
    survey = SurveyFactory(study=participant.study)
    token = token_from(survey.link_for(participant.user))
    url = reverse("research:survey_complete")

    client.get(url, {"mcpr": token, "rid": "R_1"})
    client.get(url, {"mcpr": token, "rid": "R_2"})

    assert SurveyCompletion.objects.get().response_id == "R_1"


@pytest.mark.parametrize("token", ["", "garbage", "tampered"])
def test_complete_rejects_bad_tokens(client, participant, token):
    survey = SurveyFactory(study=participant.study)
    if token == "tampered":
        token = token_from(survey.link_for(participant.user))[:-2] + "xx"

    response = client.get(reverse("research:survey_complete"), {"mcpr": token})

    assert response.status_code == 302
    assert response.url.endswith("?survey=invalid")
    assert not SurveyCompletion.objects.exists()


def test_status_page_is_superuser_only(client, participant):
    SurveyFactory(study=participant.study, title="Intake")
    url = reverse("research:survey_status")

    client.force_login(UserFactory())
    assert client.get(url).status_code == 403

    client.force_login(UserFactory(is_superuser=True, is_staff=True))
    response = client.get(url)
    assert response.status_code == 200
    assert b"Intake" in response.content
    assert participant.user.email.encode() in response.content
