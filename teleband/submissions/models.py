from django.db import models
from django.conf import settings

from teleband.assignments.models import Assignment


class Grade(models.Model):

    # submission = models.ForeignKey(Submission, related_name="grades", on_delete=models.PROTECT)
    grader = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="grades", on_delete=models.PROTECT
    )
    rhythm = models.FloatField(null=True, blank=True)
    tone = models.FloatField(null=True, blank=True)
    expression = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Submission(models.Model):
    grade = models.ForeignKey(
        Grade,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="student_submission",
    )
    self_grade = models.ForeignKey(
        Grade,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="own_submission",
    )
    # Legacy per-student link. Nullable during the Phase 2 transition so late
    # joiners (no Assignment row) can submit against a CourseAssignment; dropped
    # in step 8 once reads no longer use it.
    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.PROTECT,
        related_name="submissions",
        null=True,
        blank=True,
    )
    # Phase 2: a submission belongs to a course-level CourseAssignment and the
    # student (enrollment) who made it, and records the instrument/part it was
    # made with. Nullable during the transition (dual-populated from `assignment`);
    # `assignment` is dropped once the read path no longer uses it.
    course_assignment = models.ForeignKey(
        "assignments.CourseAssignment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submissions",
    )
    enrollment = models.ForeignKey(
        "courses.Enrollment", on_delete=models.PROTECT, null=True, blank=True
    )
    instrument = models.ForeignKey(
        "instruments.Instrument", on_delete=models.PROTECT, null=True, blank=True
    )
    part = models.ForeignKey(
        "musics.Part", on_delete=models.PROTECT, null=True, blank=True
    )
    index = models.PositiveIntegerField(default=0)
    submitted = models.DateTimeField(auto_now_add=True)
    content = models.TextField(blank=True)

    class Meta:
        indexes = [
            # Supports "latest submission per assignment" lookups
            # (TeacherSubmissionViewSet.recent orders by -submitted per assignment).
            models.Index(fields=["assignment", "-submitted"]),
        ]

    def __str__(self):
        return f"{self.assignment.id}"


class SubmissionAttachment(models.Model):

    submission = models.ForeignKey(
        Submission, related_name="attachments", on_delete=models.PROTECT
    )
    file = models.FileField()
    submitted = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Submission Attachment"
        verbose_name_plural = "Submission Attachments"
        ordering = ["-submitted"]
        indexes = [
            # Backs the per-submission, newest-first ordering above.
            models.Index(fields=["submission", "-submitted"]),
        ]

    def __str__(self):
        return f"{self.submission.id}: {self.file}"


class ActivityProgress(models.Model):
    """Tracks student progress through DAW study activities."""

    assignment = models.OneToOneField(
        Assignment,
        on_delete=models.CASCADE,
        related_name="activity_progress",
        null=True,
        blank=True,
    )
    # Phase 2: progress is per (course_assignment, enrollment). Nullable during the
    # transition (dual-populated from `assignment`); the unique (course_assignment,
    # enrollment) constraint and dropping `assignment` happen when reads flip.
    course_assignment = models.ForeignKey(
        "assignments.CourseAssignment",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="activity_progress",
    )
    enrollment = models.ForeignKey(
        "courses.Enrollment", on_delete=models.CASCADE, null=True, blank=True
    )
    current_step = models.PositiveIntegerField(default=1)  # 1-4 for Activities 1-4
    step_completions = models.JSONField(
        default=dict,
        help_text="Tracks completed operations per step: {step: [operation_type, ...]}",
    )
    activity_logs = models.JSONField(
        default=list,
        help_text="Array of timestamped events: [{timestamp, step, operation, data}, ...]",
    )
    question_responses = models.JSONField(
        default=dict,
        help_text="Student responses to embedded questions: {question_id: response, ...}",
    )
    participant_email = models.EmailField(
        blank=True, null=True, help_text="Email from Qualtrics for survey matching"
    )

    # Audio state persistence for cross-activity editing
    current_audio_url = models.TextField(
        blank=True, null=True, help_text="Current audio blob URL or file path"
    )
    audio_edit_history = models.JSONField(
        default=list,
        help_text="Array of edit history states for undo/redo: [{url, effectName, metadata}, ...]",
    )
    audio_metadata = models.JSONField(
        default=dict,
        help_text="Additional audio metadata: {duration, sampleRate, numberOfChannels, ...}",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Activity Progress"
        verbose_name_plural = "Activity Progress"

    def __str__(self):
        return f"Assignment {self.assignment.id} - Step {self.current_step}"
