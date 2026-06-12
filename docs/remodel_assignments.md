# Remodel Assignments: Course-Level Instead of Enrollment-Level

## Problem

When a teacher assigns a piece to their course, every PlannedActivity in the PiecePlan results in a new Assignment instance for each Enrollment in the course. This is problematic because:

1. It creates a large number of Assignment rows (students x activities).
2. Students who join the course after a piece has been assigned get no assignments, and there is no UI path for a teacher to assign pieces to late joiners.

## Current State

### Assignment Model

```
Assignment:
  - activity (FK -> Activity, PROTECT)
  - enrollment (FK -> Enrollment, PROTECT)
  - part (FK -> Part, PROTECT)
  - instrument (FK -> Instrument, PROTECT)
  - piece (FK -> Piece, nullable, PROTECT)
  - piece_plan (FK -> PiecePlan, nullable, PROTECT)
  - group (FK -> AssignmentGroup, nullable, PROTECT)
  - deadline (DateField, nullable)
  - created_at (auto_now_add)

  Unique constraint: (activity, enrollment, piece)
```

### Key Relationships

- `Assignment -> Enrollment -> (User, Course)`
- `Assignment -> Activity, Part, Piece, PiecePlan`
- `Submission -> Assignment` (tracks student work)

### Creation Logic (courses/helper.py)

- `assign_one_piece_activity()` loops over every Student enrollment in the course, creating one Assignment per enrollment.
- `assign_vanilla_piece_plan()` iterates all activities in a piece plan and calls `assign_one_piece_activity()` for each.
- `assign_telephone_fixed()` groups students randomly and assigns one unique activity per student within each group.

## Proposed Changes

### 1. New `CourseAssignment` Model

Replace the enrollment-level link with a course-level one:

```
CourseAssignment:
  - course (FK -> Course)
  - activity (FK -> Activity)
  - piece (FK -> Piece)
  - piece_plan (FK -> PiecePlan, nullable)
  - deadline (DateField, nullable)
  - created_at (auto_now_add)

  Unique constraint: (course, activity, piece)
```

One row per activity per piece per course, regardless of student count.

### 2. Move Per-Student Fields to Submission

The `instrument` and `part` fields are student-specific (they depend on the student's instrument, and a student may override the instrument from their enrollment). These move to `Submission`:

```
Submission (modified):
  - course_assignment (FK -> CourseAssignment)  # replaces assignment FK
  - enrollment (FK -> Enrollment)               # ties it to the student
  - instrument (FK -> Instrument)               # defaults from enrollment, overridable
  - part (FK -> Part)                           # resolved from instrument + activity
  - grade, self_grade, content, etc.            # unchanged
```

This is a better home for `instrument` than the current Assignment model, since a student could theoretically use different instruments across submissions for the same assignment.

### 3. Changes to Creation Logic (courses/helper.py)

- `assign_one_piece_activity()` creates/updates a single `CourseAssignment` row (no enrollment loop).
- `assign_vanilla_piece_plan()` creates one `CourseAssignment` per activity (not per student x activity).
- `assign_telephone_fixed()` needs special handling since grouping is inherently per-student. Groups could be created lazily or kept as a separate concern.

### 4. Resolve Assignments for a Student Dynamically

When a student (enrollment) accesses their assignments:

- Query `CourseAssignment.objects.filter(course=enrollment.course)`
- Resolve `part` and `instrument` from the enrollment at read time via `Part.for_activity()`
- Create `Submission` records on first access or on-demand

This means late joiners automatically see all course assignments.

### 5. Migration Path

1. Add `CourseAssignment` model.
2. Data migration: deduplicate existing Assignment rows into CourseAssignment (group by course, activity, piece).
3. Add `course_assignment` + `enrollment` FKs to Submission, backfill from existing `assignment` FK.
4. Update serializers/views to use the new model.
5. Remove old `Assignment` model (or deprecate).

### 6. Files That Need Changes

| File | Change |
|---|---|
| `assignments/models.py` | Add `CourseAssignment`, modify/remove `Assignment` |
| `submissions/models.py` | Change FK from `Assignment` to `CourseAssignment` + `Enrollment` |
| `courses/helper.py` | Rewrite all `assign_*` functions to create `CourseAssignment` |
| `courses/api/views.py` | Update assign/unassign endpoints |
| `assignments/api/serializers.py` | Rewrite for new model |
| `assignments/api/views.py` | Rewrite queryset and logic |
| `assignments/admin.py` | Update for new model |
| `courses/api/serializers.py` | Update enrollment-related serializers |

## Benefits

- Drastically fewer rows: 1 per activity x course instead of 1 per activity x course x student.
- Late joiners get assignments automatically by querying CourseAssignment by course.
- Cleaner separation of concerns: "what's assigned to the course" vs "what a student has submitted."

## Open Questions

- The `telephone_fixed` piece plan type assigns different activities to different students within groups. This is inherently per-student, so it may need to remain a special case -- either keeping a lightweight per-student assignment model for grouped activities, or handling group assignment as a separate concept.
