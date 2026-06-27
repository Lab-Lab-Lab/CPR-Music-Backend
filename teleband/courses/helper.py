from teleband.courses.models import Enrollment, Course
from teleband.musics.models import Piece, Part
from teleband.assignments.models import (
    Activity,
    ActivityType,
    Assignment,
    AssignmentGroup,
    CourseAssignment,
    GroupAssignment,
    PiecePlan,
)
import random


def assign_all_piece_activities(course, piece, deadline=None):
    assignments = []
    for activity in Activity.objects.filter(
        activity_type__name__in=get_query_type_names(piece)
    ):
        assignments += assign_one_piece_activity(course, piece, activity, deadline)
    return assignments


def assign_one_piece_activity(course, piece, activity, deadline=None, piece_plan=None):
    # One row per (activity, enrollment, piece) -- the model's unique constraint.
    # Create the missing ones in a single bulk_create instead of an
    # update_or_create per student (which was 2 queries each and silently
    # swallowed the constraint violation on re-assign). Students who already have
    # the assignment are left untouched, matching the prior effective behavior.
    # Phase 2 dual-write: the course-level row is the future source of truth; the
    # per-student Assignment rows below remain until the read path is flipped.
    CourseAssignment.objects.update_or_create(
        course=course,
        activity=activity,
        piece=piece,
        defaults={"piece_plan": piece_plan, "deadline": deadline},
    )

    part = Part.for_activity(activity, piece)
    # NB: do NOT select_related("user") here. This helper is called from the live
    # data migration assignments/0033, where eagerly selecting all user columns
    # touches users.external_id before that column's migration has run. Enrollment
    # instrument is enough; user is only read for the rare no-enrollment-instrument
    # fallback below.
    enrollments = Enrollment.objects.filter(
        course=course, role__name="Student"
    ).select_related("instrument")
    already_assigned = set(
        Assignment.objects.filter(
            activity=activity, piece=piece, enrollment__course=course
        ).values_list("enrollment_id", flat=True)
    )
    to_create = [
        Assignment(
            activity=activity,
            enrollment=e,
            instrument=e.instrument if e.instrument else e.user.instrument,
            part=part,
            piece=piece,
            piece_plan=piece_plan,
            deadline=deadline,
        )
        for e in enrollments
        if e.id not in already_assigned
    ]
    return Assignment.objects.bulk_create(to_create)


def assign_piece_plan(course, piece_plan, deadline=None):
    if not piece_plan.type or piece_plan.type != "telephone_fixed":
        return assign_vanilla_piece_plan(course, piece_plan, deadline)
    else:  # piece_plan.type == "telephone_fixed":
        return assign_telephone_fixed(course, piece_plan, deadline)
    # else:
    #     raise Exception("Unknown piece plan type")


def assign_vanilla_piece_plan(course, piece_plan, deadline=None):
    assignments = []
    for activity in piece_plan.activities.all():
        assignments += assign_one_piece_activity(
            course, piece_plan.piece, activity, deadline, piece_plan
        )
    return assignments


class AssignmentGroupSizeException(Exception):
    pass


def assign_telephone_fixed(course, piece_plan, deadline=None):
    num_activities = piece_plan.activities.count()
    num_enrollments = Enrollment.objects.filter(
        course=course, role__name="Student"
    ).count()
    excess_enrollments = num_enrollments % num_activities
    if num_enrollments < num_activities:
        raise AssignmentGroupSizeException()

    # split the enrollments into groups of num_activities at random
    # and then assign the excess enrollments to the last group
    enrollments = list(
        Enrollment.objects.filter(course=course, role__name="Student").select_related(
            "instrument"
        )
    )
    random.shuffle(enrollments)
    final_group = [] if excess_enrollments == 0 else enrollments[-excess_enrollments:]
    groups = [
        enrollments[i : i + num_activities]
        for i in range(0, len(enrollments) - excess_enrollments, num_activities)
    ]

    if excess_enrollments != 0:
        used_enrollments = enrollments[0 : len(enrollments) - excess_enrollments]
        random.shuffle(used_enrollments)
        final_group += used_enrollments[0 : num_activities - excess_enrollments]
        groups.append(final_group)

    # create one AssignmentGroup per group of enrollments, then assign each
    # enrollment to an activity in the piece plan within that group. Activities
    # and their parts are resolved once (not per group/assignment), and the
    # groups and assignments are each written in a single bulk_create.
    piece = piece_plan.piece
    activities = list(piece_plan.activities.all())
    part_by_activity = {a.id: Part.for_activity(a, piece) for a in activities}

    # Phase 2 dual-write: one CourseAssignment per activity for the course, plus a
    # GroupAssignment per member restricting which student gets which activity.
    course_assignment_by_activity = {
        a.id: CourseAssignment.objects.update_or_create(
            course=course,
            activity=a,
            piece=piece,
            defaults={"piece_plan": piece_plan, "deadline": deadline},
        )[0]
        for a in activities
    }

    group_objs = AssignmentGroup.objects.bulk_create(
        [AssignmentGroup(type="telephone_fixed") for _ in groups]
    )

    to_create = []
    group_memberships = []
    for group, assignment_group in zip(groups, group_objs):
        for e, a in zip(group, activities):
            to_create.append(
                Assignment(
                    activity=a,
                    part=part_by_activity[a.id],
                    enrollment=e,
                    instrument=e.instrument if e.instrument else e.user.instrument,
                    piece_plan=piece_plan,
                    piece=piece,
                    group=assignment_group,
                )
            )
            group_memberships.append(
                GroupAssignment(
                    group=assignment_group,
                    enrollment=e,
                    course_assignment=course_assignment_by_activity[a.id],
                )
            )
    GroupAssignment.objects.bulk_create(group_memberships, ignore_conflicts=True)
    return Assignment.objects.bulk_create(to_create)


def assign_curriculum(course, curriculum, deadline=None):
    # for each piece plan in the curriculum, assign all planned activities
    # in the piece plan.
    return sum(
        (
            assign_piece_plan(course, piece_plan, deadline)
            for piece_plan in curriculum.piece_plans.all()
        ),
        [],
    )


def get_query_type_names(piece):
    # FIXME: What follows is a hack to get around the facts that:
    # 1. We don't have a way to indicate that some activity types are only available to certain pieces.
    # 2. we don't have a way for the same activity on different types to have differing instructions.
    defaults = [
        "Creativity",
        "Reflection",
        "Melody",
        "Bassline",
        "MelodyPost",
        "BasslinePost",
    ]
    connects = {
        "The Favorite": "Connect Benjamin",
        "Freedom 2040 (Band)": "Connect Green",
        "Freedom 2040 (Orchestra)": "Connect Green",
        "Down by the Riverside": "Connect Danyew",
        "Deep River": "Connect Danyew",
        "I Want to be Ready": "Connect Danyew",
    }

    query_type_names = defaults.copy()
    if piece.name in connects:
        query_type_names.append(connects[piece.name])
    return query_type_names
