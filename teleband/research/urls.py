from django.urls import path

from teleband.research.views import SurveyStatusView, survey_complete_view

app_name = "research"
urlpatterns = [
    path("surveys/complete/", survey_complete_view, name="survey_complete"),
    path("surveys/status/", SurveyStatusView.as_view(), name="survey_status"),
]
