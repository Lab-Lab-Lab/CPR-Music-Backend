import logging
import random
from collections import Counter

from allauth.account.adapter import get_adapter
from allauth.account.forms import default_token_generator
from allauth.account.models import EmailAddress
from allauth.account.utils import user_pk_to_url_str
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string

from teleband.courses.helper import assign_one_piece_activity
from teleband.studies.models import StudyParticipant

logger = logging.getLogger(__name__)

User = get_user_model()


class InvalidCondition(Exception):
    pass


def assign_condition(study, posted_condition=""):
    """Pick the participant's experimental arm, per study.config.

    "assignment": "app" (default) balances across the study's consented
    participants, breaking ties at random. "qualtrics" accepts the condition
    Qualtrics posted, if it's one of the study's conditions.
    """
    conditions = study.config.get("conditions") or []
    if not conditions:
        return posted_condition or ""

    if study.config.get("assignment", "app") == "qualtrics":
        if posted_condition not in conditions:
            raise InvalidCondition(posted_condition)
        return posted_condition

    counts = Counter(
        StudyParticipant.objects.filter(
            study=study, status__in=StudyParticipant.ENROLLED_STATUSES
        )
        .exclude(condition="")
        .values_list("condition", flat=True)
    )
    fewest = min(counts.get(c, 0) for c in conditions)
    return random.choice([c for c in conditions if counts.get(c, 0) == fewest])


def is_eligible(study, user):
    """Cross-study eligibility, checked at /join. Uses the internal user_id only."""
    excluded = study.config.get("exclude_if_enrolled_in") or []
    if not excluded or user is None:
        return True
    return not StudyParticipant.objects.filter(
        user=user,
        study__slug__in=excluded,
        status__in=StudyParticipant.ENROLLED_STATUSES,
    ).exists()


def password_set_path(user):
    """Path to allauth's "set a new password" page for this user, valid until
    the password changes (allauth's reset token is tied to the password hash)."""
    key = f"{user_pk_to_url_str(user)}-{default_token_generator.make_token(user)}"
    return get_adapter().get_reset_password_from_key_url(key)


def get_or_create_teacher(email):
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        username = email
        if User.objects.filter(username__iexact=username).exists():
            username = f"{email}-{User.objects.count()}"
        user = User(username=username, email=email)
        user.set_unusable_password()
        user.save()
    user.groups.add(Group.objects.get_or_create(name="Teacher")[0])
    # The teacher proves they own this address by following the emailed link,
    # so mark it verified (ACCOUNT_EMAIL_VERIFICATION is mandatory).
    EmailAddress.objects.update_or_create(
        user=user, email=email, defaults={"verified": True, "primary": True}
    )
    return user


def send_invitation_email(participant):
    context = {
        "participant": participant,
        "study": participant.study,
        "survey_url": participant.study.qualtrics_survey_url(participant.pid),
    }
    send_mail(
        subject=render_to_string(
            "studies/email/invitation_subject.txt", context
        ).strip(),
        message=render_to_string("studies/email/invitation_message.txt", context),
        from_email=None,
        recipient_list=[participant.user.email],
    )


def send_invitation_email_on_commit(participant):
    transaction.on_commit(lambda: send_invitation_email(participant))


def apply_planned_pieces(course, user):
    """Assign the pieces/activities researchers planned for this teacher's
    consented study participations to their newly created course."""
    participants = StudyParticipant.objects.filter(
        user=user, status__in=StudyParticipant.ACCESS_STATUSES
    ).prefetch_related("planned_pieces__piece", "planned_pieces__activities")
    assignments = []
    for participant in participants:
        for planned in participant.planned_pieces.all():
            for activity in planned.activities.all():
                assignments += assign_one_piece_activity(
                    course, planned.piece, activity
                )
    return assignments


def app_home_url():
    return getattr(settings, "STUDIES_APP_HOME_URL", "/")
