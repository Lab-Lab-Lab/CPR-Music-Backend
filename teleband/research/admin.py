from django.contrib import admin

from .models import Study, StudyParticipant, Survey, SurveyCompletion


class SurveyInline(admin.StackedInline):
    model = Survey
    extra = 0


class StudyParticipantInline(admin.TabularInline):
    model = StudyParticipant
    extra = 0
    raw_id_fields = ("user",)


@admin.register(Study)
class StudyAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    inlines = [SurveyInline, StudyParticipantInline]


@admin.register(StudyParticipant)
class StudyParticipantAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "study", "start_date")
    list_filter = ("study",)
    search_fields = ("user__username", "user__email", "study__name")
    raw_id_fields = ("user",)


@admin.register(SurveyCompletion)
class SurveyCompletionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "survey", "completed_at", "response_id")
    list_filter = ("survey__study", "survey")
    search_fields = ("user__username", "user__email", "response_id")
    raw_id_fields = ("user",)
