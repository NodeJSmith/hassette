# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: Trailing-period inconsistency between design doc and shipped status text

Status: open
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

Status: open
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

Status: open
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

## KI-006: tests/integration/test_scheduler.py has pre-existing test-order-dependent flakiness

Status: open
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code pass test-suite verification at commit 56e24551 (pre-existing on main, not introduced by this branch)
Affected files:
- tests/integration/test_scheduler.py

Issue:
Running `uv run nox -s dev` (or `pytest tests/integration/test_scheduler.py` with `pytest-randomly`'s default random ordering) intermittently fails 2-5 tests in this file with `TimeoutError` — observed on `test_run_job_calls_executor`, `test_run_job_non_app_routes_through_executor`, `test_run_in_passes_args_kwargs_sync`, `test_run_in_passes_args_kwargs_async`, and `test_jobs_execute_in_run_order`, in varying combinations across runs. Confirmed pre-existing and unrelated to this clean-code pass's edits: stashing all clean-code changes and re-running the full file with a fixed `--randomly-seed` reproduces the identical failure set on the unmodified baseline. Running the same tests in isolation (via `-k`) always passes; the failures only appear when the full file (or the full suite via `-n 4 --dist loadscope`) runs many scheduler integration tests back to back, suggesting real-timer/asyncio contention under load rather than a logic bug in any single test.

Why deferred:
This is a pre-existing test-reliability issue orthogonal to spec 090's scope and to this clean-code pass — root-causing timer/asyncio contention across a 24-test integration file is a debugging task, not a stylistic fix, and touching this file's timing assumptions carries real risk of masking a genuine race instead of fixing test isolation.

Recommended follow-up:
Investigate whether these tests share mutable state (e.g. a module-scoped mock executor, as flagged in this same clean-code pass for the save/restore-mock-attributes pattern) or whether they need longer/more robust waits (`wait_for()` helper instead of bare `asyncio.wait_for(..., timeout=1)`) to tolerate scheduler contention when many real-timer tests run consecutively in one process.

Acceptance criteria:
- `pytest tests/integration/test_scheduler.py` passes consistently across at least 10 consecutive runs with random test ordering (`pytest-randomly` default, no fixed seed).
