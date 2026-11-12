import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from teleband.studies.api.serializers import DueSurveySerializer
from teleband.studies.models import Study, StudyParticipant, SurveyCompletion
from teleband.studies.services import InvalidCondition, assign_condition, due_surveys

logger = logging.getLogger(__name__)


class QualtricsCallbackView(APIView):
    """Base for server-to-server calls from a Qualtrics Web Service element.

    Authenticated by the study's shared secret, not by a user session, so DRF
    authentication (and with it CSRF enforcement) is disabled.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    # Study statuses in which this callback is accepted.
    study_statuses = [Study.Status.RECRUITING]

    def post(self, request, slug, **kwargs):
        study = Study.objects.filter(slug=slug, status__in=self.study_statuses).first()
        if study is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        provided = request.headers.get("X-Study-Secret", "")
        if not study.check_callback_secret(provided):
            logger.warning("Bad X-Study-Secret for study %s", slug)
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        pid = request.data.get("pid", "")
        participant = (
            StudyParticipant.objects.select_for_update()
            .filter(pid=pid, study=study)
            .first()
        )
        if participant is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        return self.handle(request, study, participant, **kwargs)

    def handle(self, request, study, participant, **kwargs):
        raise NotImplementedError


class ConsentCallbackView(QualtricsCallbackView):
    def handle(self, request, study, participant, **kwargs):
        response_id = request.data.get("responseId") or None
        if (
            participant.status == StudyParticipant.Status.CONSENTED
            and participant.qualtrics_response_id == response_id
        ):
            return Response(status=status.HTTP_200_OK)
        if participant.status != StudyParticipant.Status.PENDING:
            return Response(status=status.HTTP_409_CONFLICT)
        if (
            response_id
            and StudyParticipant.objects.filter(qualtrics_response_id=response_id)
            .exclude(pk=participant.pk)
            .exists()
        ):
            return Response(status=status.HTTP_409_CONFLICT)

        try:
            condition = assign_condition(study, request.data.get("condition", ""))
        except InvalidCondition:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"error": "condition is not one of this study's conditions"},
            )

        participant.status = StudyParticipant.Status.CONSENTED
        participant.qualtrics_response_id = response_id
        participant.consent_version = (
            request.data.get("consentVersion") or study.current_consent_version
        )
        participant.condition = condition
        participant.consented_at = timezone.now()
        participant.save()
        return Response(status=status.HTTP_200_OK)


class DeclinedCallbackView(QualtricsCallbackView):
    """Records an explicit decline, or a screen-out if reason=screened_out."""

    def handle(self, request, study, participant, **kwargs):
        new_status = (
            StudyParticipant.Status.SCREENED_OUT
            if request.data.get("reason") == "screened_out"
            else StudyParticipant.Status.DECLINED
        )
        if participant.status == new_status:
            return Response(status=status.HTTP_200_OK)
        if participant.status != StudyParticipant.Status.PENDING:
            return Response(status=status.HTTP_409_CONFLICT)

        participant.status = new_status
        participant.qualtrics_response_id = request.data.get("responseId") or None
        participant.save()
        return Response(status=status.HTTP_200_OK)


class SurveyCompleteCallbackView(QualtricsCallbackView):
    """Records that a participant finished one of the study's follow-up surveys."""

    study_statuses = Study.SURVEY_STATUSES

    def handle(self, request, study, participant, survey_id):
        survey = study.surveys.filter(pk=survey_id).first()
        if survey is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not participant.has_access:
            return Response(status=status.HTTP_409_CONFLICT)

        SurveyCompletion.objects.get_or_create(
            survey=survey,
            participant=participant,
            defaults={"response_id": request.data.get("responseId") or ""},
        )
        return Response(status=status.HTTP_200_OK)


class DueSurveyViewSet(ViewSet):
    """Follow-up surveys the requesting user should be reminded to take.
    Reminders only; nothing in the app is blocked while surveys are outstanding."""

    def list(self, request):
        serializer = DueSurveySerializer(due_surveys(request.user), many=True)
        return Response(serializer.data)
