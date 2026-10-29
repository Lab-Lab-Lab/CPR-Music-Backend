from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from teleband.studies.models import Study, StudyParticipant
from teleband.studies.services import app_home_url, is_eligible, password_set_path

# The onboard page re-checks every POLL_SECONDS, POLL_ATTEMPTS times (~15s),
# while waiting for the Qualtrics consent callback, then offers a button.
POLL_SECONDS = 3
POLL_ATTEMPTS = 5


def status_page(request, study, title, message, http_status=200, **extra):
    context = {"study": study, "title": title, "message": message, **extra}
    return render(request, "studies/status.html", context, status=http_status)


@require_GET
def join(request, slug):
    study = get_object_or_404(Study, slug=slug)
    if study.status != Study.Status.RECRUITING:
        return status_page(
            request,
            study,
            "Not recruiting",
            "This study is not accepting participants.",
        )

    user = request.user if request.user.is_authenticated else None
    if user is None and not study.config.get("allow_anonymous"):
        return redirect_to_login(request.get_full_path())

    participant = None
    if user is not None:
        participant = StudyParticipant.objects.filter(study=study, user=user).first()
    if participant is not None:
        if participant.status == StudyParticipant.Status.PENDING:
            return redirect(study.qualtrics_survey_url(participant.pid))
        return redirect(onboard_url(participant))

    if not is_eligible(study, user):
        return status_page(
            request, study, "Not eligible", "You are not eligible for this study."
        )
    if study.is_full():
        return status_page(
            request, study, "Study full", "This study has reached its enrollment limit."
        )

    participant = StudyParticipant.objects.create(study=study, user=user)
    return redirect(study.qualtrics_survey_url(participant.pid))


def onboard_url(participant):
    path = reverse("studies:onboard", kwargs={"slug": participant.study.slug})
    return f"{path}?pid={participant.pid}"


@require_GET
def onboard(request, slug):
    study = get_object_or_404(Study, slug=slug)
    participant = get_object_or_404(
        StudyParticipant.objects.select_related("user"),
        study=study,
        pid=request.GET.get("pid", ""),
    )

    if participant.has_access:
        user = participant.user
        if user is not None and not user.has_usable_password():
            return redirect(password_set_path(user))
        return status_page(
            request,
            study,
            "You're enrolled",
            "Thank you for completing the questionnaire.",
            continue_url=app_home_url(),
        )

    if participant.status == StudyParticipant.Status.PENDING:
        try:
            attempt = int(request.GET.get("attempt", 0))
        except ValueError:
            attempt = 0
        next_attempt = f"{onboard_url(participant)}&attempt={attempt + 1}"
        return status_page(
            request,
            study,
            "Finishing up…",
            "We're confirming your questionnaire responses. This usually takes a few seconds.",
            refresh_url=next_attempt if attempt < POLL_ATTEMPTS else None,
            refresh_seconds=POLL_SECONDS,
            check_again_url=onboard_url(participant),
        )

    return status_page(
        request, study, "Not enrolled", "You are not enrolled in this study."
    )


@login_required
@require_POST
def withdraw(request, slug):
    study = get_object_or_404(Study, slug=slug)
    participant = get_object_or_404(
        StudyParticipant, study=study, user=request.user, pid=request.POST.get("pid")
    )
    if participant.status != StudyParticipant.Status.WITHDRAWN:
        participant.status = StudyParticipant.Status.WITHDRAWN
        participant.withdrawn_at = timezone.now()
        participant.save()
    return status_page(
        request,
        study,
        "Withdrawn",
        "You have withdrawn from this study. No further study data will be collected.",
    )
