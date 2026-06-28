# Phase 2 Design Scoping — Course-Level Assignments

> Builds on the advisor's plan ([`remodel_assignments.md`](./remodel_assignments.md)) and
> [`remodel_campaign.md`](./remodel_campaign.md). Phase 1 (1a/1b/1c) is shipped on
> `backend-remodel-phase1` (PR #56). **Decision: Option B (fully dynamic).** Steps 1–6 of the
> sequence below are built and committed; steps 7–8 (the contract-sensitive read-path flip and
> dropping `Assignment`) remain. Option A is retained below as the rejected alternative.

## Decisions locked (2026-06-27)

- **Design: Option B (fully dynamic).** `CourseAssignment` is the only assignment row;
  the list `id` becomes the `CourseAssignment` id; nested submission/activity-progress
  routes scope by the requesting student's enrollment; `instrument`/`part` move to
  `Submission`; `ActivityProgress` re-keys to `(course_assignment, enrollment)`. API
  response shape preserved so the frontend is untouched.
- **Session scope: prerequisite only.** Land the migration-0033 safety fix (done — see
  sequence step 1), then pause for review of PR #56 before building the remodel.

**Status of prerequisite (step 1): ✅ DONE** — `assignments/0033` no longer calls live
helper/model code (`add_demos` is a documented no-op). Fresh `migrate` is now robust to
the upcoming helper/model changes.

### Blocker decisions (2026-06-27)

1. **Instrument source of truth:** Enrollment first, then User — preserve the current
   `e.instrument if e.instrument else e.user.instrument` fallback.
2. **`telephone_fixed`:** keep a lightweight per-student group table. `CourseAssignment`
   covers normal plans (every enrolled student is implicitly assigned every non-grouped
   row); a `GroupAssignment(group, enrollment, course_assignment)` table records which
   student gets which activity for grouped plans and restricts visibility to members.
3. **Materialization:** resolve `part`/`instrument` at read time from the enrollment; persist
   nothing per-student until the student submits (the `Submission` carries `instrument`/`part`).
   `ActivityProgress` is `get_or_create((course_assignment, enrollment))` on first access.

### Target models

```
CourseAssignment:  course, activity, piece, piece_plan?, deadline?, created_at
                   unique(course, activity, piece)
GroupAssignment:   group(AssignmentGroup), enrollment, course_assignment
                   unique(enrollment, course_assignment)   # telephone_fixed only
Submission(mod):   course_assignment, enrollment, instrument, part, + existing fields
ActivityProgress(mod): course_assignment, enrollment (was OneToOne(Assignment))
                   unique(course_assignment, enrollment)
```

Student's assignments = `CourseAssignment` for their course where the plan is not
`telephone_fixed`, UNION the `CourseAssignment`s linked to them via `GroupAssignment`.

## Reframing: what Phase 1b already fixed

The advisor's plan targets the per-student assignment row explosion. **Phase 1b already
removed the per-operation query cost**: `assign_*` now `bulk_create`s, so assigning a piece
is O(A) queries regardless of roster size (was 2·A·S). So Phase 2 is no longer about
*query expense per assign*. Its remaining, real motivations are:

1. **Row count / storage** — still A·S rows in the DB (now written efficiently, but stored).
2. **Late joiners** — a student who enrolls after a piece is assigned gets no assignments,
   and there's no UI/endpoint to assign to them. (Correctness gap, not perf.)
3. **Model cleanliness** — `instrument`/`part` are per-student data denormalized onto a row
   that's conceptually "what the course is assigned"; `piece` is redundant with `part.piece`.

This reframing matters for prioritization: Phase 2 is a **correctness + modeling** project
now, not a perf emergency. It can be sequenced deliberately.

## The hinge: the frontend uses a per-student `assignmentId`

`~/GithubOrgs/espadonne/CPR-Music` (`actions.js`, `api.js`) uses an assignment `id` in:

- `GET/POST /api/courses/{slug}/assignments/{id}/submissions/`
- `POST  .../submissions/{submissionId}/attachments/`
- `PATCH /api/courses/{slug}/assignments/{id}/` (instrument override)
- `GET/POST /api/courses/{slug}/assignments/{id}/activity-progress/{,log_event,submit_step,save_response,save_audio_state}`

The `id` comes from each object in the grouped list response. **Any design must keep a stable
id the student can use for these nested routes**, with the decision to preserve the API shape
(frontend untouched).

## Two viable designs

### Option A — Lazy per-student materialization (lower risk)
- `CourseAssignment` becomes the template: one row per `(course, activity, piece)`, created by
  `assign_*` (A rows, not A·S).
- A per-student `Assignment` row is created **on demand** the first time a student accesses
  their assignments (or submits). Its `id` is the same shape as today → **frontend unchanged,
  every nested route keeps working unmodified**.
- Late joiners: their `Assignment` rows materialize on first access → solved.
- Row count: only materializes for students who actually engage; un-accessed assignments cost 0.
- `instrument`/`part` can stay on `Assignment` (resolved at materialization), or move to
  `Submission` later. Smallest blast radius.
- **Trade-off:** keeps the per-student `Assignment` table (just sparse/lazy), so it's a partial
  realization of the advisor's model. But it's incrementally shippable and contract-safe.

### Option B — Fully dynamic (advisor's model)
- `CourseAssignment` is the only "assignment" row. The list endpoint returns
  CourseAssignment-derived objects with `id = course_assignment.id`, resolving `part`/`instrument`
  per student at read time.
- Nested routes reinterpret `{id}` as a `CourseAssignment` id and **scope by the requesting
  student's enrollment** (`request.user`): submissions/activity-progress are keyed by
  `(course_assignment, enrollment)`. The frontend is unchanged because each student only ever
  uses ids from its own list response, and the backend scopes by the authenticated user.
- `instrument`/`part` move to `Submission`; `ActivityProgress` re-keys to
  `(course_assignment, enrollment)`.
- **Trade-off:** matches the advisor's clean model and fully kills per-student rows, but changes
  more semantics (teacher list shape, activity-progress identity, submission resolution) and has
  the larger migration. Higher risk.

**Recommendation:** **Option A first** (contract-safe, incrementally shippable, solves late
joiners and row count), with Option B as a later step if the fully-dynamic model is desired.
This mirrors the phased discipline that worked for Phase 1.

## Migration landmines (must be in the plan)

1. **Migration 0033 calls live helper code.** `assignments/0033_auto_20240312.add_demos` invokes
   the live `assign_piece_plan`. If Phase 2 changes that helper's behavior/signature, a fresh
   `migrate` runs the NEW logic against the OLD schema → breaks (we already hit a variant of this
   in 1b). **Neutralize 0033 first**: freeze its behavior (inline the historical logic or guard
   the helper), so changing the helper can't rewrite history. Prerequisite for any Phase 2 helper
   change.
2. **`ActivityProgress` is `OneToOne(Assignment)` with per-student research data**
   (`audio_edit_history`, `question_responses`, `participant_email`). It cannot map onto a
   course-level row. Must become `(course_assignment, enrollment)` (Option B) or stay attached to
   the lazily-materialized `Assignment` (Option A). A wrong `on_delete` here destroys research data.
3. **`Submission.assignment` is `PROTECT`.** Can't drop old `Assignment` rows while Submissions
   reference them. Add new FK → backfill → swap → drop, in that order.
4. **Legacy `Assignment.piece IS NULL` rows** (piece nullable since migration 0026, never
   backfilled). They violate any tightened `(course, activity, piece)` uniqueness and abort the
   data migration. Audit + backfill/dedupe first.
5. **`Part.for_activity` read-time regression (Option B).** Moving part resolution to read time
   makes it per-(student×activity). Precompute a per-request `(piece, activity)→part` map; the 1c
   `.exists()` removal helped but isn't enough at read scale.
6. **Non-unique `Course.slug`/`Piece.slug`** — `.get(slug=)` can 500. Dedupe + add `unique=True`
   (slug values unchanged → no API break). Cheap; fold in.
7. **`Activity.activity_type_name`/`category` denorm columns** already drifted (migration 0037).
   Drop and repoint serializer `source` to the FK (`select_related`) — JSON field names unchanged.

## Proposed sequence (Option A)

1. ✅ **Neutralize migration 0033** (done) — `add_demos` is a no-op; fresh `migrate` green.
2. ✅ **Add `CourseAssignment` + `GroupAssignment` models** (done) — additive, unique constraints,
   factories + constraint tests.
3. ✅ **Dual-write from `assign_*`** (done) — `assign_one_piece_activity` /
   `assign_telephone_fixed` now also create `CourseAssignment` (and `GroupAssignment` per
   telephone member). Per-student `Assignment` rows still written; old read path unaffected.
4. ✅ **Backfill data migration** (done) — create `CourseAssignment` (and `GroupAssignment` for
   telephone groups) from existing `Assignment` rows, collapsing by `(course, activity, piece)`.
   Handle legacy `piece IS NULL` rows first.
5. ✅ **Add Submission fields** (done) — `course_assignment`, `enrollment`, `instrument`, `part`
   (nullable), dual-populate on create, backfill from existing `Submission.assignment`.
6. ✅ **Re-key `ActivityProgress`** (done) — add `course_assignment` + `enrollment` (unique together),
   backfill from `assignment`, keep `get_or_create` on first access.
7. 🔶 **Flip the read path** — IN PROGRESS. **Student path DONE** on `backend-remodel-phase1`:
   - `AssignmentViewSet.list` (student) resolves from `CourseAssignment` (id = `course_assignment.id`),
     precomputing per-CA part/submissions/group maps so it stays O(1) in assignment count; fixes
     late joiners and scopes telephone groups by enrollment.
   - `AssignmentViewSet.retrieve` (student) → `CourseAssignmentRetrieveSerializer` (legacy
     `AssignmentSerializer` shape).
   - Nested `submissions` + `activity-progress` routes reinterpret `{id}` as a `CourseAssignment`
     id, scope by the requesting student's enrollment, key writes by `(course_assignment, enrollment)`,
     404 on a foreign id. Late joiners can now submit/track progress (the `assignment` FK is now
     nullable — migration 0018 — and populated only when an Assignment row exists, so teacher views
     keep reading it).
   - Foundations: response-equivalence serializers + tests (`CourseAssignmentReadSerializer`,
     `CourseAssignmentRetrieveSerializer`) pin field-for-field parity except `id`; query-count test
     updated to dual-write CAs; factory fixes (unique `UserFactory.username`, date-typed
     `CourseFactory` dates).
   - **Teacher list DONE:** flipped to one row per `CourseAssignment` (A rows, not A·S). Verified the
     frontend teacher view (`components/teacher/course.js` → `getAssignedPieces`) only derives the
     distinct `(piece, activity)` set per piece and the redux consumers of this endpoint are all
     student-facing — so the cardinality collapse is contract-safe; per-student fields come back
     null/empty (read serializer handles `enrollment=None`). Teacher `retrieve` still reads per-student
     `Assignment` (single-object; not a cardinality issue) and `TeacherSubmissionViewSet.recent` still
     reads the populated `assignment` FK — both fine until step 8.

   **Step 7 COMPLETE** (student + teacher list/retrieve, submissions, activity-progress).
8. 🔶 **Contract & drop** — IN PROGRESS. **Reads + writes off Assignment DONE** (Assignment is now
   dead — neither read nor written for new data):
   - Repointed reads: `GroupSerializer.get_members` → `GroupAssignment`; `TeacherSubmissionViewSet.recent`
     + serializer → the submission's own course_assignment/enrollment/instrument/part (frontend reads
     only `assignment.enrollment.user.name` there); `ActivityViewSet` distinct-activity list → `CourseAssignment`.
   - Per-piece instrument override moved to **`CourseAssignment.instrument`** (mig 0040, nullable);
     `change_piece_instrument` sets it, `resolve_instrument` prefers it. (Restores the override the
     step-7 read flip had stopped honoring.)
   - **Stopped writing Assignment:** `assign_one_piece_activity`/`assign_telephone_fixed` create only
     `CourseAssignment` (+ `GroupAssignment`); assign endpoints return a count (frontend ignores the body).
   - **REMAINING (destructive, gated on review):** add `unique(course_assignment, enrollment)` to
     `ActivityProgress`; remove `resolve_legacy_assignment` + the `assignment=` write in
     `SubmissionViewSet.perform_create`; drop the dead `AssignmentViewSet` teacher retrieve/update/notation
     actions; drop `Submission.assignment` + `ActivityProgress.assignment` FKs; drop the `Assignment`
     model + dead serializers (`AssignmentSerializer`/`AssignmentViewSetSerializer`/`AssignmentInstrument`/
     `NotationAssignment`). Note: dropping the Assignment rows is safe (fully backfilled into
     CourseAssignment); ActivityProgress/Submission rows are NOT deleted (only their redundant FK column).

### Frontend contract surface (verified against `~/GithubOrgs/espadonne/CPR-Music`)

Per-assignment `id` from the list is consumed by exactly: `GET /assignments/{id}/` (retrieve),
`GET|POST /assignments/{id}/submissions/`, `POST .../submissions/{sid}/attachments/` (keyed by
submission pk, unaffected), and `*/activity-progress/{,log_event,submit_step,save_response,save_audio_state}`.
**There is no per-assignment `PATCH`** — instrument changes go through course-level
`PATCH /courses/{slug}/change_piece_instrument/` (by `piece_id`), which still updates `Assignment`
rows during the transition. So the student contract surface flipped in step 7 is complete.

Each step is independently shippable with query-count + response-equivalence tests, same as Phase 1.
Steps 7–8 are the contract-sensitive half — review the dual-write foundation (PR #56) first.

## Open questions (decisions needed before building)

1. **Option A vs B** — start with lazy materialization (recommended) or go straight to the fully
   dynamic model?
2. **Instrument source of truth** — when `Enrollment.instrument` ≠ `User.instrument`, which wins?
   (Current fallback prefers `Enrollment.instrument`.)
3. **`telephone_fixed`** — inherently per-student group assignment; keep a lightweight per-student
   construct, or redesign grouping? (Advisor's own open question.)
4. **Lazy materialization trigger (Option A)** — materialize on list access, or only on first
   submit? Affects whether "assigned but not started" is queryable.
5. **Scope of this effort** — is Phase 2 in scope for the current sprint, or is shipping Phase 1
   (PR #56) + the migration-0033 safety fix the right stopping point for now?
