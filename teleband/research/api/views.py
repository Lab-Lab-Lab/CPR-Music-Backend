from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from teleband.research.models import due_surveys

from .serializers import DueSurveySerializer


class DueSurveyViewSet(ViewSet):
    """Surveys the requesting user should be reminded to take. Reminders only;
    nothing in the app is blocked while surveys are outstanding."""

    def list(self, request):
        serializer = DueSurveySerializer(
            due_surveys(request.user), many=True, context={"request": request}
        )
        return Response(serializer.data)
