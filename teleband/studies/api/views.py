import hmac
import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from teleband.studies.models import Study, StudyParticipant
from teleband.studies.services import InvalidCondition, assign_condition

logger = logging.getLogger(__name__)


def secret_matches(provided, accepted):
    # Compare against every accepted secret so timing doesn't reveal which one
    # (if any) was close.
    matched = False
    for secret in accepted:
        matched |= hmac.compare_digest(provided.encode(), secret.encode())
    return matched


class QualtricsCallbackView(APIView):
    """Base for server-to-server calls from a Qualtrics Web Service element.

    Authenticated by the study's shared secret, not by a user session, so DRF
    authentication (and with it CSRF enforcement) is disabled.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, slug):
        study = Study.objects.filter(slug=slug, status=Study.Status.RECRUITING).first()
        if study is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        provided = request.headers.get("X-Study-Secret", "")
        if not secret_matches(provided, study.callback_secrets()):
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

        return self.handle(request, study, participant)

    def handle(self, request, study, participant):
        raise NotImplementedError


class ConsentCallbackView(QualtricsCallbackView):
    def handle(self, request, study, participant):
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

    def handle(self, request, study, participant):
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
