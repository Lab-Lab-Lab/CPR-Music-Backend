from rest_framework import serializers

from teleband.assignments.models import (
    Assignment,
    Activity,
    ActivityType,
    AssignmentGroup,
    PiecePlan,
)
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
        # Memoize per group.id in the shared serializer context: a group is
        # referenced once per member assignment, so without this the membership
        # query (and its per-member walks) ran O(M) times per group -> O(M^2)
        # across the list. Now it runs once per distinct group. select_related/
        # prefetch keep the per-member enrollment/user/activity/submissions
        # walks off the per-row path; bool(submissions.all()) uses the prefetch
        # cache instead of a COUNT query.
        cache = self.context.setdefault("_group_members", {})
        if obj.id not in cache:
            assignments = (
                Assignment.objects.filter(group=obj)
                .select_related("enrollment__user", "activity")
                .prefetch_related("submissions")
            )
            cache[obj.id] = [
                {
                    "enrollment_id": a.enrollment.id,
                    "enrollment_username": a.enrollment.user.username,
                    "activity_type_name": a.activity.activity_type_name,
                    "assignment_submitted": bool(a.submissions.all()),
                }
                for a in assignments
            ]
        return cache[obj.id]

    class Meta:
        model = AssignmentGroup
        fields = ["type", "members"]


class AssignmentSerializer(serializers.ModelSerializer):
    activity = ActivitySerializer()
    instrument = InstrumentSerializer()
    part = PartSerializer()
    enrollment = EnrollmentSerializer()
    submissions = SubmissionSerializer(many=True)

    class Meta:
        model = Assignment
        # fields = ["activity", "deadline", "instrument", "id", "url"]
        fields = [
            "activity",
            "deadline",
            "instrument",
            "part",
            "id",
            "enrollment",
            "submissions",
            "group",
        ]

        extra_kwargs = {
            "url": {"view_name": "api:assignment-detail", "lookup_field": "id"},
        }

    # def get_fields(self):
    #     fields = super().get_fields()
    #     if not self.instance.group:
    #         del fields['group']
    #     return fields


class AssignmentViewSetSerializer(serializers.ModelSerializer):
    activity = serializers.PrimaryKeyRelatedField(queryset=Activity.objects.all())
    activity_type_name = serializers.CharField(
        source="activity.activity_type_name", read_only=True
    )
    activity_type_category = serializers.CharField(
        source="activity.category", read_only=True
    )
    activity_body = serializers.CharField(source="activity.body", read_only=True)
    part_type = serializers.CharField(source="activity.part_type.name", read_only=True)
    piece_name = serializers.SlugField(source="piece.name", read_only=True)
    piece_id = serializers.IntegerField(source="piece.id", read_only=True)
    piece_slug = serializers.SlugField(source="piece.slug", read_only=True)
    instrument = serializers.CharField(source="instrument.name", read_only=True)
    transposition = serializers.CharField(
        source="instrument.transposition.name", read_only=True
    )
    group = GroupSerializer()
    # instrument = InstrumentSerializer()
    part = PartSerializer()
    # enrollment = EnrollmentSerializer()
    submissions = SubmissionSerializer(many=True)

    class Meta:
        model = Assignment
        # fields = ["activity", "deadline", "instrument", "id", "url"]
        # fields = ["activity", "deadline", "instrument", "part", "id", "enrollment", "submissions"]
        fields = [
            "id",
            "activity",
            "activity_type_name",
            "activity_type_category",
            "activity_body",
            "part_type",
            "piece_name",
            "piece_id",
            "piece_slug",
            "instrument",
            "transposition",
            "group",
            "part",
            "submissions",
        ]

        extra_kwargs = {
            "url": {"view_name": "api:assignment-detail", "lookup_field": "id"},
        }


class AssignmentInstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assignment
        fields = ["id", "instrument"]


class NotationAssignmentSerializer(serializers.ModelSerializer):
    activity = ActivitySerializer()
    instrument = InstrumentSerializer()
    part = PartSerializer()

    class Meta:
        model = Assignment
        # fields = ["activity", "deadline", "instrument", "id", "url"]
        fields = ["activity", "deadline", "instrument", "part", "id"]

        extra_kwargs = {
            "url": {"view_name": "api:assignment-detail", "lookup_field": "id"},
        }


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
