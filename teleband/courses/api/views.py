import collections
import csv
from io import StringIO
import json
import logging
import random

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import permissions
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import (
    ListModelMixin,
    RetrieveModelMixin,
    CreateModelMixin,
    DestroyModelMixin,
    UpdateModelMixin,
)
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from .serializers import (
    EnrollmentSerializer,
    CourseSerializer,
    CourseRelatedSerializer,
    EnrollmentCreateSerializer,
    EnrollmentInstrumentSerializer,
    RosterSerializer,
)
from teleband.assignments.api.serializers import AssignmentSerializer
from teleband.users.api.serializers import UserSerializer

from teleband.courses.models import Enrollment, Course
from teleband.assignments.models import (
    Assignment,
    Activity,
    CourseAssignment,
    PiecePlan,
    Curriculum,
    AssignmentGroup,
)
from teleband.musics.models import PartType, Piece, Part
from teleband.users.models import Role
from teleband.utils.permissions import IsTeacher
from teleband.instruments.models import Instrument

from teleband.courses.helper import (
    assign_all_piece_activities,
    AssignmentGroupSizeException,
    assign_piece_plan,
    assign_curriculum,
)

logger = logging.getLogger(__name__)


User = get_user_model()


class IsTeacherEnrollment(permissions.IsAuthenticated):
    def has_permission(self, request, view):
        if view.action not in ["create", "update", "partial_update", "destroy"]:
            return super().has_permission(request, view)

        if view.action == "create":
            if "course" not in request.POST:
                return super().has_permission(request, view)
            try:
                return (
                    Enrollment.objects.get(
                        user=request.user, course_id=request.POST["course"]
                    ).role.name
                    == "Teacher"
                )
            except Enrollment.DoesNotExist:
                return False

        try:
            e = Enrollment.objects.get(
                user=request.user, course=view.get_object().course
            )
            return e.role.name == "Teacher"
        except Enrollment.DoesNotExist:
            logger.info(
                "No Enrollment for {} in {}".format(request.user, view.get_object())
            )
        return False


class EnrollmentViewSet(
    ListModelMixin,
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyModelMixin,
    GenericViewSet,
):
    serializer_class = EnrollmentSerializer
    queryset = Enrollment.objects.all()
    permission_classes = [IsTeacherEnrollment]

    def get_queryset(self, *args, **kwargs):
        if self.action in ["update", "partial_update", "destroy"]:
            courses = [
                e.course
                for e in Enrollment.objects.filter(
                    user=self.request.user, role__name="Teacher"
                )
            ]
            return self.queryset.filter(course__in=courses)

        # EnrollmentSerializer nests course->owner, instrument->transposition,
        # role, and user (UserSerializer -> groups).
        return (
            self.queryset.filter(user=self.request.user)
            .select_related(
                "course__owner", "instrument__transposition", "role", "user"
            )
            .prefetch_related("course__owner__groups", "user__groups")
        )

    def get_serializer_class(self):
        if self.action == "update" or self.action == "partial_update":
            return EnrollmentInstrumentSerializer
        elif self.action == "create":
            return EnrollmentCreateSerializer
        return self.serializer_class


class CoursePermission(permissions.IsAuthenticated):
    def has_permission(self, request, view):
        if view.action == "create":
            return request.user.groups.filter(name="Teacher").exists()
        return True

    def has_object_permission(self, request, view, obj):
        if view.action in ["retrieve", "change_piece_instrument"]:
            return super().has_permission(request, view)
        try:
            e = Enrollment.objects.get(user=request.user, course=obj)
            return e.role.name == "Teacher"
        except Enrollment.DoesNotExist:
            logger.info("No Enrollment for {} in {}".format(request.user, obj))
        return False


class CourseViewSet(
    RetrieveModelMixin, CreateModelMixin, UpdateModelMixin, GenericViewSet
):
    serializer_class = CourseSerializer
    queryset = Course.objects.all()
    lookup_field = "slug"
    permission_classes = [CoursePermission]

    def get_serializer_class(self):
        if (
            self.action == "create"
            or self.action == "update"
            or self.action == "partial_update"
        ):
            return CourseRelatedSerializer
        # elif self.action == "update" or self.action == "partial_update":
        #     return EnrollmentInstrumentSerializer
        return self.serializer_class

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["get", "post"])
    def roster(self, request, **kwargs):
        if request.method == "POST":
            # bulk student/enrollment creation
            users_file = request.FILES["file"]
            contents = "".join(
                [line.decode("utf-8") for line in users_file.readlines()]
            )
            reader = csv.reader(StringIO(contents))

            response = collections.defaultdict(list)

            for row in reader:
                # strip trailing empty fields (e.g. from trailing commas)
                while row and row[-1] == "":
                    row.pop()
                if len(row) != 4:
                    continue
                name, username, password, grade = row
                if (name, username, password, grade) == (
                    "fullname",
                    "username",
                    "password",
                    "grade",
                ):
                    continue
                try:
                    trimmed = username.strip()
                    user = User.objects.get(username=trimmed)
                    if user.check_password(password):
                        response["existing"].append(user)
                    else:
                        new_username = trimmed
                        while True:
                            new_username = f"{trimmed}{random.randint(1000, 9999)}"
                            if not User.objects.filter(username=new_username).exists():
                                break
                        response["created"].append(
                            User.objects.create_user(
                                name=name,
                                username=new_username,
                                password=password,
                                grade=grade,
                            )
                        )
                except User.DoesNotExist:
                    response["created"].append(
                        User.objects.create_user(
                            name=name, username=trimmed, password=password, grade=grade
                        )
                    )

            course = self.get_object()
            role = Role.objects.get(name="Student")
            enrollments = collections.defaultdict(list)

            # Resolve existing enrollments in one query, then bulk_create the new
            # ones instead of a get()+create() per user.
            all_users = response["created"] + response["existing"]
            existing_by_user = {
                e.user_id: e
                for e in Enrollment.objects.filter(course=course, user__in=all_users)
            }
            to_create = []
            for user in all_users:
                existing = existing_by_user.get(user.id)
                if existing is not None:
                    enrollments["existing"].append(existing)
                else:
                    to_create.append(
                        Enrollment(
                            user=user,
                            course=course,
                            instrument=user.instrument,
                            role=role,
                        )
                    )
            enrollments["created"] = Enrollment.objects.bulk_create(to_create)

            response["created"] = UserSerializer(
                response["created"], many=True, context={"request": request}
            ).data
            response["existing"] = UserSerializer(
                response["existing"], many=True, context={"request": request}
            ).data
            enrollments["created"] = EnrollmentSerializer(
                enrollments["created"], many=True, context={"request": request}
            ).data
            enrollments["existing"] = EnrollmentSerializer(
                enrollments["existing"], many=True, context={"request": request}
            ).data
            return Response(
                status=status.HTTP_200_OK,
                data={"users": response, "enrollments": enrollments},
            )

        # must be a GET, respond with all enrollments for this class.
        # RosterSerializer walks user (-> groups), instrument -> transposition,
        # and role, so pull them in one shot.
        course_enrollments = (
            Enrollment.objects.filter(course=self.get_object())
            .select_related("user", "instrument__transposition", "role")
            .prefetch_related("user__groups")
        )
        serializer = RosterSerializer(
            course_enrollments, many=True, context={"request": request}
        )
        return Response(status=status.HTTP_200_OK, data=serializer.data)

    @action(detail=True, methods=["post"])
    def assign_piece_plan(self, request, **kwargs):
        with transaction.atomic():
            parsed = request.data
            if "piece_plan_id" not in parsed:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"error": "Missing piece_plan_id in POST data"},
                )

            try:
                piece_plan = PiecePlan.objects.get(pk=parsed["piece_plan_id"])
            except PiecePlan.DoesNotExist:
                logger.info(
                    "Attempt to assign non-existent piece plan {}".format(
                        parsed["piece_plan_id"]
                    )
                )
                return Response(status=status.HTTP_404_NOT_FOUND)

            course = self.get_object()

            missing_instruments = Enrollment.objects.filter(
                Q(instrument=None) & Q(user__instrument=None),
                course=course,
                role__name="Student",
            )
            if missing_instruments.exists():
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": "Some users and their enrollments have no instrument",
                        "enrollments": EnrollmentSerializer(
                            missing_instruments, many=True, context={"request": request}
                        ).data,
                    },
                )

            try:
                assignments = assign_piece_plan(course, piece_plan)
            except AssignmentGroupSizeException:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={
                        "message": "Number of students must be greater than or equal to the number of activities in the piece plan",
                    },
                )

            # Phase 2: assign_* returns CourseAssignment/GroupAssignment rows; the
            # frontend ignores this body (it refetches the list), so return a count.
            return Response(
                status=status.HTTP_200_OK, data={"assigned": len(assignments)}
            )

    @action(detail=True, methods=["post"])
    def assign(self, request, **kwargs):
        parsed = request.data
        if "piece_id" not in parsed:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"error": "Missing piece_id in POST data"},
            )

        try:
            piece = Piece.objects.get(pk=parsed["piece_id"])
        except Piece.DoesNotExist:
            logger.info(
                "Attempt to assign non-existent piece {}".format(parsed["piece_id"])
            )
            return Response(status=status.HTTP_404_NOT_FOUND)

        course = self.get_object()

        missing_instruments = Enrollment.objects.filter(
            Q(instrument=None) & Q(user__instrument=None),
            course=course,
            role__name="Student",
        )
        if missing_instruments.exists():
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "message": "Some users and their enrollments have no instrument",
                    "enrollments": EnrollmentSerializer(
                        missing_instruments, many=True, context={"request": request}
                    ).data,
                },
            )

        assignments = assign_all_piece_activities(course, piece)

        # Phase 2: assign_* now returns CourseAssignment/GroupAssignment rows, not
        # per-student Assignments. The frontend ignores this body (it refetches the
        # list), so return a simple count.
        return Response(status=status.HTTP_200_OK, data={"assigned": len(assignments)})

    @action(detail=True, methods=["post"])
    def assign_curriculum(self, request, **kwargs):
        parsed = request.data
        if "curriculum_id" not in parsed:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"error": "Missing curriculum_id in POST data"},
            )

        try:
            curriculum = Curriculum.objects.get(pk=parsed["curriculum_id"])
        except Curriculum.DoesNotExist:
            logger.info(
                "Attempt to assign non-existent curriculum {}".format(
                    parsed["curriculum_id"]
                )
            )
            return Response(status=status.HTTP_404_NOT_FOUND)

        course = self.get_object()

        missing_instruments = Enrollment.objects.filter(
            Q(instrument=None) & Q(user__instrument=None),
            course=course,
            role__name="Student",
        )
        if missing_instruments.exists():
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "message": "Some users and their enrollments have no instrument",
                    "enrollments": EnrollmentSerializer(
                        missing_instruments, many=True, context={"request": request}
                    ).data,
                },
            )

        assignments = assign_curriculum(course, curriculum)

        # Phase 2: assign_* now returns CourseAssignment/GroupAssignment rows, not
        # per-student Assignments. The frontend ignores this body (it refetches the
        # list), so return a simple count.
        return Response(status=status.HTTP_200_OK, data={"assigned": len(assignments)})

    @action(detail=True, methods=["post"])
    def unassign(self, request, **kwargs):
        parsed = request.data
        if "piece_id" not in parsed:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"error": "Missing piece_id in POST data"},
            )

        try:
            piece = Piece.objects.get(pk=parsed["piece_id"])
        except Piece.DoesNotExist:
            logger.info(
                "Attempt to assign non-existent piece {}".format(parsed["piece_id"])
            )
            return Response(status=status.HTTP_404_NOT_FOUND)

        course = self.get_object()

        try:
            with transaction.atomic():
                # Phase 2: unassigning a piece removes its CourseAssignments
                # (GroupAssignments cascade). A piece with submissions is PROTECTed,
                # which surfaces as the IntegrityError handled below -- same guard
                # the per-student Assignment delete had.
                CourseAssignment.objects.filter(
                    piece_id=parsed["piece_id"], course=course
                ).delete()
        except IntegrityError:
            logger.error(
                "Cannot remove all the assignments for {} in {}".format(
                    parsed["piece_id"], course.slug
                )
            )
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "error": "Cannot remove assignments for piece {}".format(
                        parsed["piece_id"]
                    )
                },
            )

        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=["patch"])
    def change_piece_instrument(self, request, **kwargs):
        piece_id = request.data.get("piece_id")
        if piece_id is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"error": "Piece Id missing from PATCH request"},
            )

        instrument_id = request.data.get("instrument_id")
        if instrument_id is None:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"error": "Instrument ID missing from PATCH request"},
            )

        course = self.get_object()
        if not course.can_edit_instruments:
            return Response(
                status=status.HTTP_403_FORBIDDEN,
                data={"error": "No permission to change instrument"},
            )

        instrument = Instrument.objects.get(pk=instrument_id)
        piece = Piece.objects.get(pk=piece_id)

        # Phase 2: the per-piece instrument override lives on CourseAssignment
        # (course-level, applied to every student for that piece). One UPDATE
        # across the piece's CourseAssignments; resolve_instrument prefers it.
        CourseAssignment.objects.filter(piece=piece, course=course).update(
            instrument=instrument
        )

        return Response(status=status.HTTP_200_OK)
