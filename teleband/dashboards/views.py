import csv
from collections import defaultdict
from types import SimpleNamespace

from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import HttpResponse, JsonResponse
from django.views import generic

from teleband.assignments.api.serializers import resolve_instrument
from teleband.assignments.models import CourseAssignment, GroupAssignment
from teleband.courses.models import Course, Enrollment
from teleband.submissions.models import Submission, SubmissionAttachment


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


class ResearchDashboardView(UserPassesTestMixin, generic.TemplateView):
    template_name = "dashboards/research.html"

    def test_func(self):
        return self.request.user.is_superuser

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["courses"] = Course.objects.select_related("owner").order_by(
            "-start_date", "name"
        )
        return ctx


def _serialize_grade(grade):
    if grade is None:
        return None
    return {
        "rhythm": grade.rhythm,
        "tone": grade.tone,
        "expression": grade.expression,
    }


@user_passes_test(lambda u: u.is_superuser)
def research_data_view(request):
    course_ids = request.GET.getlist("course_ids")
    if not course_ids:
        return JsonResponse({"courses": []})

    courses = Course.objects.filter(id__in=course_ids).select_related("owner")
    course_assignments = (
        CourseAssignment.objects.filter(course_id__in=course_ids)
        .select_related("activity", "activity__activity_type", "piece")
        .order_by("course_id", "id")
    )
    submissions = (
        Submission.objects.filter(course_assignment__course_id__in=course_ids)
        .select_related("grade", "self_grade", "enrollment__user", "instrument")
        .order_by("submitted")
    )
    attachments = SubmissionAttachment.objects.filter(
        submission__course_assignment__course_id__in=course_ids
    )
    atts_by_sub = defaultdict(list)
    for att in attachments:
        if att.file:
            atts_by_sub[att.submission_id].append({"id": att.id, "url": att.file.url})

    subs_by_ca = defaultdict(list)
    for sub in submissions:
        subs_by_ca[sub.course_assignment_id].append(sub)

    cas_by_course = defaultdict(list)
    for ca in course_assignments:
        cas_by_course[ca.course_id].append(ca)

    result = []
    for course in courses:
        course_data = {
            "id": course.id,
            "name": course.name,
            "owner": course.owner.name or course.owner.username,
            "assignments": [],
        }
        for ca in cas_by_course.get(course.id, []):
            assn_data = {
                "id": ca.id,
                "activity": str(ca.activity),
                "category": ca.activity.category or "",
                "piece": str(ca.piece),
                "submissions": [],
            }
            for sub in subs_by_ca.get(ca.id, []):
                assn_data["submissions"].append(
                    {
                        "id": sub.id,
                        "student": sub.enrollment.user.id if sub.enrollment else None,
                        "instrument": str(sub.instrument) if sub.instrument else None,
                        "submitted": sub.submitted.strftime("%Y-%m-%d %H:%M"),
                        "content": sub.content,
                        "grade": _serialize_grade(sub.grade),
                        "self_grade": _serialize_grade(sub.self_grade),
                        "attachments": atts_by_sub.get(sub.id, []),
                    }
                )
            course_data["assignments"].append(assn_data)
        result.append(course_data)

    return JsonResponse({"courses": result})


@user_passes_test(lambda u: u.is_superuser)
def attachment_proxy_view(request, attachment_id):
    """Proxy an attachment file through the server to avoid S3 CORS issues."""
    from django.http import FileResponse, Http404

    try:
        att = SubmissionAttachment.objects.get(pk=attachment_id)
    except SubmissionAttachment.DoesNotExist:
        raise Http404

    try:
        f = att.file.open("rb")
    except Exception:
        raise Http404

    filename = att.file.name.split("/")[-1] if "/" in att.file.name else att.file.name
    return FileResponse(f, as_attachment=False, filename=filename)
