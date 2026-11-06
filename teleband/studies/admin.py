from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from reversion.admin import VersionAdmin

from teleband.studies.models import (
    PlannedPiece,
    Study,
    StudyParticipant,
    Survey,
    SurveyCompletion,
)
from teleband.studies.services import (
    get_or_create_teacher,
    mark_consented_outside_app,
    send_invitation_email_on_commit,
)

User = get_user_model()


class SurveyInline(admin.StackedInline):
    model = Survey
    extra = 0
    verbose_name_plural = "follow-up surveys"


@admin.register(Study)
class StudyAdmin(VersionAdmin):
    list_display = ("id", "slug", "name", "status", "irb_protocol", "max_enrollment")
    list_filter = ("status",)
    search_fields = ("slug", "name", "irb_protocol")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (SurveyInline,)


class PlannedPieceInline(admin.TabularInline):
    model = PlannedPiece
    extra = 1
    filter_horizontal = ("activities",)
    verbose_name = "piece and activities"
    verbose_name_plural = "pieces and activities to assign"


class InviteTeacherForm(forms.ModelForm):
    """Add form: a researcher enters a teacher's email and picks a study. The
    teacher is emailed a link to that study's Qualtrics consent survey, unless
    the researcher says consent was already obtained outside the app."""

    teacher_email = forms.EmailField(
        help_text="An account is created for this teacher if none exists."
    )
    consented_outside_app = forms.BooleanField(
        required=False,
        label="Consent obtained outside the app",
        help_text=(
            "Add this existing user as already consented, without emailing the "
            "consent survey. Follow-up surveys count from today."
        ),
    )

    class Meta:
        model = StudyParticipant
        fields = ("study",)

    def clean(self):
        cleaned = super().clean()
        study, email = cleaned.get("study"), cleaned.get("teacher_email")
        if (
            study
            and email
            and StudyParticipant.objects.filter(
                study=study, user__email__iexact=email
            ).exists()
        ):
            raise forms.ValidationError(f"{email} is already a participant in {study}.")
        if (
            email
            and cleaned.get("consented_outside_app")
            and not User.objects.filter(email__iexact=email).exists()
        ):
            self.add_error(
                "teacher_email",
                "No account has this email. Invite them instead, or create "
                "the account first.",
            )
        return cleaned


@admin.register(StudyParticipant)
class StudyParticipantAdmin(VersionAdmin):
    list_display = (
        "pid",
        "study",
        "user",
        "status",
        "condition",
        "consent_version",
        "created_at",
        "consented_at",
    )
    list_filter = ("study", "status", "condition")
    search_fields = ("pid", "user__username", "user__email", "qualtrics_response_id")
    raw_id_fields = ("user",)
    readonly_fields = (
        "pid",
        "created_at",
        "consented_at",
        "withdrawn_at",
        "consented_outside_app",
    )
    inlines = (PlannedPieceInline,)
    actions = ("resend_invitation",)

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = InviteTeacherForm
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("study", "teacher_email", "consented_outside_app")
        return super().get_fields(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return super().get_readonly_fields(request, obj)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.user = get_or_create_teacher(form.cleaned_data["teacher_email"])
            if form.cleaned_data["consented_outside_app"]:
                mark_consented_outside_app(obj)
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if change:
            return
        if form.instance.consented_outside_app:
            self.message_user(
                request, f"Added {form.instance.user.email} as already consented."
            )
        else:
            send_invitation_email_on_commit(form.instance)
            self.message_user(
                request, f"Invitation emailed to {form.instance.user.email}."
            )

    @admin.action(
        description="Resend invitation email to selected pending participants"
    )
    def resend_invitation(self, request, queryset):
        sent = 0
        for participant in queryset.filter(
            status=StudyParticipant.Status.PENDING, user__isnull=False
        ).select_related("study", "user"):
            send_invitation_email_on_commit(participant)
            sent += 1
        self.message_user(request, f"Resent {sent} invitation(s).", messages.SUCCESS)


@admin.register(SurveyCompletion)
class SurveyCompletionAdmin(admin.ModelAdmin):
    list_display = ("id", "participant", "survey", "completed_at", "response_id")
    list_filter = ("survey__study", "survey")
    search_fields = (
        "participant__pid",
        "participant__user__username",
        "participant__user__email",
        "response_id",
    )
    raw_id_fields = ("participant",)
