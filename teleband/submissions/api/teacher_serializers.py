from rest_framework import serializers

from teleband.assignments.api.serializers import ActivitySerializer
from teleband.courses.api.serializers import EnrollmentSerializer
from teleband.instruments.api.serializers import InstrumentSerializer
from teleband.musics.api.serializers import PartSerializer
from teleband.submissions.api.serializers import (
    AttachmentSerializer,
    GradeSerializer,
    SubmissionSerializer,
)
from teleband.submissions.models import Submission


class SubmissionAssignmentSerializer(serializers.Serializer):
    """Phase 2: renders the legacy AssignmentSerializer shape for a Submission from
    its own fields (course_assignment / enrollment / instrument / part), replacing
    the dropped Submission.assignment FK. The teacher grading view only reads
    ``enrollment.user.name`` off this object, but the full shape is preserved.

    The nested ``submissions`` list and ``group`` are resolved from per-(course
    assignment, enrollment) maps the view precomputes (context ``submissions_by_pair``
    / ``group_by_pair``), so serialization stays constant in the number of students.
    """

    def to_representation(self, submission):
        ca = submission.course_assignment
        pair = (submission.course_assignment_id, submission.enrollment_id)
        submissions = self.context.get("submissions_by_pair", {}).get(pair, [])
        group_id = self.context.get("group_by_pair", {}).get(pair)
        return {
            "activity": ActivitySerializer(ca.activity, context=self.context).data,
            "deadline": (
                serializers.DateField().to_representation(ca.deadline)
                if ca.deadline
                else None
            ),
            "instrument": (
                InstrumentSerializer(submission.instrument, context=self.context).data
                if submission.instrument
                else None
            ),
            "part": (
                PartSerializer(submission.part, context=self.context).data
                if submission.part
                else None
            ),
            "id": ca.id,
            "enrollment": EnrollmentSerializer(
                submission.enrollment, context=self.context
            ).data,
            "submissions": SubmissionSerializer(
                submissions, many=True, context=self.context
            ).data,
            "group": group_id,
        }


class TeacherSubmissionSerializer(serializers.ModelSerializer):
    attachments = AttachmentSerializer(read_only=True, many=True)
    assignment = SubmissionAssignmentSerializer(source="*")
    grade = GradeSerializer()
    self_grade = GradeSerializer()

    class Meta:
        model = Submission
        fields = [
            "id",
            "assignment",
            "submitted",
            "content",
            "attachments",
            "grade",
            "self_grade",
        ]
