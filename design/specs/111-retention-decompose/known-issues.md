# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: database_service.py exceeds the repo's 800-line file-size ceiling

Status: open
Run: 138
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code review of branch `111-retention-decompose` (commit range 53d605a7...HEAD)
Affected files:
- src/hassette/core/database_service.py

Issue:
The file is well over the 800-line max in `coding-style.md` (1060 lines as of this walkthrough's
last fix, up from ~1044 lines when this entry was first recorded — exact counts drift as sibling
known-issue fixes land in this same file, so treat "well over 800" as the durable fact, not the
specific number). This diff added the `_run_failsafe_tier` method plus two module-level delete
helpers (~120 net lines) without a corresponding split, growing an already-oversized file
further.

Why deferred:
Splitting the size-failsafe machinery (or the retention-cleanup machinery) into its own module
is a structural decomposition, not a mechanical clean-code fix — it changes import paths and
requires re-verifying every call site, which is architecture-track work (see
`.claude/rules/clean-code-findings.md`'s topic:code-quality vs topic:architecture distinction),
not something to bolt onto this task's scope.

Recommended follow-up:
File a `topic:architecture` issue (Architecture milestone) proposing a decomposition of
`database_service.py` — a natural split is retention/failsafe delete machinery
(`RetentionTarget`, `_execute_target_delete`, `_execute_failsafe_delete`, `_run_failsafe_tier`,
`_do_run_retention_cleanup`, `_check_size_failsafe`) into its own module, leaving connection
lifecycle, write-queue, and heartbeat management in `database_service.py`.

Acceptance criteria:
- `database_service.py` is at or under 800 lines after the split
- Extracted module has its own focused test file(s) rather than growing the existing ones further

## KI-002: `_run_failsafe_tier` is long (~109 lines) and nests four levels deep

Status: resolved — fixed during known issues walkthrough (nesting only; length left as-is per
user judgment — the ~109-line length wasn't the concern, the 4-level nesting was)
Run: 138
Source: clean-code
Reason not fixed now: behavior-change
Observed in: clean-code review of branch `111-retention-decompose` (commit range 53d605a7...HEAD)
Affected files:
- src/hassette/core/database_service.py

Issue:
`_run_failsafe_tier` (lines 855-961) is well over the 50-line function guideline in
`coding-style.md`, and its worst branch nests four levels (`for iteration` -> `for attempt in
range(...)` -> `try` -> `if attempt == 0: ... else: ...`).

Why deferred:
This method was just extracted and hardened with two-layer error handling and a bounded vacuum
retry in this same PR (T02 + the ship-time challenge fixes). Splitting it further right after
writing it risks reintroducing the exact control-flow bugs the pinned tests
(`test_run_failsafe_tier_*`) were added to guard against, without a fresh characterization pass —
`refactoring-discipline.md` requires pinning behavior before restructuring, and the pins here were
written for the current shape, not a further-decomposed one.

Recommended follow-up:
Once this PR has been live for a cycle, consider extracting the per-target delete loop and/or the
bounded vacuum-retry loop into their own small helper methods, each independently unit-testable,
re-running the existing `_run_failsafe_tier` tests as the pin.

Acceptance criteria:
- `_run_failsafe_tier` (or its replacement orchestration method) is under ~50 lines
- Nesting in the extracted method is at most 3 levels
- All existing `_run_failsafe_tier` tests continue to pass against the new shape

## KI-003: `_do_run_retention_cleanup` remains a long, mixed-concern method after extraction

Status: open
Run: 138
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code review of branch `111-retention-decompose` (commit range 53d605a7...HEAD)
Affected files:
- src/hassette/core/database_service.py

Issue:
`_do_run_retention_cleanup` (lines 773-844) is ~72 lines even after this diff extracted
`_execute_target_delete()` out of its per-target loop. The surrounding method still mixes BEGIN,
the per-target loop, two hand-written parent-guard DELETE queries, commit, two summary-logging
blocks, and rollback-with-nested-except handling at the same level.

Why deferred:
Most of this method's structure predates this diff (design.md explicitly scopes out touching the
parent-guard deletes — see design.md's Non-Goals). This diff only improved it (extracted the
per-target delete, hardened rollback handling); further decomposition of the pre-existing
structure is out of this task's approved scope.

Recommended follow-up:
Consider extracting the parent-guard deletes (listeners/scheduled_jobs NOT EXISTS queries) into
their own helper method with a pinned characterization test, as a follow-up task explicitly scoped
to touch that code (design.md's current Non-Goals list excludes it from this task).

Acceptance criteria:
- `_do_run_retention_cleanup` is under ~50 lines
- A characterization test pins the parent-guard delete behavior before any extraction

## KI-004: Duplicate log-record dict literals across `test_log_records.py`'s pre-existing helpers

Status: resolved — fixed during known issues walkthrough (added `make_log_record_dict()` to
`tests/support/factories.py` and migrated all cited call sites plus two more for consistency)
Run: 138
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code review of branch `111-retention-decompose` (commit range 53d605a7...HEAD)
Affected files:
- tests/unit/core/test_log_records.py

Issue:
The same 13-key log-record dict shape is hand-built inline across several pre-existing tests and
helpers (`test_insert_writes_records`, `test_insert_stores_all_fields`,
`test_insert_framework_record_null_app_key`, `seed_log_records`,
`TestGetLogRecordsByExecution.seed_for_execution`) rather than through a shared factory. This
diff's own two new rollback tests were deduplicated against each other via a local
`_make_rollback_test_record()` helper, but the pre-existing instances elsewhere in the file were
left untouched since they predate this diff and touching them isn't part of this task's approved
scope.

Why deferred:
None of the cited pre-existing duplication sites were touched by this diff; deduplicating them
would mean editing test functions this PR was never scoped to change (design.md: "no
modifications to existing test assertions").

Recommended follow-up:
Add a shared `make_log_record_dict(**overrides)` factory to `tests/support/factories.py` (or a
`tests/support/web_telemetry_helpers.py`-style dedicated module) and migrate the cited call sites
to use it, per `test-conventions.md`'s factory-sharing convention.

Acceptance criteria:
- A single shared factory produces the 13-key log-record dict shape
- The cited pre-existing call sites are migrated to use it with no change in test behavior

## KI-005: FK-seed block duplicated across three integration tests

Status: resolved — fixed during known issues walkthrough (added `seed_listener_for_fk()` to
`tests/support/helpers.py` and migrated all three cited call sites)
Run: 138
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code review of branch `111-retention-decompose` (commit range 53d605a7...HEAD)
Affected files:
- tests/integration/database/test_database_service.py

Issue:
The same 6-line `INSERT INTO listeners (...)` FK-seed block appears verbatim in
`test_retention_cleanup`, `test_size_failsafe_logs_warning_on_consecutive_triggers` (both
pre-existing), and this diff's new `test_run_failsafe_tier_isolates_per_target_delete_failures`,
which reproduces the same pre-existing convention rather than introducing a new pattern.

Why deferred:
A meaningful dedup requires factoring a shared `seed_listener_for_fk(db, ...)` helper and
migrating the two pre-existing call sites too — those tests were not otherwise touched by this
diff, and design.md scopes this task to "no modifications to existing test assertions."

Recommended follow-up:
Add a `seed_listener_for_fk(db, **overrides)` helper (mirroring the existing `seed_log_records`
pattern in this test suite) and migrate all three call sites, including the two pre-existing ones.

Acceptance criteria:
- A single shared helper seeds the FK listener row
- All three cited call sites use it with no change in test behavior
