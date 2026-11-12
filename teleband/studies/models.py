import datetime
import hashlib
import hmac
import secrets
import string
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from teleband.assignments.models import Activity
from teleband.musics.models import Piece

PID_ALPHABET = string.ascii_lowercase + string.digits


def generate_pid():
    return "p_" + "".join(secrets.choice(PID_ALPHABET) for _ in range(12))


def hash_callback_secret(secret):
    # The secret is random and high-entropy, so a fast unsalted hash is enough:
    # it can't be brute-forced, and it keeps a leaked database row from being
    # usable as the secret.
    return hashlib.sha256(secret.encode()).hexdigest()


class Study(models.Model):
    """One IRB protocol / experiment, each with its own Qualtrics intake survey."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        RECRUITING = "recruiting"
        # Not accepting new participants; existing ones still get follow-ups.
        CLOSED = "closed"
        # Over: no recruiting and no follow-up surveys.
        ENDED = "ended"

    # Statuses in which consented participants are prompted for follow-ups.
    SURVEY_STATUSES = [Status.RECRUITING, Status.CLOSED]

    slug = models.SlugField(unique=True, help_text="Used in URLs: /s/{slug}/...")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
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
    # SHA-256 of the shared secret Qualtrics sends in the X-Study-Secret
    # header. The secret itself is shown once, when generated, and not stored.
    callback_secret_hash = models.CharField(max_length=64, blank=True, editable=False)
    # Still accepted after a rotation, until revoked, so Qualtrics can be
    # updated without dropping callbacks.
    previous_callback_secret_hash = models.CharField(
        max_length=64, blank=True, editable=False
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

    def generate_callback_secret(self, keep_previous=False):
        """Set a new random callback secret and return it. Only its hash is
        kept, so the caller must show it to the researcher now. With
        keep_previous, the old secret stays valid until revoked. Doesn't save."""
        secret = secrets.token_urlsafe(32)
        self.previous_callback_secret_hash = (
            self.callback_secret_hash if keep_previous else ""
        )
        self.callback_secret_hash = hash_callback_secret(secret)
        return secret

    def check_callback_secret(self, provided):
        provided_hash = hash_callback_secret(provided)
        # Compare against both hashes so timing doesn't reveal which matched.
        matched = False
        for accepted in (self.callback_secret_hash, self.previous_callback_secret_hash):
            if accepted:
                matched |= hmac.compare_digest(provided_hash, accepted)
        return bool(provided) and matched

    def save(self, *args, **kwargs):
        if not self.callback_secret_hash:
            # Never leave a study with no secret. Admin generates (and shows)
            # one itself; this is a backstop for other code paths.
            self.generate_callback_secret()
        super().save(*args, **kwargs)

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
    consented_outside_app = models.BooleanField(
        default=False,
        help_text="Consent was obtained outside Qualtrics and recorded by a researcher.",
    )
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

    @property
    def start_date(self):
        """Day 0 for follow-up surveys: the day consent was recorded."""
        if self.consented_at is None:
            return None
        return timezone.localdate(self.consented_at)


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


class Survey(models.Model):
    """A follow-up Qualtrics survey, due a number of days after consent."""

    study = models.ForeignKey(Study, related_name="surveys", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    url = models.URLField(
        max_length=1000,
        help_text=(
            "Qualtrics anonymous link. The app adds pid and study to it. See "
            "docs/qualtrics_studies.md for the Web Service callback and "
            "end-of-survey redirect."
        ),
    )
    due_after_days = models.PositiveIntegerField(
        default=0,
        help_text="Days after the participant consented. 0 = right away.",
    )
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["due_after_days", "order", "id"]

    def __str__(self):
        return f"{self.study}: {self.title}"

    def due_date(self, participant):
        return participant.start_date + datetime.timedelta(days=self.due_after_days)

    def link_for(self, participant):
        """The survey URL carrying the participant's pid and the study slug."""
        parts = urlparse(self.url)
        query = parse_qsl(parts.query) + [
            ("pid", participant.pid),
            ("study", self.study.slug),
        ]
        return urlunparse(parts._replace(query=urlencode(query)))


class SurveyCompletion(models.Model):
    """Recorded by the Qualtrics Web Service callback when a follow-up is done."""

    survey = models.ForeignKey(
        Survey, related_name="completions", on_delete=models.CASCADE
    )
    participant = models.ForeignKey(
        StudyParticipant, related_name="survey_completions", on_delete=models.CASCADE
    )
    completed_at = models.DateTimeField(default=timezone.now)
    response_id = models.CharField(
        max_length=64, blank=True, help_text="Qualtrics ResponseID"
    )

    class Meta:
        unique_together = ["survey", "participant"]

    def __str__(self):
        return f"{self.participant.pid} completed {self.survey}"
