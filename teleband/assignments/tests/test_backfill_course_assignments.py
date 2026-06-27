"""Test the Phase 2 step-4 backfill (Assignment -> CourseAssignment/GroupAssignment)."""

import importlib

import pytest
from django.apps import apps as global_apps

from teleband.assignments.models import CourseAssignment, GroupAssignment
from teleband.assignments.tests.factories import (
    ActivityFactory,
    AssignmentFactory,
    AssignmentGroupFactory,
)
from teleband.courses.tests.factories import CourseFactory, EnrollmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory

pytestmark = pytest.mark.django_db


def _run_backfill():
    # The migration module name starts with a digit, so import it via importlib.
    mod = importlib.import_module(
        "teleband.assignments.migrations.0039_backfill_course_assignments"
    )
    mod.backfill_course_assignments(global_apps, None)


def test_backfill_collapses_assignments_by_course_activity_piece():
    course = CourseFactory()
    piece = PieceFactory()
    activity = ActivityFactory()
    part = PartFactory(piece=piece)
    # Two students with the same (course, activity, piece) assignment.
    for _ in range(2):
        enrollment = EnrollmentFactory(course=course)
        AssignmentFactory(
            activity=activity,
            enrollment=enrollment,
            part=part,
            piece=piece,
        )

    _run_backfill()

    # Collapses to a single CourseAssignment.
    assert (
        CourseAssignment.objects.filter(
            course=course, activity=activity, piece=piece
        ).count()
        == 1
    )


def test_backfill_derives_piece_from_part_when_piece_null():
    course = CourseFactory()
    piece = PieceFactory()
    part = PartFactory(piece=piece)
    enrollment = EnrollmentFactory(course=course)
    # Legacy row: piece is NULL but part.piece is set.
    AssignmentFactory(enrollment=enrollment, part=part, piece=None)

    _run_backfill()

    ca = CourseAssignment.objects.get(course=course)
    assert ca.piece_id == piece.id


def test_backfill_creates_group_assignments_for_grouped_rows():
    course = CourseFactory()
    piece = PieceFactory()
    group = AssignmentGroupFactory()
    enrollment = EnrollmentFactory(course=course)
    part = PartFactory(piece=piece)
    AssignmentFactory(
        activity=ActivityFactory(),
        enrollment=enrollment,
        part=part,
        piece=piece,
        group=group,
    )

    _run_backfill()

    ga = GroupAssignment.objects.get(enrollment=enrollment)
    assert ga.group_id == group.id
    assert ga.course_assignment.course_id == course.id
