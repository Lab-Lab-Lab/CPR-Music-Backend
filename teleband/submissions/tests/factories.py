from factory import SubFactory
from factory.django import DjangoModelFactory

from teleband.submissions.models import Submission


class SubmissionFactory(DjangoModelFactory):
    # Phase 2: submissions are keyed by (course_assignment, enrollment). Imported
    # lazily as SubFactory strings to avoid a circular import with the assignments
    # factories (which build course assignments).
    course_assignment = SubFactory(
        "teleband.assignments.tests.factories.CourseAssignmentFactory"
    )
    enrollment = SubFactory("teleband.courses.tests.factories.EnrollmentFactory")

    class Meta:
        model = Submission
