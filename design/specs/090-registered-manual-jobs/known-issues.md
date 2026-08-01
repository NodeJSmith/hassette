# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: Trailing-period inconsistency between design doc and shipped status text

Status: resolved — trailing periods added to the CLI's 5 unpunctuated status strings (matching the frontend's existing convention), and design.md's two `legacy_unknown` quotes updated to match.
Source: impl-review
Reason not fixed now: needs-decision
Observed in: T06 (CLI), T07 (frontend), commit 87db5785 (final state)
Affected files:
- design/specs/090-registered-manual-jobs/design.md (Operator Surfaces section)
- src/hassette/cli/commands/job.py
- frontend/src/components/app-detail/job-detail.tsx (or equivalent status-text source)

Issue:
The design doc specifies trailing periods on status text ("Timing unavailable.", "Waiting for entity time.", "Schedule completed.", "Manual only."). The shipped CLI and frontend implementation (matching the task files' own unpunctuated wording) omits the period on 4 of 6 strings. The two planning documents (design.md vs. task files) disagree with each other, not just with the code — the code correctly followed the task files.

Why deferred:
Purely cosmetic, no functional impact. Resolving it requires a product decision (which punctuation convention is correct) rather than a mechanical fix, and touches both docs and shipped user-facing text.

Recommended follow-up:
Pick one convention (with vs. without trailing periods) and align design.md, the task files, and the shipped CLI/frontend text to match.

Acceptance criteria:
- design.md's Operator Surfaces section and the actual CLI/frontend status strings use the same punctuation convention.

## KI-002: Stale "heap" terminology in test naming

Status: resolved — test renamed to `test_returns_job_found_in_registry`, docstrings updated to say "registry" instead of "heap".
Source: impl-review
Reason not fixed now: out-of-scope
Observed in: T03 (registry and registration)
Affected files:
- tests/unit/core/test_scheduler_service_trigger.py

Issue:
The module docstring and the test `test_returns_job_found_on_heap` still say "heap," though this feature moved live job lookup from heap membership to the `_jobs_by_id` registry (`SchedulerService._jobs_by_id`) — the test itself correctly exercises the registry, only its name/docstring are stale.

Why deferred:
Purely a naming/documentation nit inside a test file with no behavioral consequence; out of scope for any of T01-T08's stated Target Files.

Recommended follow-up:
Rename `test_returns_job_found_on_heap` to something like `test_returns_job_found_in_registry` and update the module docstring's "heap" references to "registry" where they describe live-lookup behavior (retain "heap" only where the test genuinely describes `_ScheduledJobQueue`/due-time heap behavior).

Acceptance criteria:
- Test and docstring naming in test_scheduler_service_trigger.py accurately reflects registry- vs. heap-based behavior for each test.

## KI-003: schedule_status display-text mapping hand-maintained in two files

Status: resolved — extracted to `frontend/src/utils/schedule-status.ts` (`scheduleStatusDisplay(status, reason)`), consumed by both `handler-rows.ts` and `job-detail.tsx`.
Source: clean-code
Reason not fixed now: needs-decision
Observed in: T07 (frontend), clean-code pass at commit 56e24551 (branch base before clean-code fixes)
Affected files:
- frontend/src/utils/handler-rows.ts (`scheduleStatusLabel`)
- frontend/src/components/app-detail/job-detail.tsx (`scheduleStatusText`)

Issue:
Both files switch over the same `JobData.schedule_status` enum to produce display text, but for different consumers: `scheduleStatusLabel` returns a short single-word label used in the handler-rows list/sort (and only distinguishes the `legacy_unknown` reason), while `scheduleStatusText` returns a full punctuated sentence used in the job detail view (and additionally distinguishes the `trigger_error` reason within `completed`). The two switches are not a 1:1 duplicate — they diverge in which reason values they surface and in output shape (word vs. sentence) — so collapsing them requires designing a shared status-to-display data structure (e.g. a lookup table keyed by status+reason with both a short label and a long sentence), not a mechanical extraction.

Why deferred:
Unifying the two mappings is a design decision about the shared data shape (whether the short label and long sentence for a status genuinely belong in one table entry, and whether coupling the row-sort package to the job-detail package's sentence text is desirable) rather than an unambiguous mechanical fix. The immediate risk of leaving it alone is only maintenance drift: a new `schedule_status` or reason value requires updating both switches by hand.

Recommended follow-up:
Design a single `SCHEDULE_STATUS_DISPLAY` lookup (status + optional reason -> `{ label, text }`) in `handler-rows.ts` or a shared `schedule-status.ts` util, and have both `scheduleStatusLabel` and `scheduleStatusText` read from it.

Acceptance criteria:
- Adding a new `schedule_status` or `schedule_status_reason` value requires updating exactly one source of truth, not two independent switch statements.

## KI-004: Repeated raw-SQL test boilerplate in migration and telemetry test files

Status: open
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: T02 (migration and persistence), T04 (completion and submission); clean-code pass at commit 56e24551
Affected files:
- tests/unit/test_migration_012.py (new file added by this branch, 384 lines)
- tests/unit/test_migration_002.py
- tests/unit/test_schema_migration.py
- tests/unit/core/test_migration_runner.py
- tests/unit/core/test_telemetry_repository.py

Issue:
The `conn = sqlite3.connect(db_path); try: ...; finally: conn.close()` block is repeated 60+ times across the migration/schema test files, and a hand-typed `INSERT INTO executions (...) VALUES (...)` statement with the same column list is repeated 10+ times across `test_telemetry_repository.py`, `test_migration_012.py`, and `test_schema_migration.py`. `test_migration_012.py` is entirely new in this branch and follows the same repetitive pattern already established in its pre-existing siblings rather than introducing a shared helper.

Why deferred:
A fix requires touching many pre-existing, correctness-sensitive migration/telemetry test files (not just the new ones from this branch) to introduce and adopt a shared `sqlite_conn(db_path)` context manager and an `insert_execution_row(conn, ...)` helper. That is a cross-cutting test-infra change with real risk of subtly changing fixture teardown timing in tests that verify exact schema/migration behavior — better done as its own reviewed change than folded into this clean-code pass.

Recommended follow-up:
Add `sqlite_conn(db_path)` (context manager) and `insert_execution_row(conn, **kw)` to `src/hassette/test_utils/helpers.py` or a new `test_utils/sql_helpers.py`, then migrate the migration/schema/telemetry test files to use them.

Acceptance criteria:
- A new migration or telemetry test can open a scoped sqlite connection and insert an execution row via one shared helper call each, without hand-rolling `sqlite3.connect`/`try`/`finally` or the full `INSERT INTO executions` column list.

## KI-005: Row-coherence telemetry test duplicated across three files

Status: open
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: T04 (completion and submission); clean-code pass at commit 56e24551
Affected files:
- tests/integration/telemetry/test_global_jobs_and_service_info.py
- tests/integration/telemetry/test_health_aggregates_and_global_listeners.py
- tests/integration/telemetry/test_listener_queries.py

Issue:
The "insert two error rows at different timestamps, assert `last_error_*` fields all come from the most recent row" test (`test_last_error_row_coherence` / `test_since_filter_scopes_error_cte`) is copy-pasted near-verbatim across job and listener variants in these three files (~150 lines total), differing only in entity type (job vs. listener) and scope (global vs. per-instance). This branch added a new copy of the pattern to `test_global_jobs_and_service_info.py` (108 new lines) rather than sharing it with the pre-existing listener-side versions.

Why deferred:
Extracting a shared parametrized helper means touching pre-existing, already-passing correctness-sensitive telemetry tests in files this branch did not otherwise modify. The risk of subtly changing what each variant asserts (job vs. listener column names, global vs. scoped query behavior) outweighs the benefit of doing it inside this clean-code pass.

Recommended follow-up:
Extract a shared parametrized helper (e.g. `assert_last_error_row_coherence(query_fn, insert_fn, ...)`) that both the job and listener variants call, collapsing the ~150 duplicated lines into one parametrized implementation.

Acceptance criteria:
- The row-coherence behavior is asserted from one shared implementation, parametrized over entity type and scope, rather than four independent copies.

## KI-006: tests/integration/test_scheduler.py flaked under random test ordering

Status: resolved — root-caused and fixed. The earlier "pre-existing on main" conclusion was
wrong; this was a genuine regression introduced by T04 of this branch.

Source: clean-code (originally); root-caused during PR readiness follow-up.
Affected files:
- src/hassette/core/scheduler_service.py (fix)
- tests/unit/core/test_scheduler_service_reschedule.py (updated assertions + new coverage)

What it actually was:
The original note claimed this reproduced on an unmodified `main` baseline and was therefore
pre-existing and unrelated to spec 090. That claim was never checked against actual `main` —
it only stashed this clean-code pass's own diff, not the full branch. Re-verifying against
real `main` (`git diff`/checkout comparison, both the single file and the full 8500+-test
suite under `-n 4 --dist loadscope`) found **zero** flakiness there, even under heavier load
than the failing subset. Bisecting the branch's 8 task commits (T01-T08) against
`tests/integration/test_scheduler.py` pinned the regression to T04 ("Implement completion
retention and manual submission").

Root cause: T04 deleted `SchedulerService._remove_job()`, which used to unconditionally strip
a job from the due-time heap at the end of every dispatch. In its place, `dispatch_and_log()`
now only updates `job.schedule_status` (COMPLETED/WAITING) when a trigger is exhausted, raises,
or goes mid-recurrence-WAITING — it never removes the corresponding heap entry. Several tests
in this file legitimately schedule a job for the near future (`run_in(delay=10)`) and then
force an early fire via a direct `await scheduler_service.dispatch_and_log(job)` call, without
removing the still-pending heap entry first. That entry survives with its `next_run`/`fire_at`
wiped to `None` by the COMPLETED/WAITING transition. When the real due-time heap pops it later
(sometimes seconds into a later test, depending on random ordering), it hits
`pop_due_and_peek_next()`'s `assert candidate.fire_at is not None` and crashes the
`SchedulerService.serve()` task permanently for the rest of the test module — every subsequent
`run_in()`-scheduled job across the remaining tests in the file then times out waiting for an
event that can never fire, since nothing pops the heap anymore.

Fix: `dispatch_and_log()` now calls `await self._job_queue.remove_job(job)` whenever a job
transitions away from `SCHEDULED` (COMPLETED or WAITING), mirroring what `reschedule_job()`
already did correctly for its own WAITING/re-SCHEDULED paths. This is a no-op in the normal
case (the job was already popped off the heap by `serve()` before dispatch), and correctly
clears the stale entry in the edge case (dispatch forced early on a still heap-resident job).
Verified: 10/10 clean runs of the single file, 3/3 clean runs of the full integration suite
under `-n 4 --dist loadscope`, and a full 8500+-test suite run with zero failures.

Acceptance criteria:
- [x] `pytest tests/integration/test_scheduler.py` passes consistently across at least 10
  consecutive runs with random test ordering.
- [x] Root cause identified and fixed at the source, not papered over with longer timeouts.
