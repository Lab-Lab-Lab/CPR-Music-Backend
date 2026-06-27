from django.db import migrations


def backfill_course_assignments(apps, schema_editor):
    """Create CourseAssignment (and GroupAssignment) rows from existing per-student
    Assignment rows, collapsing by (course, activity, piece).

    Legacy Assignment rows may have piece IS NULL (piece became nullable in
    migration 0026 and was never backfilled). Every Assignment has a non-null
    part, and Part.piece is non-null, so we derive the piece from part.piece when
    Assignment.piece is null -- this both fixes the legacy rows and keeps the
    CourseAssignment.piece NOT NULL invariant.
    """
    Assignment = apps.get_model("assignments", "Assignment")
    CourseAssignment = apps.get_model("assignments", "CourseAssignment")
    GroupAssignment = apps.get_model("assignments", "GroupAssignment")

    seen = set()
    to_create = []
    rows = Assignment.objects.values(
        "enrollment__course_id",
        "activity_id",
        "piece_id",
        "part__piece_id",
        "piece_plan_id",
        "deadline",
    )
    for row in rows.iterator():
        course_id = row["enrollment__course_id"]
        piece_id = row["piece_id"] or row["part__piece_id"]
        key = (course_id, row["activity_id"], piece_id)
        if key in seen:
            continue
        seen.add(key)
        to_create.append(
            CourseAssignment(
                course_id=course_id,
                activity_id=row["activity_id"],
                piece_id=piece_id,
                piece_plan_id=row["piece_plan_id"],
                deadline=row["deadline"],
            )
        )
    CourseAssignment.objects.bulk_create(to_create, ignore_conflicts=True)

    # Map (course, activity, piece) -> course_assignment id for the group backfill.
    ca_map = {
        (ca["course_id"], ca["activity_id"], ca["piece_id"]): ca["id"]
        for ca in CourseAssignment.objects.values(
            "id", "course_id", "activity_id", "piece_id"
        )
    }

    seen_ga = set()
    ga_to_create = []
    grouped = Assignment.objects.filter(group__isnull=False).values(
        "group_id",
        "enrollment_id",
        "enrollment__course_id",
        "activity_id",
        "piece_id",
        "part__piece_id",
    )
    for row in grouped.iterator():
        piece_id = row["piece_id"] or row["part__piece_id"]
        ca_id = ca_map.get((row["enrollment__course_id"], row["activity_id"], piece_id))
        if ca_id is None:
            continue
        key = (row["enrollment_id"], ca_id)
        if key in seen_ga:
            continue
        seen_ga.add(key)
        ga_to_create.append(
            GroupAssignment(
                group_id=row["group_id"],
                enrollment_id=row["enrollment_id"],
                course_assignment_id=ca_id,
            )
        )
    GroupAssignment.objects.bulk_create(ga_to_create, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0038_courseassignment_groupassignment_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_course_assignments, migrations.RunPython.noop),
    ]
