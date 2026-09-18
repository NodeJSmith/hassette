# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: `_RetentionBatchError` uses exception-as-control-flow to carry a partial-delete count

Status: filed (#2268)
Run: 135
Source: clean-code
Reason not fixed now: behavior-change
Observed in: src/hassette/core/database_service.py:125-143 (`_RetentionBatchError`), :868-869 (raise site), :951-958 (catch site)
Affected files:
- src/hassette/core/database_service.py

Issue:
`_RetentionBatchError` exists solely to smuggle an `int` (`partial_deleted`) out of `_delete_target_batched()`'s batch loop to its one caller, `_do_run_retention_cleanup()`, which immediately unpacks `.partial_deleted`. `_delete_target_batched()` already returns a plain `tuple[int, bool]` on its non-error path, so the error path could plausibly use the same return-value shape (e.g. a sentinel or a `(deleted, exhausted, error)` tuple) instead of a custom exception class with exactly one raise site and one catch site.

Why deferred:
This is flagged as a training-bias pattern (llm-checker), not a confirmed defect — the exception carries real information (partial progress before a mid-batch failure) that must propagate past a `raise ... from exc` chain to preserve the original traceback for `logger.exception()`. Reshaping this into a return-value convention touches the retry/rollback/logging flow across `_delete_target_batched()`, `_do_run_retention_cleanup()`, and their extensive test coverage (per-target failure isolation, partial-progress reporting) — exactly the kind of "could change behavior in subtle ways" restructuring this orchestration run should not attempt inline with an unrelated clean-code pass.

Recommended follow-up:
If revisited, evaluate replacing `_RetentionBatchError` with a plain return-value carrying `(total_deleted, exhausted, error | None)`, preserving the original exception via `exc.__cause__`-equivalent handling if `logger.exception()` still needs traceback info without an active `except` frame.

Acceptance criteria:
- Either the exception-based control flow is kept with a documented rationale, or replaced by a return-value convention with equivalent partial-progress reporting and equivalent traceback visibility in `Retention cleanup failed for %s` log lines, verified by the existing `test_per_target_failure_isolation` and `test_parent_guard_skipped_when_target_failed` tests still passing unmodified in behavior.

## KI-002: Tier-filter WHERE-clause construction is duplicated (with different shapes) between `_delete_target_batched()` and `_check_size_failsafe()`

Status: open
Run: 135
Source: clean-code
Reason not fixed now: behavior-change
Observed in: src/hassette/core/database_service.py:850-855 (`_delete_target_batched`), :1074-1079 (`_check_size_failsafe`)
Affected files:
- src/hassette/core/database_service.py

Issue:
Both methods independently implement "conditionally add a `source_tier = ?` filter" for the same `RetentionTarget.source_tier` field, but with different string-assembly styles and different surrounding query shapes: `_delete_target_batched()` builds `"source_tier = ? AND {timestamp_col} < ?"` (age-cutoff delete), while `_check_size_failsafe()` builds `"WHERE source_tier = ? "` spliced before `ORDER BY ... LIMIT ?` (oldest-N delete, no age cutoff). Two checkers (lazy-checker, nitpicker) both flagged this as duplicated "same conditional, same column, two different assembly styles" logic that a shared helper could consolidate.

Why deferred:
The two call sites solve genuinely different query problems (age-based cutoff vs. oldest-N-by-tier), not the same one twice — a shared helper would need to return just the tier-filter fragment and let each caller splice it differently, which is more indirection than the four extra lines it would save. More importantly, the design doc for this feature explicitly documents a prior subquery-scoping bug in exactly this SQL ("the tier filter must NOT go on the outer DELETE — that would select globally-oldest rows then discard non-matching ones") and AC#4 exists specifically to pin this correctness property. Touching this shared construction to deduplicate style risks reintroducing that class of bug for a stylistic win, which is out of proportion for a clean-code pass on an already-tested, already-shipped-in-this-PR piece of SQL.

Recommended follow-up:
If a third call site needing tier filtering appears, extract a small `_tier_filter(target) -> tuple[str, list[Any]]` helper at that point and re-verify both existing call sites against `test_size_failsafe_*` and the tier-aware retention tests before merging.

Acceptance criteria:
- A future change either introduces a shared helper with full re-verification against `AC#4`'s subquery-scoping test, or explicitly re-confirms (in code review) that consolidating the two call sites is not worth the risk.

## KI-003: Near-identical single-line test setup (`make_failing_execute`, `_insert_log_records`) repeated across 3+ tests in `test_log_records_retention.py`

Status: open
Run: 135
Source: clean-code
Reason not fixed now: needs-decision
Observed in: tests/unit/core/test_log_records_retention.py — `db.execute = make_failing_execute(db, "DELETE FROM blocking_events")` (2 occurrences, now wrapped across lines by this run's clean-code fix) and `_insert_log_records([make_log_record_row(1, now - 10, "log")])` (2 occurrences, also fixed for line length this run; nitpicker also cites a third occurrence in a related exhaustion-warning test)
Affected files:
- tests/unit/core/test_log_records_retention.py

Issue:
The same one-line setup statement (forcing `db.execute` to fail on a specific SQL substring, or inserting a single throwaway log record) is repeated verbatim across multiple independent test functions rather than factored into a shared fixture/parametrized helper.

Why deferred:
This directory's own `CLAUDE.md` documents an explicit, accepted convention (`# dup-ignore-start: pytest test function signature`) for tolerating repeated setup across independent test functions, on the grounds that Python has no clean way to share a function signature between tests and `tools/check_duplicate_code.py` would otherwise flag normal test structure. Whether these specific one-liners cross the line from "acceptable per-test setup" to "should be a shared helper" is a judgment call about test-fixture design this run should not make unilaterally mid-clean-code-pass — restructuring test setup risks subtly changing what each test actually exercises.

Recommended follow-up:
If a 4th or 5th near-identical setup line accumulates in this file, extract a small helper (e.g. `patch_failing_delete(db, table_fragment)` as a context manager) following the existing `make_failing_execute()` factory pattern already in this file.

Acceptance criteria:
- Either a shared helper is introduced and all call sites migrated with tests still passing unmodified in behavior, or a reviewer confirms the current level of duplication is within this directory's documented tolerance.
