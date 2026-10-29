import os
import secrets
import string

from django.conf import settings
from django.db import models
from django.db.models import Q

from teleband.assignments.models import Activity
from teleband.musics.models import Piece

PID_ALPHABET = string.ascii_lowercase + string.digits


def generate_pid():
    return "p_" + "".join(secrets.choice(PID_ALPHABET) for _ in range(12))


def resolve_secret_ref(ref):
    """Look up a secret by its reference (an environment variable name).

    The variable may hold several comma-separated values so that an old and a
    new secret are both accepted while a rotation is in progress.
    """
    if not ref:
        return []
    return [s.strip() for s in os.environ.get(ref, "").split(",") if s.strip()]


class Study(models.Model):
    """One IRB protocol / experiment, each with its own Qualtrics intake survey."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        RECRUITING = "recruiting"
        CLOSED = "closed"

    slug = models.SlugField(unique=True, help_text="Used in URLs: /s/{slug}/...")
    name = models.CharField(max_length=255)
    irb_protocol = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    qualtrics_survey_id = models.CharField(max_length=64, help_text="SV_xxxxxxxx")
    qualtrics_base_url = models.URLField(default="https://jmu.qualtrics.com")
    qualtrics_api_token_ref = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name of the environment variable holding this study's Qualtrics API token.",
    )
    callback_secret_ref = models.CharField(
        max_length=255,
        help_text=(
            "Name of the environment variable holding this study's shared secret "
            "(sent by Qualtrics in the X-Study-Secret header). Comma-separate "
            "values in the variable to accept old and new secrets during rotation."
        ),
    )
    current_consent_version = models.CharField(max_length=64)
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'App behavior, e.g. {"conditions": ["control", "treatment"], '
            '"assignment": "app", "exclude_if_enrolled_in": ["pilot-2026"], '
            '"allow_anonymous": false}'
        ),
    )
    max_enrollment = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Studies"

    def __str__(self):
        return self.name

    def callback_secrets(self):
        return resolve_secret_ref(self.callback_secret_ref)

    def qualtrics_survey_url(self, pid):
        base = self.qualtrics_base_url.rstrip("/")
        return f"{base}/jfe/form/{self.qualtrics_survey_id}?pid={pid}&study={self.slug}"

    def is_full(self):
        if self.max_enrollment is None:
            return False
        return (
            self.participants.filter(
                status__in=StudyParticipant.ENROLLED_STATUSES
            ).count()
            >= self.max_enrollment
        )


class StudyParticipant(models.Model):
    """One row per (person x study). The pid is the only ID shared with Qualtrics.

    Named "participant" rather than "enrollment" to avoid confusion with
    courses.Enrollment.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        CONSENTED = "consented"
        DECLINED = "declined"
        SCREENED_OUT = "screened_out"
        ACTIVE = "active"
        WITHDRAWN = "withdrawn"
        COMPLETED = "completed"

    # Statuses that grant access to the study's part of the app.
    ACCESS_STATUSES = [Status.CONSENTED, Status.ACTIVE]
    # Statuses that count toward a study's max_enrollment.
    ENROLLED_STATUSES = [Status.CONSENTED, Status.ACTIVE, Status.COMPLETED]

    pid = models.CharField(
        primary_key=True, max_length=32, default=generate_pid, editable=False
    )
    study = models.ForeignKey(
        Study, related_name="participants", on_delete=models.PROTECT
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="study_participations",
        on_delete=models.SET_NULL,
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    qualtrics_response_id = models.CharField(
        max_length=64, unique=True, null=True, blank=True
    )
    consent_version = models.CharField(max_length=64, blank=True)
    condition = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    consented_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["study", "user"],
                condition=Q(user__isnull=False),
                name="one_participation_per_user_per_study",
            )
        ]

    def __str__(self):
        return f"{self.pid} ({self.study.slug}, {self.status})"

    @property
    def has_access(self):
        return self.status in self.ACCESS_STATUSES


class PlannedPiece(models.Model):
    """A piece, and which of its activities, a researcher has chosen for a
    teacher participant. Applied to each course the teacher creates."""

    participant = models.ForeignKey(
        StudyParticipant, related_name="planned_pieces", on_delete=models.CASCADE
    )
    piece = models.ForeignKey(Piece, on_delete=models.PROTECT)
    activities = models.ManyToManyField(Activity)

    class Meta:
        unique_together = ["participant", "piece"]

    def __str__(self):
        return f"{self.participant.pid}: {self.piece}"
