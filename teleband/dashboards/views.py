import csv
from collections import defaultdict
from types import SimpleNamespace

from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import HttpResponse
from django.views import generic

from teleband.assignments.api.serializers import resolve_instrument
from teleband.assignments.models import CourseAssignment, GroupAssignment
from teleband.courses.models import Course, Enrollment
from teleband.submissions.models import Submission


def build_assignment_rows():
    """Phase 2: the per-student assignment table is gone. Reconstruct one row per
    (student, CourseAssignment) -- every enrolled student is implicitly assigned
    every non-grouped CourseAssignment in their course, plus the grouped
    (telephone_fixed) ones their GroupAssignment names. Each row exposes the same
    attributes the old Assignment rows did (enrollment, piece, piece_plan, activity,
    instrument, submissions), so the CSV and the template are unchanged in shape.

    All data is fetched in a constant number of queries (no per-row N+1).
    """
    course_assignments = list(
        CourseAssignment.objects.select_related(
            "course",
            "activity",
            "activity__activity_type",
            "activity__part_type",
            "piece",
            "piece_plan",
            "piece_plan__piece",
            "instrument",
        )
    )
    enrollments = list(
        Enrollment.objects.filter(role__name="Student").select_related(
            "user", "course", "instrument"
        )
    )

    cas_by_course = defaultdict(list)
    for ca in course_assignments:
        cas_by_course[ca.course_id].append(ca)
    enr_by_course = defaultdict(list)
    for e in enrollments:
        enr_by_course[e.course_id].append(e)

    grouped_ca_ids = set(
        GroupAssignment.objects.values_list("course_assignment_id", flat=True)
    )
    member_pairs = set(
        GroupAssignment.objects.values_list("course_assignment_id", "enrollment_id")
    )

    subs_by_pair = defaultdict(list)
    for s in Submission.objects.select_related("grade", "self_grade").prefetch_related(
        "attachments"
    ):
        subs_by_pair[(s.course_assignment_id, s.enrollment_id)].append(s)

    rows = []
    for course_id, course_cas in cas_by_course.items():
        for enrollment in enr_by_course.get(course_id, []):
            for ca in course_cas:
                # Skip grouped CourseAssignments this student isn't a member of.
                if (
                    ca.id in grouped_ca_ids
                    and (ca.id, enrollment.id) not in member_pairs
                ):
                    continue
                rows.append(
                    SimpleNamespace(
                        id=ca.id,
                        enrollment=enrollment,
                        piece=ca.piece,
                        piece_plan=ca.piece_plan,
                        activity=ca.activity,
                        instrument=resolve_instrument(enrollment, ca),
                        submissions=subs_by_pair.get((ca.id, enrollment.id), []),
                    )
                )
    return rows


def _id(obj):
    return obj.id if obj is not None else "N/A"


def _name(obj):
    return obj.name if obj is not None else "N/A"


class AssignmentListView(UserPassesTestMixin, generic.ListView):
    template_name = "assignments/assignment_list.html"
    context_object_name = "assignment_list"
    paginate_by = 100

    def get_queryset(self):
        return build_assignment_rows()

    def test_func(self):
        return self.request.user.is_superuser


class CourseListView(UserPassesTestMixin, generic.ListView):
    model = Course

    def test_func(self):
        return self.request.user.is_superuser


def csv_view(request):
    """Generate the per-(student, CourseAssignment) CSV export for download."""
    rows = build_assignment_rows()

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
    for assn in rows:
        prefix = [
            assn.id,
            assn.enrollment.course.id,
            assn.enrollment.course.name,
            assn.piece.id,
            assn.piece.name,
            _id(assn.piece_plan),
            assn.piece_plan or "N/A",
            assn.enrollment.user.id,
            _id(assn.enrollment.instrument),
            _name(assn.enrollment.instrument),
            assn.activity.id,
            assn.activity,
            _id(assn.instrument),
            _name(assn.instrument),
        ]
        if len(assn.submissions) == 0:
            writer.writerow(prefix + ["N/A"] * 8)
            continue
        for sub in assn.submissions:
            for att in sub.attachments.all():
                content = (
                    "Create, see below"
                    if assn.activity.category == "Create"
                    else sub.content
                )
                writer.writerow(
                    prefix
                    + [
                        sub.id,
                        content,
                        sub.submitted,
                        sub.grade,
                        sub.self_grade,
                        att.id,
                        att.file,
                        att.submitted,
                    ]
                )
    return response
