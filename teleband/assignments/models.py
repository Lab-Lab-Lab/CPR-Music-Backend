from django.db import models

from teleband.courses.models import Course, Enrollment
from teleband.musics.models import PartType, Piece


class ActivityCategory(models.Model):

    name = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Activity Category"
        verbose_name_plural = "Activity Categories"

    def __str__(self):
        return self.name


class ActivityType(models.Model):

    name = models.CharField(unique=True, max_length=255)
    category = models.ForeignKey(ActivityCategory, on_delete=models.PROTECT)

    class Meta:
        verbose_name = "Activity Type"
        verbose_name_plural = "Activity Types"

    def __str__(self):
        return f"{self.name}"


class Activity(models.Model):

    activity_type = models.ForeignKey(ActivityType, on_delete=models.PROTECT)
    part_type = models.ForeignKey(PartType, null=True, on_delete=models.PROTECT)
    body = models.TextField()
    number_of_submissions = models.PositiveIntegerField(default=1)
    activity_type_name = models.CharField(max_length=255, null=True, blank=True)
    category = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Activity"
        verbose_name_plural = "Activities"

    def __str__(self):
        return f"{self.activity_type}: {self.part_type}"


class PiecePlan(models.Model):

    name = models.CharField(max_length=255)
    activities = models.ManyToManyField(Activity, through="PlannedActivity")
    piece = models.ForeignKey(Piece, on_delete=models.PROTECT)
    type = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        if self.type:
            return f"{self.name}: {self.piece.name} ({self.type})"
        else:
            return f"{self.name}: {self.piece.name} "


class AssignmentGroup(models.Model):

    type = models.CharField(max_length=255, null=True, blank=True)


class CourseAssignment(models.Model):
    """What a course is assigned: one row per (course, activity, piece), instead of
    one Assignment per enrolled student. Per-student data (instrument, part) is
    resolved at read time and persisted on Submission. See docs/remodel_phase2_design.md.
    """

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="course_assignments"
    )
    activity = models.ForeignKey(Activity, on_delete=models.PROTECT)
    piece = models.ForeignKey(Piece, on_delete=models.PROTECT)
    piece_plan = models.ForeignKey(
        PiecePlan, on_delete=models.PROTECT, null=True, blank=True
    )
    # Course-level per-piece instrument override (set by change_piece_instrument).
    # Null means each student resolves their own instrument from their enrollment.
    instrument = models.ForeignKey(
        "instruments.Instrument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    deadline = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course", "activity", "piece"],
                name="unique_course_assignment",
            )
        ]
        indexes = [models.Index(fields=["course", "piece"])]

    def __str__(self):
        return f"{self.course.slug}: {self.activity_id} {self.piece}"


class GroupAssignment(models.Model):
    """Links a student (enrollment) to a specific CourseAssignment within a group,
    for telephone_fixed plans where different students get different activities.
    Normal plans need no GroupAssignment -- every enrolled student is implicitly
    assigned every non-grouped CourseAssignment in their course."""

    group = models.ForeignKey(
        AssignmentGroup, on_delete=models.CASCADE, related_name="memberships"
    )
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE)
    course_assignment = models.ForeignKey(
        CourseAssignment, on_delete=models.CASCADE, related_name="group_assignments"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["enrollment", "course_assignment"],
                name="unique_group_assignment",
            )
        ]

    def __str__(self):
        return f"{self.enrollment} -> {self.course_assignment} (group {self.group_id})"


class PlannedActivity(models.Model):

    piece_plan = models.ForeignKey(PiecePlan, on_delete=models.CASCADE)
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE)
    order = models.PositiveIntegerField()

    class Meta:
        unique_together = ["piece_plan", "activity"]
        ordering = ["piece_plan__name", "order"]
        verbose_name_plural = "Planned Activities"

    def __str__(self):
        return f"{self.piece_plan.name}: {self.activity}"


class Curriculum(models.Model):

    name = models.CharField(max_length=255)
    ordered = models.BooleanField(default=False)
    piece_plans = models.ManyToManyField(PiecePlan, through="CurriculumEntry")
    course = models.ForeignKey(Course, on_delete=models.PROTECT)

    class Meta:
        verbose_name = "Curriculum"
        verbose_name_plural = "Curricula"

    def __str__(self):
        return f"{self.name}: {self.course.name}"


class CurriculumEntry(models.Model):

    curriculum = models.ForeignKey(Curriculum, on_delete=models.CASCADE)
    piece_plan = models.ForeignKey(PiecePlan, on_delete=models.CASCADE)
    order = models.PositiveIntegerField()

    class Meta:
        unique_together = ["curriculum", "piece_plan"]
        ordering = ["order"]

    def __str__(self):
        return f"{self.curriculum.name}: {self.piece_plan.name}"
