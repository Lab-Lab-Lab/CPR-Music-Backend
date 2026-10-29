from django.urls import path

from teleband.studies.api.views import ConsentCallbackView, DeclinedCallbackView

app_name = "qualtrics"
urlpatterns = [
    path("<slug:slug>/consent", ConsentCallbackView.as_view(), name="consent"),
    path("<slug:slug>/declined", DeclinedCallbackView.as_view(), name="declined"),
]
