from collections import defaultdict

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin, CreateModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet
from teleband.submissions.api.teacher_serializers import TeacherSubmissionSerializer

from .serializers import (
    GradeSerializer,
    SubmissionSerializer,
    AttachmentSerializer,
    ActivityProgressSerializer,
)

from teleband.courses.models import Course
from teleband.submissions.models import (
    Grade,
    Submission,
    SubmissionAttachment,
    ActivityProgress,
)
from teleband.assignments.models import CourseAssignment, GroupAssignment
from teleband.assignments.api.serializers import resolve_instrument
from teleband.musics.models import Part
from datetime import datetime


def resolve_student_target(request, course_slug, course_assignment_id):
    """Resolve the (course_assignment, enrollment) a student's nested route refers
    to. Phase 2: the URL id is a CourseAssignment id (the list contract), scoped to
    the requesting user's enrollment in the course. Returns (course_assignment,
    enrollment); raises Http404 if the student has no enrollment in the course or
    no such CourseAssignment."""
    enrollment = get_object_or_404(
        request.user.enrollment_set.select_related("course"),
        course__slug=course_slug,
    )
    course_assignment = get_object_or_404(
        CourseAssignment.objects.select_related(
            "activity", "activity__part_type", "piece"
        ),
        pk=course_assignment_id,
        course=enrollment.course,
    )
    return course_assignment, enrollment


class SubmissionViewSet(
    ListModelMixin, RetrieveModelMixin, CreateModelMixin, GenericViewSet
):
    serializer_class = SubmissionSerializer
    queryset = Submission.objects.all()

    def _target(self):
        # Resolve (course_assignment, enrollment) once per request from the URL
        # CourseAssignment id, scoped to the requesting student.
        if not hasattr(self, "_cached_target"):
            self._cached_target = resolve_student_target(
                self.request,
                self.kwargs["course_slug_slug"],
                self.kwargs["assignment_id"],
            )
        return self._cached_target

    def get_queryset(self):
        # Phase 2: a student's submissions are keyed by (course_assignment,
        # enrollment), not the legacy per-student assignment id.
        course_assignment, enrollment = self._target()
        return self.queryset.filter(
            course_assignment=course_assignment, enrollment=enrollment
        )

    def perform_create(self, serializer):
        # Phase 2: record the course-level assignment, the student (enrollment),
        # and the instrument/part the work was made with, resolved from the
        # enrollment at write time.
        course_assignment, enrollment = self._target()
        serializer.save(
            course_assignment=course_assignment,
            enrollment=enrollment,
            instrument=resolve_instrument(enrollment, course_assignment),
            part=Part.for_activity(course_assignment.activity, course_assignment.piece),
        )

    # @action(detail=False)
    # def get_


class AttachmentViewSet(
    ListModelMixin, RetrieveModelMixin, CreateModelMixin, GenericViewSet
):
    serializer_class = AttachmentSerializer
    queryset = SubmissionAttachment.objects.all()

    def get_queryset(self):
        return self.queryset.filter(submission_id=self.kwargs["submission_pk"])

    def perform_create(self, serializer):
        serializer.save(
            submission=Submission.objects.get(pk=self.kwargs["submission_pk"])
        )


class TeacherSubmissionViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    serializer_class = TeacherSubmissionSerializer
    queryset = Submission.objects.all()

    # def get_queryset(self,):
    #     pass

    @action(detail=False)
    def recent(self, request, **kwargs):
        if "piece_slug" not in request.GET or "activity_name" not in request.GET:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "error": "Missing piece_slug or activity_name (figure it out!) in get data"
                },
            )

        course_id = self.kwargs["course_slug_slug"]
        piece_slug = request.GET["piece_slug"]
        activity_name = request.GET["activity_name"]

        # Phase 2: resolve the latest submission per enrollment from the
        # submission's own fields (course_assignment / enrollment / part) instead
        # of the dropped assignment FK.
        latest_submissions = (
            Submission.objects.filter(
                enrollment=OuterRef("enrollment"),
                enrollment__course__slug=course_id,
                course_assignment__activity__activity_type__name=activity_name,
                course_assignment__piece__slug=piece_slug,
            )
            .order_by("-submitted")
            .values("pk")[:1]
        )

        # select_related/prefetch cover every relation SubmissionAssignmentSerializer
        # walks (activity tree, instrument, part tree, enrollment course/owner/role),
        # so serialization issues a constant number of queries regardless of how many
        # students submitted.
        submissions = list(
            Submission.objects.filter(pk__in=Subquery(latest_submissions))
            .select_related(
                "grade",
                "self_grade",
                "course_assignment__activity__activity_type__category",
                "course_assignment__activity__part_type",
                "course_assignment__piece",
                "instrument__transposition",
                "part__part_type",
                "part__piece__composer",
                "enrollment__user",
                "enrollment__instrument__transposition",
                "enrollment__role",
                "enrollment__course__owner",
            )
            .prefetch_related(
                "attachments",
                "part__transpositions__transposition",
                "part__instrument_samples",
                "enrollment__user__groups",
                "enrollment__course__owner__groups",
            )
            .order_by("enrollment", "-submitted")
        )

        serializer = self.serializer_class(
            submissions,
            many=True,
            context={"request": request, **self._assignment_maps(submissions)},
        )
        return Response(status=status.HTTP_200_OK, data=serializer.data)

    @staticmethod
    def _assignment_maps(submissions):
        # Per-(course_assignment, enrollment) maps for the nested assignment object's
        # `submissions` and `group` fields -- two queries total, so the recent view
        # stays constant in roster size.
        ca_ids = [s.course_assignment_id for s in submissions]
        enr_ids = [s.enrollment_id for s in submissions]

        submissions_by_pair = defaultdict(list)
        for s in (
            Submission.objects.filter(
                course_assignment_id__in=ca_ids, enrollment_id__in=enr_ids
            )
            .order_by("id")
            .prefetch_related("attachments")
        ):
            submissions_by_pair[(s.course_assignment_id, s.enrollment_id)].append(s)

        group_by_pair = {
            (ga.course_assignment_id, ga.enrollment_id): ga.group_id
            for ga in GroupAssignment.objects.filter(
                course_assignment_id__in=ca_ids, enrollment_id__in=enr_ids
            )
        }
        return {
            "submissions_by_pair": submissions_by_pair,
            "group_by_pair": group_by_pair,
        }


class GradeViewSet(ModelViewSet):
    queryset = Grade.objects.all()
    serializer_class = GradeSerializer

    def get_queryset(self, *args, **kwargs):
        # GradeSerializer renders the reverse student_submission/own_submission
        # one-to-ones; prefetch them so they aren't fetched per grade.
        return Grade.objects.filter(
            student_submission__assignment__enrollment__course__slug=self.kwargs[
                "course_slug_slug"
            ]
        ).prefetch_related("student_submission", "own_submission")


class ActivityProgressViewSet(GenericViewSet):
    serializer_class = ActivityProgressSerializer
    queryset = ActivityProgress.objects.all()

    def _target(self):
        # Resolve (course_assignment, enrollment) once per request from the URL
        # CourseAssignment id, scoped to the requesting student.
        if not hasattr(self, "_cached_target"):
            self._cached_target = resolve_student_target(
                self.request,
                self.kwargs["course_slug_slug"],
                self.kwargs["assignment_id"],
            )
        return self._cached_target

    def _get_or_create_progress(self, lock=False):
        # Phase 2: progress is keyed by (course_assignment, enrollment).
        course_assignment, enrollment = self._target()
        manager = ActivityProgress.objects
        if lock:
            manager = manager.select_for_update()
        return manager.get_or_create(
            course_assignment=course_assignment,
            enrollment=enrollment,
        )

    def get_object(self):
        """Get or create progress for the current assignment."""
        progress, created = self._get_or_create_progress()
        return progress

    def list(self, request, *args, **kwargs):
        """Get progress for current assignment (uses list URL since no pk needed)."""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def log_event(self, request, **kwargs):
        """Log an operation event to the activity progress."""
        try:
            # Use transaction with row-level locking to prevent race conditions
            with transaction.atomic():
                progress, created = self._get_or_create_progress(lock=True)

                # Extract event data from request
                operation = request.data.get("operation")
                step = request.data.get("step", progress.current_step)
                data = request.data.get("data", {})
                email = request.data.get("email")

                # DEBUG: Log what we received
                print(f"🔍 Backend log_event received:")
                print(f"   operation: {operation}")
                print(f"   step: {step}")
                print(f"   BEFORE step_completions: {progress.step_completions}")

                # Store email if provided and not already set
                if email and not progress.participant_email:
                    progress.participant_email = email

                # Add timestamped event to logs
                event = {
                    "timestamp": datetime.now().isoformat(),
                    "step": step,
                    "operation": operation,
                    "data": data,
                }
                progress.activity_logs.append(event)

                # Track operation completion
                step_key = str(step)
                if step_key not in progress.step_completions:
                    progress.step_completions[step_key] = []
                if operation not in progress.step_completions[step_key]:
                    progress.step_completions[step_key].append(operation)
                    print(f"   ✅ Added {operation} to step {step_key}")
                else:
                    print(f"   ⏭️ Skipped {operation} (already exists)")

                print(f"   AFTER step_completions: {progress.step_completions}")

                progress.save()

            # Serialize AFTER transaction completes
            serializer = self.serializer_class(progress)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def submit_step(self, request, **kwargs):
        """Submit current step and advance to next."""
        submitted_step = request.data.get("step")

        try:
            with transaction.atomic():
                progress, created = self._get_or_create_progress(lock=True)

                # If a step was submitted, use it as the step being completed
                # This ensures the user's actual position is used, not stale DB state
                if submitted_step is not None:
                    submitted_step = int(submitted_step)
                    # Allow setting the step if it's valid (1-4)
                    if 1 <= submitted_step <= 4:
                        print(
                            f"📝 Submitted step: {submitted_step}, stored step was: {progress.current_step}"
                        )
                        # Set current_step to the submitted step (trust the frontend)
                        progress.current_step = submitted_step

                # Save any question responses
                responses = request.data.get("question_responses", {})
                progress.question_responses.update(responses)

                # Advance to next step (max 4)
                if progress.current_step < 4:
                    old_step = progress.current_step
                    progress.current_step += 1
                    print(
                        f"✅ Advancing from step {old_step} to step {progress.current_step}"
                    )

                progress.save()

            # Refresh from database to ensure fresh data
            progress.refresh_from_db()
            serializer = self.serializer_class(progress)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except ActivityProgress.DoesNotExist:
            return Response(
                {"error": "Activity progress not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except (ValueError, TypeError) as e:
            return Response(
                {"error": f"Invalid step value: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["post"])
    def save_response(self, request, **kwargs):
        """Save a question response without advancing step."""
        try:
            progress, created = self._get_or_create_progress()

            question_id = request.data.get("question_id")
            response_text = request.data.get("response")

            if question_id and response_text is not None:
                progress.question_responses[question_id] = response_text
                progress.save()

            serializer = self.serializer_class(progress)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def save_audio_state(self, request, **kwargs):
        """Save current audio state for persistence across activities."""
        assignment_id = kwargs.get("assignment_id")

        try:
            with transaction.atomic():
                progress, created = self._get_or_create_progress(lock=True)

                # Extract audio state from request
                audio_url = request.data.get("audio_url")
                edit_history = request.data.get("edit_history")
                metadata = request.data.get("metadata")

                # Update audio state fields
                if audio_url is not None:
                    progress.current_audio_url = audio_url
                if edit_history is not None:
                    progress.audio_edit_history = edit_history
                if metadata is not None:
                    progress.audio_metadata = metadata

                progress.save()

            print(f"💾 Saved audio state for assignment {assignment_id}")
            print(
                f"   audio_url: {progress.current_audio_url[:50] if progress.current_audio_url else None}..."
            )
            print(f"   edit_history length: {len(progress.audio_edit_history)}")

            serializer = self.serializer_class(progress)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
