# Backend Remodel Campaign

> Directive file guiding the CPR-Music-Backend query/model remodel.
> Derived from a 6-dimension fan-out audit (65 findings, 45 confirmed remediable:
> 37 Phase-1 safe, 7 Phase-2 structural) and the advisor's plan in
> [`remodel_assignments.md`](./remodel_assignments.md).

## Decisions locked in

- **Sequencing:** phased. Ship Phase 1 (safe, no-migration query wins) first; the
  advisor's structural `CourseAssignment` remodel is Phase 2, gated behind Phase 1.
- **API contract:** the assignment/submission JSON response shapes stay **identical**.
  Per-student fields get resolved server-side so the frontend
  (`~/GithubOrgs/espadonne/CPR-Music`) needs no changes.
- **Working style:** tests first-class (query-count + response-equivalence), one
  endpoint/fix per commit, CI green before merge.

## The two cost classes

1. **Write-explosion** — one teacher "assign" click fans out across the roster.
   `assign_one_piece_activity` runs `update_or_create` per student per activity
   (`courses/helper.py:23-42`): ~`2·A·S` queries / `A·S` rows per POST, `P·A·S` for a
   curriculum, none wrapped in `transaction.atomic`. (A = activities, S = students,
   P = piece plans.)
2. **Read N+1** — teacher list/grading endpoints serialize deep nested trees over
   unoptimized querysets. Worst offender: `GroupSerializer.get_members` re-queries
   membership per assignment → O(M²) per group.

**Biggest single win:** the `AssignmentViewSet.list` teacher read path — three
compounding N+1s collapse to a bounded handful with pure queryset/memoization
changes, no migration, no API change.

---

## PHASE 1 — Safe quick wins (no migration, no API change)

Each item ships as its own commit with an `assertNumQueries` test proving the count
is **constant** w.r.t. roster/group size (parametrize S = 1, 5, 30). Capture a
response-equivalence snapshot of every touched endpoint *before* editing.

> **Progress (branch `backend-remodel-phase1`, 11 commits):** all of 1a landed EXCEPT
> #13 (held — behavior change). Done: #1–#4, #6–#12, #14, plus 1c #22/#25 and 1d indexes
> (#26 + attachment), each with query-count tests (`teleband/*/tests/test_query_counts.py`).
> Verified teeth: teacher list 484→const, grouped 1009→const (O(M²)), grading `recent`
> 501→const, CSV export 9000+→2. Remaining 1a: #13, #21, #23, #24. Then 1b (write side).
> Note: repo has 16 PRE-EXISTING black-dirty files on main (`black . --check` already
> fails repo-wide under black 24.4.2) — separate cleanup, not this PR.

### 1a — Pure queryset / serializer (zero schema risk)

- [x] **#1 `GroupSerializer.get_members`** (`assignments/api/serializers.py:42-54`) —
  O(M²)/group. Memoize members per `group.id` in serializer `context` (compute once
  per request); replace `submissions.count()` with prefetched `bool(len(...))` /
  annotated `has_submission`. Drop the inner re-query.
- [x] **#2 `AssignmentViewSet.get_queryset`** (`assignments/api/views.py:82-109`) —
  factor a shared base queryset; add to **both** student & teacher branches:
  `select_related("part","part__piece","part__piece__composer")` +
  `prefetch_related("submissions","submissions__attachments",
  "part__transpositions__transposition","part__instrument_samples")`.
  (Does **not** fix #1 — that's separate.)
- [x] **#3 `PartSerializer` tree** (`musics/api/serializers.py:60-74`) — resolved by
  #2's prefetch (`part__piece__composer`, `part__transpositions__transposition`,
  `part__instrument_samples`).
- [x] **#4 `TeacherSubmissionViewSet.recent`** (`submissions/api/views.py:80-102`) —
  add `select_related("grade","self_grade",
  "assignment__activity__activity_type__category","assignment__instrument",
  "assignment__part__piece__composer","assignment__enrollment__user",
  "assignment__enrollment__course__owner")` +
  `prefetch_related("attachments","assignment__submissions__attachments",
  "assignment__part__transpositions__transposition")`. Long-term: a slim serializer
  that doesn't re-embed `assignment.submissions[]`.
- [x] **#6 `EnrollmentViewSet.list`** (`courses/api/views.py:103-113`) —
  `select_related("course__owner","instrument__transposition","role","user")` +
  `prefetch_related("course__owner__groups","user__groups")`.
- [x] **#7 `CourseViewSet.roster` GET** (`courses/api/views.py:249-253`) —
  `select_related("user","instrument__transposition","role")` +
  `prefetch_related("user__groups")`.
- [x] **#8 `PiecePlanViewSet`** (`assignments/api/views.py:163-173`) —
  `select_related("piece__composer")` +
  `prefetch_related("activities__activity_type__category","activities__part_type")`.
- [x] **#9 `ActivityViewSet`** (`assignments/api/views.py:36-50`) —
  `select_related("activity_type","activity_type__category","part_type")`.
- [x] **#10 `GradeViewSet`** (`submissions/api/views.py:109-114`) —
  `prefetch_related("student_submission","own_submission")`.
- [x] **#11 `dashboards/views.py:55` (`csv_view`)** — reverse relations are misused
  with `select_related` → full-table N+1; `submissions.all()` evaluated twice.
  Use `prefetch_related("submissions","submissions__attachments")`; guard nullable
  `assn.piece_plan` before `.id`.
- [x] **#12 `dashboards/views.py:19` (`AssignmentListView`)** — split forward FKs into
  `select_related`, reverse/m2m into `prefetch_related`; add `paginate_by`.
  (Superuser-only, low blast radius.)
- [ ] **#13 `UserViewSet.get_queryset`** (`users/api/views.py:64`) — list-comprehension
  N+1 over `Enrollment…course`, **and** hardcodes `username="admin"` (scoping bug).
  Replace with one `.filter(enrollment__course__enrollment__user=request.user,
  enrollment__course__enrollment__role__name="Teacher").distinct()` — fixes N+1 **and**
  the bug.
- [x] **#14 permission/view duplicate point lookups** (`utils/permissions.py:21`,
  `assignments/api/views.py:70,83-84`) — resolve course/enrollment once per request
  (cache on `request`), reuse role; `select_related("role","course")`.

### 1b — Write batching + transactions (correctness first, then batch)

> Add the `transaction.atomic` wrapper **first** (correctness), then `bulk_create`/
> `.update()`. `bulk_create` verified safe: no custom `Assignment.save()`, no
> pre/post_save signals, Postgres returns populated PKs.

- [ ] **#15 `assign_one_piece_activity`** (`courses/helper.py:23-42`, view
  `courses/api/views.py:343`) — prefetch existing `(activity,enrollment,piece)` keys
  in one query, `bulk_create(missing, ignore_conflicts=True)` (~A INSERTs);
  `select_related("user","instrument")` on the Enrollment loop; wrap view in
  `transaction.atomic`.
- [ ] **#16 `assign_curriculum`** (`courses/helper.py:117-126`, view `:387`) —
  `bulk_create` across all plans (~P·A INSERTs); wrap in `transaction.atomic`.
- [ ] **#17 `change_piece_instrument`** (`courses/api/views.py:461-464`) — replace the
  `save()` loop with
  `Assignment.objects.filter(piece=piece, enrollment__course=course)
  .update(instrument=instrument)` → 1 UPDATE.
- [ ] **#18 `assign_telephone_fixed`** (`courses/helper.py:67-114`) — hoist
  `Part.for_activity` into an activity-keyed dict (A lookups); build objects in
  memory, `bulk_create` after creating groups.
- [ ] **#19 roster POST** (`courses/api/views.py:174-229`) — `filter(username__in=…)`
  for existence; `Enrollment.objects.bulk_create(ignore_conflicts=True)` after one
  `filter(user__in=…)` prefetch; resolve collisions in memory; wrap in transaction.
  (`create_user` can't bulk — password hashing.)
- [ ] **#20 `update_or_create` lookup wider than constraint** (`courses/helper.py:29-37`
  vs `assignments/models.py:102-106`) — make lookup keys exactly
  `(activity, enrollment, piece)`, move the rest into `defaults=`; stop swallowing
  `IntegrityError` silently.

### 1c — Cheap cleanups

- [ ] **#21** `courses/helper.py:68,100` — hoist
  `activities = list(piece_plan.activities.all())` before the group loop.
- [x] **#22** `musics/models.py:65-76` (`Part.for_activity`) — cache the
  `PartType.objects.get(name="Melody")` lookup; drop the redundant `.exists()` before
  `.get()`. **Prerequisite for Phase 2** (the plan moves this call to read time).
- [ ] **#23** `assignments/api/views.py:123-135` — annotate the queryset with a
  correlated `Subquery` on `PlannedActivity.order` instead of rebuilding a Python dict
  per request.
- [ ] **#24** `assignments/api/views.py:126` — add explicit `.order_by()` (the
  `Meta.ordering` spanning `piece_plan__name` forces an unused sort).
- [x] **#25** `assignments/models.py:57-73` (`PiecePlan.assign`) — delete (confirmed
  zero callers; a trap if reused).

### 1d — Additive index migrations (non-breaking; see Open Q #6)

- [x] **#26** `submissions/models.py:38` — composite index `(assignment, submitted DESC)`
  for latest-per-assignment (`submissions/api/views.py:80-94`).
- [ ] `submissions/models.py:53-56` — index for `SubmissionAttachment.Meta.ordering`
  `(submission, submitted)`, or drop the implicit ordering.

---

## PHASE 2 — Structural remodel (needs migration)

Implements the advisor's `CourseAssignment` plan: one row per `(course, activity, piece)`
instead of per-enrollment; move `instrument`/`part` to `Submission`; resolve a student's
assignments dynamically at read time (late joiners handled for free); **preserve the
response shape**.

### What the advisor's plan covers
- Write fan-out `A·S → A` (root of #15/#16) — directly solved.
- `instrument` denormalized per-row → moved to `Submission`.
- Nullable `piece` in the unique constraint → `CourseAssignment` uses non-null `piece`.
- `Submission` FK repoint + backfill.

### What the plan MISSES (our findings to fold in)
1. **`Part.for_activity` read-time regression** (`musics/models.py:65-76`) — plan §4
   relocates this 2-3-query, magic-string lookup to read time *per (student × activity)*,
   converting a write cost into a per-request N+1. Land #22 first; precompute a
   per-request `(piece, activity)→part` map before going live with dynamic resolution.
2. **`ActivityProgress` OneToOne CASCADE** (`submissions/models.py:65-67`) — per-student
   research data (`audio_edit_history`, `question_responses`, `participant_email`).
   Cannot map onto a course-level row; must become FK to `CourseAssignment` + `enrollment`,
   or a wrong CASCADE deletes it. **Must be in the migration plan.**
3. **`Activity.activity_type_name` / `category` denormalized columns**
   (`assignments/models.py:35-40`) — shadow `ActivityType.name`/`category.name`, read live
   (`serializers.py:49,95-100`), and have **already drifted** (migration 0037). Drop the
   columns, repoint serializer `source` to the FK with `select_related` — JSON field names
   unchanged, so **not** an API break.
4. **`PlannedActivity.order` not denormalized** (`models.py:117-126`) — denormalize onto
   `CourseAssignment` to kill the read-time reassembly join (#23). Decide during the remodel.
5. **Instrument source of truth** — `e.instrument if e.instrument else e.user.instrument`
   (`courses/helper.py:32,107`). Pin which upstream wins before backfill (Open Q #1).
6. **Non-unique `Course.slug` / `Piece.slug`** (`courses/models.py:12`, `musics/models.py:31`)
   — looked up via `.get(slug=…)` → `MultipleObjectsReturned` 500 if a dup lands; racy
   TOCTOU in `utils/fields.py`. Dedupe existing, add `unique=True`. Slug values unchanged →
   no API break. Orthogonal but cheap to fold in.
7. **`SubmissionAttachment` ordering without index** — covered by 1d.
8. **Tighten `CourseAssignment` uniqueness explicitly** — `piece NOT NULL`; **audit
   pre-2023 `Assignment` rows with `piece IS NULL`** (nullable since migration 0026, never
   backfilled) — they violate tightened uniqueness and abort the migration.

### Migration order (PROTECT-safe)
`CourseAssignment` model → data migration (dedupe `Assignment`; repoint `Submission` +
`ActivityProgress`; backfill `instrument`/`part`) → serializer/view rewrite (shape-preserving)
→ drop `Activity` denorm columns + add slug uniqueness + attachment index → remove `Assignment`.

---

## API-contract constraints (must preserve)

- **`TeacherSubmission` recent** (`teacher_serializers.py:7-27`): `id`, `content`,
  `attachments[]{file, submitted}`, `assignment{part.piece.name,
  activity.activity_type.category, enrollment.user.name}`, `grade{rhythm, tone, expression}`.
- **Student `SubmissionSerializer`**: `submissions[]{id, submitted, content,
  attachments[]{file, submitted}}`.
- **Assignment list grouped-by-`piece_slug` dict** + the flat denormalized keys on
  `AssignmentViewSetSerializer`.
- `part.transpositions` score-selection chain, `RosterSerializer`, `CourseSerializer`
  (`can_edit_instruments`,`id`,`slug`,`name`), Grade write contract.

**Possibly droppable (needs a frontend grep first — do not drop blind):**
`UserSerializer.groups/external_id/grade/url` (prefer prefetch over removal),
`self_grade`, `group`/`GroupSerializer`, the heavy assign-endpoint response body
(frontend appears to use only HTTP status — unverified in this checkout).

---

## Testing strategy

- **Query-count assertions** (`assertNumQueries`) on every 1a endpoint —
  assert constant w.r.t. S ∈ {1, 5, 30}: `AssignmentViewSet.list` (teacher+student),
  `TeacherSubmissionViewSet.recent`, `EnrollmentViewSet.list`, `roster`, `PiecePlanViewSet`,
  `ActivityViewSet`, `csv_view`.
- **Write-count assertions** on assign / assign_curriculum / change_piece_instrument /
  roster — assert O(A)/O(1), not O(A·S).
- **Atomicity** — force a mid-loop failure on assign; assert no partial rows.
- **Response-equivalence snapshots** — capture current JSON for every load-bearing
  endpoint before changes; assert key-set equality after each commit and across the
  Phase 2 serializer rewrite.
- **Re-assign idempotency** (#20) — assign same piece twice with changed deadline; assert
  every student updates, no swallowed `IntegrityError`.
- **Phase 2 migration tests** — seed legacy `piece IS NULL` + duplicate-slug rows;
  assert `ActivityProgress` research data survives; assert late-joiner resolves all
  course assignments.

---

## Open questions (Phase 2 blockers in **bold**)

1. **Instrument source of truth:** when `Enrollment.instrument` ≠ `User.instrument`, which
   wins as the Submission default? (Current fallback prefers `Enrollment.instrument`.)
2. **`telephone_fixed` under `CourseAssignment`:** keep a lightweight per-student/group
   model for grouped activities, or redesign grouping? (Advisor's own open question.)
3. **Read-time `Submission` creation:** on first access vs. lazily on submit? Affects
   whether "assigned but not started" is queryable + submission-count badge semantics.
4. Confirm against the frontend repo that the assign-endpoint response body is unused
   before slimming it.
5. Drop vs. keep `self_grade`/`group`/`external_id`/`grade` — frontend grep first, or keep
   and rely on prefetch?
6. Index-as-migration policy: treat additive/non-breaking indexes (#26) as Phase 1, or
   batch into the Phase 2 migration?
