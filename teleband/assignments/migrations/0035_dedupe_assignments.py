from django.db import migrations, models


def remove_dupes(apps, schema_editor):
    Activity = apps.get_model("assignments", "Activity")
    Course = apps.get_model("courses", "Course")
    # Enrollment = apps.get_model('courses', 'Enrollment')
    Piece = apps.get_model("musics", "Piece")

    # check each course for duplicate assignments
    for c in Course.objects.all():

        # assignments are only duplicates if they are assigned to the same student (enrollment), and ...
        for e in c.enrollment_set.all():

            # ...if they are the same activity and ...
            for act in Activity.objects.all():

                # ...they are for the same piece
                for p in Piece.objects.all():
                    dupes = e.assignment_set.filter(activity=act, piece=p).order_by(
                        "-created_at"
                    )
                    if dupes.count() > 1:
                        delete_dupes(dupes)


"""
given a queryset of assignments that all have the same enrollment (student), 
activity, and piece, find the one with the most recent submission, and delete 
the others.
"""


def delete_dupes(dupes):
    # assume the first assignment is the one with the most recent submission
    assn_w_max_sub_date = dupes[0]
    max_sub_for_assn = None
    if assn_w_max_sub_date.submissions.order_by("-submitted").count() > 0:
        max_sub_for_assn = assn_w_max_sub_date.submissions.order_by("-submitted")[0]

    to_remove = []

    # loop over the rest of the assignments to see if any has a more recent submission
    for d in dupes[1:]:

        # either this assn has no submissions and we can remove this assn,
        # or this assn has a more recent submission and we need to remove previous max assn
        # or this assn's most recent sub is older and we need to remove this assn
        if d.submissions.count() == 0:
            to_remove.append(d)
            continue
        else:
            most_recent_sub = d.submissions.order_by("-submitted")[0]
            if max_sub_for_assn is None or most_recent_sub.submitted > max_sub_for_assn:
                to_remove.append(assn_w_max_sub_date)
                assn_w_max_sub_date = d
                max_sub_for_assn = most_recent_sub
            else:
                to_remove.append(d)

    for r in to_remove:
        subs = r.submissions.all()
        for sub in subs:
            sub.attachments.all().delete()
        # attachments = [sub.attachments.all() for sub in subs]
        # for a in attachments:
        #     a.delete()
        subs.delete()
        r.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0034_auto_20240315_1547"),
    ]

    operations = [
        migrations.RunPython(remove_dupes, migrations.RunPython.noop),
    ]
