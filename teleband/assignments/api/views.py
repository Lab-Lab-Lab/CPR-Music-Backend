from collections import defaultdict
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from django.db.models import OuterRef, Q, Subquery

from django.shortcuts import get_object_or_404

from .serializers import (
    CourseAssignmentReadSerializer,
    CourseAssignmentRetrieveSerializer,
)
from teleband.assignments.api.serializers import ActivitySerializer, PiecePlanSerializer

from teleband.assignments.models import (
    Activity,
    CourseAssignment,
    GroupAssignment,
    PlannedActivity,
    PiecePlan,
)
from teleband.courses.models import Course
from teleband.musics.models import Part
from teleband.submissions.models import Submission
from teleband.utils.permissions import IsTeacher


class TeacherUpdate(IsTeacher):
    def has_permission(self, request, view):
        if view.action not in ["update", "partial_update"]:
            return True

        return super().has_permission(request, view)


class ActivityViewSet(RetrieveModelMixin, ListModelMixin, GenericViewSet):
    serializer_class = ActivitySerializer
    queryset = Activity.objects.all()
    lookup_field = "id"
    permission_classes = [IsTeacher]

    def get_queryset(self):
        # Phase 2: the activities assigned in a course come from CourseAssignment
        # (one row per (course, activity, piece)), not per-student Assignment rows.
        distinct_activity_assignments = (
            CourseAssignment.objects.filter(
                course__slug=self.kwargs["course_slug_slug"],
                activity=OuterRef("id"),
            )
            .order_by("id", "pk")
            .values("activity_id")[:1]
        )

        # Use the subquery to filter the main queryset. select_related covers the
        # activity_type/category/part_type walked by ActivitySerializer.
        queryset = self.queryset.filter(
            pk__in=Subquery(distinct_activity_assignments)
        ).select_related("activity_type", "activity_type__category", "part_type")

        return queryset


class AssignmentViewSet(RetrieveModelMixin, ListModelMixin, GenericViewSet):
    # Phase 2: list/retrieve are fully overridden and resolve from CourseAssignment;
    # this queryset/serializer is only for router basename + DRF metadata.
    serializer_class = CourseAssignmentReadSerializer
    queryset = CourseAssignment.objects.all()
    lookup_field = "id"
    permission_classes = [TeacherUpdate]

    def retrieve(self, request, *args, **kwargs):
        # Phase 2: the single-assignment id is a CourseAssignment id; resolve it
        # against the requesting user's enrollment and return the legacy
        # AssignmentSerializer shape.
        enrollment = self.request.user.enrollment_set.select_related(
            "role", "course"
        ).get(course__slug=self.kwargs["course_slug_slug"])
        course_assignment = get_object_or_404(
            CourseAssignment.objects.select_related(
                "activity",
                "activity__part_type",
                "activity__activity_type",
                "activity__activity_type__category",
                "piece",
            ),
            pk=self.kwargs["id"],
            course=enrollment.course,
        )
        serializer = CourseAssignmentRetrieveSerializer(
            course_assignment,
            context={"request": request, "enrollment": enrollment},
        )
        return Response(serializer.data)

    # Fallback ordering by activity type name prefix, used when an assignment has
    # no PlannedActivity.order (shared by the student and teacher list paths).
    _FALLBACK_ORDERING = {
        "Melody": 1,
        "Bassline": 2,
        "Creativity": 3,
        "Reflection": 4,
        "Connect": 5,
        "Aural": 3,
        "Exploratory": 3,
        "Theoretical": 3,
        "MelodyPost": 3.1,
        "BasslinePost": 3.2,
    }

    def _grouped_by_piece(self, serialized_items, plan_order_by_id):
        # Group serialized rows by piece slug, then sort each group by the row's
        # PlannedActivity.order (when present) else the activity-type fallback.
        grouped = defaultdict(list)
        for item in serialized_items:
            grouped[item["piece_slug"]].append(item)

        def sort_key(a):
            plan_order = plan_order_by_id.get(a["id"])
            if plan_order is not None:
                return (0, plan_order)
            return (
                1,
                self._FALLBACK_ORDERING.get(a["activity_type_name"].split()[0], 999),
            )

        for slug in grouped:
            grouped[slug].sort(key=sort_key)
        return grouped

    def _student_list(self, request, enrollment):
        # Phase 2 read path: resolve the student's assignments from CourseAssignment
        # instead of per-student Assignment rows. A student sees every CourseAssignment
        # for their course that is NOT scoped to a group, UNION the grouped ones
        # (telephone_fixed) that name their enrollment. This also fixes late joiners:
        # they get the course's CourseAssignments even with no Assignment rows.
        grouped_ca_ids = GroupAssignment.objects.values("course_assignment_id")
        my_ca_ids = GroupAssignment.objects.filter(enrollment=enrollment).values(
            "course_assignment_id"
        )
        planned_order_subquery = PlannedActivity.objects.filter(
            piece_plan_id=OuterRef("piece_plan_id"),
            activity_id=OuterRef("activity_id"),
        ).values("order")[:1]
        course_assignments = (
            CourseAssignment.objects.filter(course=enrollment.course)
            .filter(~Q(id__in=grouped_ca_ids) | Q(id__in=my_ca_ids))
            .select_related(
                "activity",
                "activity__part_type",
                "activity__activity_type",
                "activity__activity_type__category",
                "piece",
            )
            .annotate(plan_order=Subquery(planned_order_subquery))
        )
        course_assignments = list(course_assignments)
        context = {
            "request": request,
            "enrollment": enrollment,
            **self._read_context(course_assignments, enrollment),
        }
        serialized = CourseAssignmentReadSerializer(
            course_assignments, many=True, context=context
        ).data
        plan_order_by_id = {
            ca.id: ca.plan_order for ca in course_assignments if ca.piece_plan_id
        }
        return Response(self._grouped_by_piece(serialized, plan_order_by_id))

    def _read_context(self, course_assignments, enrollment):
        # Precompute the per-CA maps CourseAssignmentReadSerializer needs so the
        # list resolves part/submissions/group in O(1) per row instead of N+1
        # (landmine: read-time per-(student x activity) resolution).
        ca_ids = [ca.id for ca in course_assignments]
        pieces = {ca.piece for ca in course_assignments}

        # submissions for this student, grouped by CourseAssignment, attachments
        # prefetched (matches the legacy per-assignment submissions list).
        submissions_by_ca = defaultdict(list)
        for sub in (
            Submission.objects.filter(
                course_assignment_id__in=ca_ids, enrollment=enrollment
            )
            .order_by("id")
            .prefetch_related("attachments")
        ):
            submissions_by_ca[sub.course_assignment_id].append(sub)

        # group (telephone_fixed) per CourseAssignment for this student.
        group_by_ca = {
            ga.course_assignment_id: ga.group
            for ga in GroupAssignment.objects.filter(
                course_assignment_id__in=ca_ids, enrollment=enrollment
            ).select_related("group")
        }

        return {
            "submissions_by_ca": submissions_by_ca,
            "group_by_ca": group_by_ca,
            "part_for": self._part_resolver(course_assignments),
        }

    def _part_resolver(self, course_assignments):
        # One Part query for every piece in play (with the tree PartSerializer
        # walks), then resolve (activity, piece) -> Part in memory, mirroring
        # Part.for_activity's part_type match with a Melody fallback. Shared by the
        # student and teacher lists so part resolution never hits the N+1 path.
        pieces = {ca.piece for ca in course_assignments}
        parts = (
            Part.objects.filter(piece__in=pieces)
            .select_related("part_type", "piece", "piece__composer")
            .prefetch_related("transpositions__transposition", "instrument_samples")
        )
        by_type = {}
        melody_by_piece = {}
        for part in parts:
            by_type[(part.piece_id, part.part_type_id)] = part
            if part.part_type.name == "Melody":
                melody_by_piece[part.piece_id] = part

        def part_for(activity, piece):
            if activity.part_type_id is not None:
                hit = by_type.get((piece.id, activity.part_type_id))
                if hit is not None:
                    return hit
            return melody_by_piece.get(piece.id)

        return part_for

    def _teacher_list(self, request):
        # Phase 2: a teacher sees what the COURSE is assigned -- one row per
        # CourseAssignment (every assigned (piece, activity)), not one per student.
        # The frontend's teacher view only derives the distinct (piece, activity)
        # set from this list, so per-student fields come back null/empty. This
        # collapses the response from A*S rows to A and makes it constant in roster.
        planned_order_subquery = PlannedActivity.objects.filter(
            piece_plan_id=OuterRef("piece_plan_id"),
            activity_id=OuterRef("activity_id"),
        ).values("order")[:1]
        course_assignments = list(
            CourseAssignment.objects.filter(
                course__slug=self.kwargs["course_slug_slug"]
            )
            .select_related(
                "activity",
                "activity__part_type",
                "activity__activity_type",
                "activity__activity_type__category",
                "piece",
            )
            .annotate(plan_order=Subquery(planned_order_subquery))
        )
        # part_for keeps the per-row Part lookup off the N+1 path; submissions/group
        # are empty for the teacher (enrollment=None), so only the part map is built.
        context = {
            "request": request,
            "enrollment": None,
            "part_for": self._part_resolver(course_assignments),
        }
        serialized = CourseAssignmentReadSerializer(
            course_assignments, many=True, context=context
        ).data
        plan_order_by_id = {
            ca.id: ca.plan_order for ca in course_assignments if ca.piece_plan_id
        }
        return Response(self._grouped_by_piece(serialized, plan_order_by_id))

    def list(self, request, *args, **kwargs):
        enrollment = self.request.user.enrollment_set.select_related("role").get(
            course__slug=self.kwargs["course_slug_slug"]
        )
        if enrollment.role.name == "Student":
            return self._student_list(request, enrollment)
        return self._teacher_list(request)


class PiecePlanViewSet(RetrieveModelMixin, ListModelMixin, GenericViewSet):
    serializer_class = PiecePlanSerializer
    queryset = PiecePlan.objects.prefetch_related("piece")
    lookup_field = "id"
    permission_classes = [IsTeacher]

    def get_queryset(self):
        course = Course.objects.get(slug=self.kwargs["course_slug_slug"])
        # PiecePlanSerializer walks piece->composer and activities->
        # activity_type/category/part_type.
        return (
            PiecePlan.objects.filter(curriculum__course=course)
            .select_related("piece__composer")
            .prefetch_related(
                "activities__activity_type__category", "activities__part_type"
            )
        )

    # def get_serializer_class(self):
    #     if self.action == "create":
    #         return PieceCreateSerializer
    #     return self.serializer_class
