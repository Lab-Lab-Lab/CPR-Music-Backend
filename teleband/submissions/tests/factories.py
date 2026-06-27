from factory import SubFactory
from factory.django import DjangoModelFactory

from teleband.submissions.models import Submission


class SubmissionFactory(DjangoModelFactory):
    # Imported lazily as a SubFactory string to avoid a circular import with the
    # assignments factories (which build submissions).
    assignment = SubFactory("teleband.assignments.tests.factories.AssignmentFactory")

    class Meta:
        model = Submission
