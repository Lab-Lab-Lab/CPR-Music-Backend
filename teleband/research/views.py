import datetime
from collections import Counter
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core import signing
from django.shortcuts import redirect
from django.utils import timezone
from django.views import generic

from teleband.assignments.models import CourseAssignment
from teleband.courses.models import Enrollment
from teleband.research.models import (
    SURVEY_TOKEN_PARAM,
    Study,
    Survey,
    SurveyCompletion,
    read_survey_token,
)


def _return_to_frontend(result):
    return redirect(
        f"{settings.RESEARCH_SURVEY_RETURN_URL}?{urlencode({'survey': result})}"
    )


def survey_complete_view(request):
    """Qualtrics end-of-survey redirect target. No login is required: the
    browser coming back from Qualtrics has no session (the frontend uses token
    auth), so the signed token is what identifies the user and survey."""
    try:
        user_id, survey_id = read_survey_token(request.GET.get(SURVEY_TOKEN_PARAM, ""))
    except signing.BadSignature:
        return _return_to_frontend("invalid")

    if not Survey.objects.filter(pk=survey_id).exists():
        return _return_to_frontend("invalid")

    SurveyCompletion.objects.get_or_create(
        survey_id=survey_id,
        user_id=user_id,
        defaults={"response_id": request.GET.get("rid", "")[:255]},
    )
    return _return_to_frontend("completed")


class SurveyStatusView(UserPassesTestMixin, generic.TemplateView):
    """Per-study table of who has taken which survey and whether they are
    using the app at all."""

    template_name = "research/survey_status.html"

    def test_func(self):
        return self.request.user.is_superuser

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()

        studies = list(
            Study.objects.filter(is_active=True).prefetch_related(
                "surveys", "participants__user"
            )
        )
        user_ids = {p.user_id for s in studies for p in s.participants.all()}

        completed = {
            (c.user_id, c.survey_id): c.completed_at
            for c in SurveyCompletion.objects.filter(user_id__in=user_ids)
        }
        courses_taught = Counter(
            Enrollment.objects.filter(
                user_id__in=user_ids, role__name="Teacher"
            ).values_list("user_id", flat=True)
        )
        teacher_course_ids = list(
            Enrollment.objects.filter(
                user_id__in=user_ids, role__name="Teacher"
            ).values_list("user_id", "course_id")
        )
        assignments_by_course = Counter(
            CourseAssignment.objects.filter(
                course_id__in=[c for _, c in teacher_course_ids]
            ).values_list("course_id", flat=True)
        )
        assignments_assigned = Counter()
        for user_id, course_id in teacher_course_ids:
            assignments_assigned[user_id] += assignments_by_course[course_id]

        ctx["studies"] = []
        for study in studies:
            surveys = [s for s in study.surveys.all() if s.is_active]
            rows = []
            for p in study.participants.all():
                cells = []
                for survey in surveys:
                    due_date = p.start_date + datetime.timedelta(
                        days=survey.due_after_days
                    )
                    done_at = completed.get((p.user_id, survey.id))
                    if done_at:
                        cells.append(("done", done_at.date()))
                    elif due_date <= today:
                        cells.append(("overdue", due_date))
                    else:
                        cells.append(("upcoming", due_date))
                rows.append(
                    {
                        "participant": p,
                        "cells": cells,
                        "courses": courses_taught[p.user_id],
                        "assignments": assignments_assigned[p.user_id],
                    }
                )
            ctx["studies"].append({"study": study, "surveys": surveys, "rows": rows})
        return ctx
