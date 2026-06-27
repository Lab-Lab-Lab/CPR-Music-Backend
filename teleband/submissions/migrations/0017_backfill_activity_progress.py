from django.db import migrations


def backfill_activity_progress(apps, schema_editor):
    """Populate ActivityProgress.course_assignment / enrollment for existing rows,
    resolved from the OneToOne assignment (piece derived from part.piece when the
    assignment's piece is null)."""
    ActivityProgress = apps.get_model("submissions", "ActivityProgress")
    CourseAssignment = apps.get_model("assignments", "CourseAssignment")

    ca_map = {
        (ca["course_id"], ca["activity_id"], ca["piece_id"]): ca["id"]
        for ca in CourseAssignment.objects.values(
            "id", "course_id", "activity_id", "piece_id"
        )
    }

    updates = []
    rows = ActivityProgress.objects.values(
        "id",
        "assignment__enrollment_id",
        "assignment__enrollment__course_id",
        "assignment__activity_id",
        "assignment__piece_id",
        "assignment__part__piece_id",
    )
    for r in rows.iterator():
        piece_id = r["assignment__piece_id"] or r["assignment__part__piece_id"]
        ca_id = ca_map.get(
            (
                r["assignment__enrollment__course_id"],
                r["assignment__activity_id"],
                piece_id,
            )
        )
        progress = ActivityProgress(id=r["id"])
        progress.course_assignment_id = ca_id
        progress.enrollment_id = r["assignment__enrollment_id"]
        updates.append(progress)

    if updates:
        ActivityProgress.objects.bulk_update(
            updates, ["course_assignment", "enrollment"], batch_size=500
        )


class Migration(migrations.Migration):

    dependencies = [
        ("submissions", "0016_activityprogress_course_assignment_and_more"),
        ("assignments", "0039_backfill_course_assignments"),
    ]

    operations = [
        migrations.RunPython(backfill_activity_progress, migrations.RunPython.noop),
    ]
