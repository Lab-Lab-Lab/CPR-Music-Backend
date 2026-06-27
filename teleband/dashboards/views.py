from typing import Any
from django.db.models.query import QuerySet
from django.shortcuts import render

from django.views import generic

from teleband.assignments.models import Assignment
from teleband.courses.models import Course
from django.contrib.auth.mixins import UserPassesTestMixin

import csv
from django.http import HttpResponse


class AssignmentListView(UserPassesTestMixin, generic.ListView):
    model = Assignment
    paginate_by = 100

    def get_queryset(self) -> QuerySet[Any]:
        # Forward FKs belong in select_related (one JOIN); only the reverse
        # submissions relation needs prefetch_related.
        results = (
            Assignment.objects.select_related(
                "piece",
                "piece_plan",
                "piece_plan__piece",
                "enrollment",
                "enrollment__user",
                "enrollment__course",
                "enrollment__instrument",
                "enrollment__course__owner",
                "instrument",
                "activity",
                "activity__activity_type",
                "activity__part_type",
            )
            .prefetch_related(
                "submissions__attachments",
                "submissions__grade",
                "submissions__self_grade",
            )
            .all()
        )
        return results

    # queryset = Course.objects.prefetch_related(
    #     "enrollment_set__assignment_set__submissions__attachments"
    # ).all()

    def test_func(self):
        return self.request.user.is_superuser


class CourseListView(UserPassesTestMixin, generic.ListView):
    model = Course

    def test_func(self):
        return self.request.user.is_superuser


def csv_view(request):
    """Function which generates a CSV file for download"""
    # select related returns a queryset that will follow foreign-key relationships. This
    # is a performance booster which results in a single more complex query but won't require
    # database queries
    assignments = (
        Assignment.objects.select_related(
            "piece",
            "piece_plan",
            "piece_plan__piece",
            "enrollment",
            "enrollment__user",
            "enrollment__course",
            "enrollment__instrument",
            "enrollment__course__owner",
            "instrument",
            "activity",
            # Activity.__str__ / PiecePlan.__str__ walk these; the CSV writes the
            # str() of activity and piece_plan, so cover them too.
            "activity__activity_type",
            "activity__part_type",
        )
        .prefetch_related(
            # Reverse relations iterated in the row loop below -- without these
            # each assignment re-queried its submissions/attachments/grades.
            "submissions__attachments",
            "submissions__grade",
            "submissions__self_grade",
        )
        .all()
    )

    # Create the HttpResponse object with the appropriate CSV header
    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="assignment.csv"'},
    )

    writer = csv.writer(response)
    writer.writerow(
        [
            "ID",
            "Course ID",
            "Course Name",
            "Piece ID",
            "Piece Name",
            "Piece Plan ID",
            "Piece Plan Name",
            "Student ID",
            "Student Instrument ID",
            "Student Instrument Name",
            "Assignment Activity ID",
            "Assignment Activity",
            "Assignment Instrument ID",
            "Assignment Instrument Name",
            "Submissions ID",
            "Submissions Content",
            "Submissions submitted",
            "Submissions grade",
            "Submissions Self Grade",
            "Submission Attatchnment ID",
            "Submission Attachment File",
            "Submission Attachment Submitted",
        ]
    )
    for assn in assignments:
        if len(assn.submissions.all()) == 0:

            writer.writerow(
                [
                    assn.id,
                    assn.enrollment.course.id,
                    assn.enrollment.course.name,
                    assn.piece.id,
                    assn.piece.name,
                    assn.piece_plan.id if assn.piece_plan else "N/A",
                    assn.piece_plan or "N/A",
                    assn.enrollment.user.id,
                    assn.enrollment.instrument.id,
                    assn.enrollment.instrument.name,
                    assn.activity.id,
                    assn.activity,
                    assn.instrument.id,
                    assn.instrument.name,
                    "N/A",
                    "N/A",
                    "N/A",
                    "N/A",
                    "N/A",
                    "N/A",
                    "N/A",
                    "N/A",
                ]
            )
        else:
            for sub in assn.submissions.all():
                for att in sub.attachments.all():
                    csv_val = [
                        assn.id,
                        assn.enrollment.course.id,
                        assn.enrollment.course.name,
                        assn.piece.id,
                        assn.piece.name,
                        assn.piece_plan.id if assn.piece_plan else "N/A",
                        assn.piece_plan or "N/A",
                        assn.enrollment.user.id,
                        assn.enrollment.instrument.id,
                        assn.enrollment.instrument.name,
                        assn.activity.id,
                        assn.activity,
                        assn.instrument.id,
                        assn.instrument.name,
                        sub.id,
                    ]
                    if assn.activity.category == "Create":
                        csv_val.append("Create, see below")
                    else:
                        csv_val.append(sub.content)
                    csv_val.extend(
                        [
                            sub.submitted,
                            sub.grade,
                            sub.self_grade,
                            att.id,
                            att.file,
                            att.submitted,
                        ]
                    )

                    writer.writerow(csv_val)
    return response
