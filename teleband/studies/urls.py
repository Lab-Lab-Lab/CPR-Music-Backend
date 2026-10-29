from django.urls import path

from teleband.studies import views

app_name = "studies"
urlpatterns = [
    path("<slug:slug>/join", view=views.join, name="join"),
    path("<slug:slug>/onboard", view=views.onboard, name="onboard"),
    path("<slug:slug>/withdraw", view=views.withdraw, name="withdraw"),
]
