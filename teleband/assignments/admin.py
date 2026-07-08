from django.contrib import admin
from django.utils.html import format_html
from reversion.admin import VersionAdmin

from teleband.submissions.models import Submission

from .models import (
    ActivityCategory,
    ActivityType,
    Activity,
    Curriculum,
    CurriculumEntry,
    PiecePlan,
    PlannedActivity,
    AssignmentGroup,
    CourseAssignment,
)


@admin.register(ActivityCategory)
class ActivityCategoryAdmin(VersionAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(ActivityType)
class ActivityTypeAdmin(VersionAdmin):
    list_display = ("id", "name", "category")
    list_filter = ("category",)
    search_fields = ("name",)


@admin.register(Activity)
class ActivityAdmin(VersionAdmin):
    list_display = ("id", "activity_type", "part_type")
    list_filter = ("activity_type", "part_type")


class PiecePlanActivityInline(admin.TabularInline):
    model = PlannedActivity
    extra = 0
    ordering = ("order",)


@admin.register(PiecePlan)
class PiecePlanAdmin(VersionAdmin):
    list_display = (
        "id",
        "name",
        "piece",
        "type",
    )
    list_filter = (
        ("piece", admin.RelatedOnlyFieldListFilter),
        "type",
    )
    inlines = (PiecePlanActivityInline,)
    raw_id_fields = ("activities",)
    save_as = True


@admin.register(AssignmentGroup)
class AssignmentGroupAdmin(VersionAdmin):
    list_display = (
        "id",
        "type",
    )
    list_filter = ("type",)


# @admin.register(PlannedActivity)
# class PlannedActivityAdmin(VersionAdmin):
#     list_display = (
#         "id",
#         "piece_plan",
#         "activity",
#         "order",
#     )
#     list_filter = (
#         "piece_plan",
#         "activity",
#     )


class CurriculumEntryInline(admin.TabularInline):
    model = CurriculumEntry
    extra = 0
    ordering = ("order",)


@admin.register(Curriculum)
class CurriculumAdmin(VersionAdmin):
    list_display = (
        "id",
        "name",
        "course",
        "ordered",
    )
    list_filter = (
        "course",
        "ordered",
    )
    inlines = (CurriculumEntryInline,)
    raw_id_fields = ("piece_plans",)
    save_as = True


class SubmissionInline(admin.TabularInline):
    model = Submission
    extra = 0
    fields = ("id", "enrollment", "instrument", "part", "index", "attachments_list")
    readonly_fields = ("id", "attachments_list")

    def attachments_list(self, obj):
        if not obj.pk:
            return "-"
        attachments = obj.attachments.all()
        if not attachments:
            return "-"
        links = []
        for att in attachments:
            url = att.file.url if att.file else ""
            links.append(format_html('<a href="{}">{}</a>', url, att.file.name))
        return format_html(", ".join(links))

    attachments_list.short_description = "Attachments"


@admin.register(CourseAssignment)
class CourseAssignmentAdmin(VersionAdmin):
    list_display = (
        "id",
        "course",
        "piece",
        "activity",
        "deadline",
        "created_at",
    )
    list_filter = (
        "course",
        "piece",
        "activity",
    )
    inlines = (SubmissionInline,)
