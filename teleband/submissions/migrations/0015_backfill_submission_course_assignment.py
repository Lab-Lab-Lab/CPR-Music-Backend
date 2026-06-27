from django.db import migrations


def backfill_submission_fields(apps, schema_editor):
    """Populate Submission.course_assignment / enrollment / instrument / part for
    existing rows, resolved from the per-student Assignment the submission points at.
    Piece is derived from part.piece when Assignment.piece is null (legacy rows)."""
    Submission = apps.get_model("submissions", "Submission")
    CourseAssignment = apps.get_model("assignments", "CourseAssignment")

    ca_map = {
        (ca["course_id"], ca["activity_id"], ca["piece_id"]): ca["id"]
        for ca in CourseAssignment.objects.values(
            "id", "course_id", "activity_id", "piece_id"
        )
    }

    updates = []
    rows = Submission.objects.values(
        "id",
        "assignment__enrollment_id",
        "assignment__instrument_id",
        "assignment__part_id",
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
        sub = Submission(id=r["id"])
        sub.course_assignment_id = ca_id
        sub.enrollment_id = r["assignment__enrollment_id"]
        sub.instrument_id = r["assignment__instrument_id"]
        sub.part_id = r["assignment__part_id"]
        updates.append(sub)

    if updates:
        Submission.objects.bulk_update(
            updates,
            ["course_assignment", "enrollment", "instrument", "part"],
            batch_size=500,
        )


class Migration(migrations.Migration):

    dependencies = [
        (
            "submissions",
            "0014_submission_course_assignment_submission_enrollment_and_more",
        ),
        ("assignments", "0039_backfill_course_assignments"),
    ]

    operations = [
        migrations.RunPython(backfill_submission_fields, migrations.RunPython.noop),
    ]
