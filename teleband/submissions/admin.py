from django.contrib import admin
from reversion.admin import VersionAdmin

from .models import Submission, SubmissionAttachment, Grade, ActivityProgress


@admin.register(Submission)
class SubmissionAdmin(VersionAdmin):
    list_display = (
        "id",
        "course_assignment",
        "enrollment",
        "submitted",
    )
    list_filter = ("course_assignment__piece",)
    raw_id_fields = ("course_assignment", "enrollment", "instrument", "part")


@admin.register(SubmissionAttachment)
class SubmissionAttachmentAdmin(VersionAdmin):
    list_display = ("id", "submission", "file")
    raw_id_fields = ("submission",)
    # list_filter = ("submission",)


@admin.register(Grade)
class GradeAdmin(VersionAdmin):
    list_display = (
        "id",
        # "student_submission",
        # "own_submission",
        "grader",
        "rhythm",
        "tone",
        "expression",
        "created_at",
    )
    # list_filter = ("student_submission", "own_submission", "grader")
    list_filter = ("grader",)


@admin.register(ActivityProgress)
class ActivityProgressAdmin(VersionAdmin):
    list_display = (
        "id",
        "course_assignment",
        "enrollment",
        "current_step",
        "participant_email",
        "created_at",
        "updated_at",
    )
    list_filter = ("current_step", "created_at")
    search_fields = ("participant_email", "course_assignment__id")
    readonly_fields = (
        "activity_logs",
        "step_completions",
        "question_responses",
        "audio_edit_history",
        "audio_metadata",
        "created_at",
        "updated_at",
    )
    raw_id_fields = ("course_assignment", "enrollment")
