from rest_framework import serializers

from teleband.submissions.models import (
    Grade,
    Submission,
    SubmissionAttachment,
    ActivityProgress,
)

# from teleband.assignments.api.serializers import AssignmentSerializer


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubmissionAttachment
        fields = ["id", "file", "submitted"]


class SubmissionSerializer(serializers.ModelSerializer):
    attachments = AttachmentSerializer(many=True, required=False)

    class Meta:
        model = Submission
        fields = [
            "id",
            "submitted",
            "content",
            "grade",
            "self_grade",
            "attachments",
            "index",
        ]

        # extra_kwargs = {
        #     "assignment": {"view_name": "api:assignment-detail", "lookup_field": "id"},
        # }


class GradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Grade
        fields = [
            "id",
            "rhythm",
            "tone",
            "expression",
            "created_at",
            "grader",
            "student_submission",
            "own_submission",
        ]


class ActivityProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityProgress
        fields = [
            "id",
            "assignment",
            "current_step",
            "step_completions",
            "activity_logs",
            "question_responses",
            "participant_email",
            "current_audio_url",
            "audio_edit_history",
            "audio_metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]
