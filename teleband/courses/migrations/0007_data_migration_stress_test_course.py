import os
from datetime import date

from django.contrib.auth.hashers import make_password
from django.db import migrations


def stress_test_course(apps, schema_editor):
    User = apps.get_model("users", "User")
    Course = apps.get_model("courses", "Course")
    Enrollment = apps.get_model("courses", "Enrollment")
    Role = apps.get_model("users", "Role")
    Instrument = apps.get_model("instruments", "Instrument")
    Curriculum = apps.get_model("assignments", "Curriculum")
    CurriculumEntry = apps.get_model("assignments", "CurriculumEntry")
    PiecePlan = apps.get_model("assignments", "PiecePlan")
    PlannedActivity = apps.get_model("assignments", "PlannedActivity")
    Assignment = apps.get_model("assignments", "Assignment")
    Part = apps.get_model("musics", "Part")
    PartType = apps.get_model("musics", "PartType")

    teacher_role = Role.objects.get(name="Teacher")
    student_role = Role.objects.get(name="Student")
    trombone = Instrument.objects.filter(name="Trombone").first()

    demomike = User.objects.get(username="demomike")
    demoalden = User.objects.get(username="demoalden")

    # Create the course
    course = Course.objects.create(
        name="Stress Test",
        owner=demomike,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        slug="stress-test",
    )

    # Enroll demomike as teacher
    Enrollment.objects.create(user=demomike, course=course, role=teacher_role)

    # Enroll demoalden as student
    student_enrollments = []
    enrollment = Enrollment.objects.create(
        user=demoalden, course=course, instrument=trombone, role=student_role
    )
    student_enrollments.append(enrollment)

    # Create 30 users and enroll as students
    prefix = os.environ.get("STRESS_TEST_STUDENT_USER_PREFIX", "stresstest")
    start = int(os.environ.get("STRESS_TEST_STUDENT_USER_START", "1"))
    for i in range(int(os.environ.get("STRESS_TEST_STUDENT_USER_COUNT", "30"))):
        username = f"{prefix}{i + start}"
        password = make_password(os.environ.get("STRESS_TEST_STUDENT_PW", "changeme"))
        user = User.objects.create(username=username, password=password)
        enrollment = Enrollment.objects.create(
            user=user, course=course, instrument=trombone, role=student_role
        )
        student_enrollments.append(enrollment)

    # Copy the "ALL Curriculum" to this course
    sixth_grade = Course.objects.get(slug="6th-grade-band")
    source_curriculum = Curriculum.objects.get(name="ALL Curriculum", course=sixth_grade)
    new_curriculum = Curriculum.objects.create(
        name="ALL Curriculum",
        ordered=source_curriculum.ordered,
        course=course,
    )

    source_entries = CurriculumEntry.objects.filter(
        curriculum=source_curriculum
    ).order_by("order")

    for entry in source_entries:
        source_plan = entry.piece_plan
        # Create a new PiecePlan copy
        new_plan = PiecePlan.objects.create(
            name=source_plan.name,
            piece=source_plan.piece,
            type=source_plan.type,
        )
        # Copy planned activities
        for pa in PlannedActivity.objects.filter(piece_plan=source_plan).order_by(
            "order"
        ):
            PlannedActivity.objects.create(
                piece_plan=new_plan, activity=pa.activity, order=pa.order
            )
        # Link to new curriculum
        CurriculumEntry.objects.create(
            curriculum=new_curriculum, piece_plan=new_plan, order=entry.order
        )

        # Assign this piece plan's activities to all students
        piece = new_plan.piece
        melody_part_type = PartType.objects.get(name="Melody")
        for pa in PlannedActivity.objects.filter(piece_plan=new_plan).order_by("order"):
            activity = pa.activity
            # Replicate Part.for_activity logic
            if (
                activity.part_type_id
                and Part.objects.filter(
                    piece=piece, part_type_id=activity.part_type_id
                ).exists()
            ):
                part = Part.objects.get(piece=piece, part_type_id=activity.part_type_id)
            else:
                part = Part.objects.get(piece=piece, part_type=melody_part_type)

            for enrollment in student_enrollments:
                Assignment.objects.create(
                    activity=activity,
                    enrollment=enrollment,
                    part=part,
                    instrument=trombone,
                    piece_plan=new_plan,
                    piece=piece,
                )


def reverse_stress_test(apps, schema_editor):
    Course = apps.get_model("courses", "Course")
    try:
        course = Course.objects.get(slug="stress-test")
    except Course.DoesNotExist:
        return

    Assignment = apps.get_model("assignments", "Assignment")
    Enrollment = apps.get_model("courses", "Enrollment")
    CurriculumEntry = apps.get_model("assignments", "CurriculumEntry")
    Curriculum = apps.get_model("assignments", "Curriculum")
    PlannedActivity = apps.get_model("assignments", "PlannedActivity")
    PiecePlan = apps.get_model("assignments", "PiecePlan")

    enrollments = Enrollment.objects.filter(course=course)
    Assignment.objects.filter(enrollment__in=enrollments).delete()

    for curr in Curriculum.objects.filter(course=course):
        for entry in CurriculumEntry.objects.filter(curriculum=curr):
            PlannedActivity.objects.filter(piece_plan=entry.piece_plan).delete()
            entry.piece_plan.delete()
        CurriculumEntry.objects.filter(curriculum=curr).delete()
        curr.delete()

    enrollments.delete()
    course.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0006_course_can_edit_instruments"),
        ("assignments", "0036_assignment_unique_assignment_20240320_1310"),
        ("users", "0004_data_migration_demo_users"),
        ("instruments", "0001_initial"),
        ("musics", "0020_auto_20230918_1451_seed_beginning_orchestra"),
    ]

    operations = [
        migrations.RunPython(stress_test_course, reverse_stress_test),
    ]
