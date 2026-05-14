from django.db import migrations


def rename_beginner_prefix_to_suffix(apps, schema_editor):
    ActivityType = apps.get_model("assignments", "ActivityType")
    Activity = apps.get_model("assignments", "Activity")

    prefix = "Beginner "
    for at in ActivityType.objects.filter(name__startswith=prefix):
        old_name = at.name
        new_name = at.name[len(prefix) :] + " Beginner"
        at.name = new_name
        at.save()

        Activity.objects.filter(activity_type_name=old_name).update(
            activity_type_name=new_name
        )


def rename_beginner_suffix_to_prefix(apps, schema_editor):
    ActivityType = apps.get_model("assignments", "ActivityType")
    Activity = apps.get_model("assignments", "Activity")

    suffix = " Beginner"
    for at in ActivityType.objects.filter(name__endswith=suffix):
        old_name = at.name
        new_name = "Beginner " + at.name[: -len(suffix)]
        at.name = new_name
        at.save()

        Activity.objects.filter(activity_type_name=old_name).update(
            activity_type_name=new_name
        )


class Migration(migrations.Migration):

    dependencies = [
        ("assignments", "0036_assignment_unique_assignment_20240320_1310"),
    ]

    operations = [
        migrations.RunPython(
            rename_beginner_prefix_to_suffix, rename_beginner_suffix_to_prefix
        ),
    ]
