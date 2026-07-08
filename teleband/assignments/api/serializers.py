from rest_framework import serializers

from teleband.assignments.models import (
    Activity,
    ActivityType,
    AssignmentGroup,
    CourseAssignment,
    GroupAssignment,
    PiecePlan,
)
from teleband.musics.models import Part
from teleband.submissions.models import Submission
from teleband.courses.api.serializers import EnrollmentSerializer
from teleband.instruments.api.serializers import InstrumentSerializer
from teleband.submissions.api.serializers import SubmissionSerializer
from teleband.utils.serializers import GenericNameSerializer
from teleband.musics.api.serializers import (
    PartTranspositionSerializer,
    PartSerializer,
    PieceSerializer,
)


class ActivityTypeSerializer(serializers.ModelSerializer):
    category = GenericNameSerializer()

    class Meta:
        model = ActivityType
        fields = ["name", "category"]


class ActivitySerializer(serializers.ModelSerializer):
    activity_type = ActivityTypeSerializer()
    part_type = GenericNameSerializer()

    class Meta:
        model = Activity
        fields = ["activity_type", "part_type", "body"]


class GroupSerializer(serializers.ModelSerializer):
    type = serializers.CharField(read_only=True)
    members = serializers.SerializerMethodField(method_name="get_members")

    def get_members(self, obj):
        # Phase 2: group membership comes from GroupAssignment (was per-student
        # Assignment.group). Memoize per group.id in the shared serializer context
        # so this runs once per distinct group, not once per member row. One query
        # for the memberships and one for which (course_assignment, enrollment)
        # pairs have a submission keep this off the per-row N+1 path.
        cache = self.context.setdefault("_group_members", {})
        if obj.id not in cache:
            memberships = list(
                GroupAssignment.objects.filter(group=obj).select_related(
                    "enrollment__user", "course_assignment__activity"
                )
            )
            submitted = set(
                Submission.objects.filter(
                    course_assignment_id__in=[
                        m.course_assignment_id for m in memberships
                    ],
                    enrollment_id__in=[m.enrollment_id for m in memberships],
                ).values_list("course_assignment_id", "enrollment_id")
            )
            cache[obj.id] = [
                {
                    "enrollment_id": m.enrollment_id,
                    "enrollment_username": m.enrollment.user.username,
                    "activity_type_name": m.course_assignment.activity.activity_type_name,
                    "assignment_submitted": (
                        m.course_assignment_id,
                        m.enrollment_id,
                    )
                    in submitted,
                }
                for m in memberships
            ]
        return cache[obj.id]

    class Meta:
        model = AssignmentGroup
        fields = ["type", "members"]


class PiecePlanSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField()
    type = serializers.CharField()
    # piece = serializers.SlugRelatedField(slug_field="name", read_only=True)
    piece = PieceSerializer()
    activities = ActivitySerializer(many=True)

    class Meta:
        model = PiecePlan
        fields = ["id", "piece", "type", "activities"]

        # extra_kwargs = {
        #     "url": {"view_name": "api:pieceplan-detail", "lookup_field": "id"},
        # }


def resolve_instrument(enrollment, course_assignment=None):
    """The instrument a student uses for a CourseAssignment: the course-level
    per-piece override (``CourseAssignment.instrument``, set by
    change_piece_instrument) if present, else their enrollment instrument, else
    their user instrument."""
    if course_assignment is not None and course_assignment.instrument_id:
        return course_assignment.instrument
    return enrollment.instrument or enrollment.user.instrument


class CourseAssignmentReadSerializer(serializers.Serializer):
    """Phase 2 read path: produces the SAME per-assignment shape as
    AssignmentViewSetSerializer, but resolved from a CourseAssignment against a
    student enrollment (passed in context as ``enrollment``). The ``id`` is the
    CourseAssignment id. Per-student data (instrument, part, submissions, group) is
    resolved at read time. A response-equivalence test pins that this matches the
    legacy per-student serializer field-for-field except ``id``.

    For list rendering the view precomputes per-CA maps (``submissions_by_ca``,
    ``group_by_ca``, ``part_for``) and passes them in context, so resolution is
    O(1) per row instead of N+1. When those maps are absent (single-object use,
    e.g. the equivalence test) it falls back to direct queries."""

    def _submissions_for(self, ca, enrollment):
        by_ca = self.context.get("submissions_by_ca")
        if by_ca is not None:
            return by_ca.get(ca.id, [])
        if enrollment is None:
            # Teacher list: no per-student enrollment, so no per-student submissions.
            return []
        return list(
            Submission.objects.filter(course_assignment=ca, enrollment=enrollment)
            .order_by("id")
            .prefetch_related("attachments")
        )

    def _group_for(self, ca, enrollment):
        by_ca = self.context.get("group_by_ca")
        if by_ca is not None:
            return by_ca.get(ca.id)
        if enrollment is None:
            return None
        group_assignment = (
            GroupAssignment.objects.select_related("group")
            .filter(course_assignment=ca, enrollment=enrollment)
            .first()
        )
        return group_assignment.group if group_assignment else None

    def _part_for(self, ca):
        part_for = self.context.get("part_for")
        if part_for is not None:
            return part_for(ca.activity, ca.piece)
        return Part.for_activity(ca.activity, ca.piece)

    @staticmethod
    def submissions_for(ca, enrollment):
        return list(
            Submission.objects.filter(course_assignment=ca, enrollment=enrollment)
            .order_by("id")
            .prefetch_related("attachments")
        )

    @staticmethod
    def group_assignment_for(ca, enrollment):
        return (
            GroupAssignment.objects.select_related("group")
            .filter(course_assignment=ca, enrollment=enrollment)
            .first()
        )

    def to_representation(self, ca):
        # enrollment is None on the teacher list (no per-student context); the
        # per-student fields (instrument/transposition/submissions/group) come back
        # null/empty, while the piece/activity/part fields are fully populated.
        enrollment = self.context["enrollment"]
        activity = ca.activity
        instrument = resolve_instrument(enrollment, ca) if enrollment else None
        part = self._part_for(ca)
        submissions = self._submissions_for(ca, enrollment)
        group = self._group_for(ca, enrollment)
        transposition = instrument.transposition if instrument else None
        return {
            "id": ca.id,
            "activity": activity.id,
            "activity_type_name": activity.activity_type_name,
            "activity_type_category": activity.category,
            "activity_body": activity.body,
            "part_type": activity.part_type.name if activity.part_type else None,
            "piece_name": ca.piece.name,
            "piece_id": ca.piece.id,
            "piece_slug": ca.piece.slug,
            "instrument": instrument.name if instrument else None,
            "transposition": transposition.name if transposition else None,
            "group": (
                GroupSerializer(group, context=self.context).data if group else None
            ),
            "part": PartSerializer(part, context=self.context).data,
            "submissions": SubmissionSerializer(
                submissions, many=True, context=self.context
            ).data,
        }


class CourseAssignmentRetrieveSerializer(serializers.Serializer):
    """Phase 2 single-assignment (retrieve) read path: produces the SAME shape as
    the legacy AssignmentSerializer, resolved from a CourseAssignment against the
    requesting student's enrollment (context ``enrollment``). The ``id`` is the
    CourseAssignment id; a response-equivalence test pins field-for-field parity
    except ``id``."""

    def to_representation(self, ca):
        enrollment = self.context["enrollment"]
        instrument = resolve_instrument(enrollment, ca)
        part = Part.for_activity(ca.activity, ca.piece)
        submissions = CourseAssignmentReadSerializer.submissions_for(ca, enrollment)
        group_assignment = CourseAssignmentReadSerializer.group_assignment_for(
            ca, enrollment
        )
        return {
            "activity": ActivitySerializer(ca.activity, context=self.context).data,
            "deadline": (
                serializers.DateField().to_representation(ca.deadline)
                if ca.deadline
                else None
            ),
            "instrument": (
                InstrumentSerializer(instrument, context=self.context).data
                if instrument
                else None
            ),
            "part": PartSerializer(part, context=self.context).data,
            "id": ca.id,
            "enrollment": EnrollmentSerializer(enrollment, context=self.context).data,
            "submissions": SubmissionSerializer(
                submissions, many=True, context=self.context
            ).data,
            "group": group_assignment.group_id if group_assignment else None,
        }
