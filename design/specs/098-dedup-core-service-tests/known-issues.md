# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: Inconsistent naming for newly-extracted "perform + return" test helpers across the 4 task groups

Status: open
Run: 90
Source: cross-file-review
Reason not fixed now: out-of-scope
Observed in: T01, T03 (WIP commits 7ec3588a, 016a2683)
Affected files:
- tests/unit/core/test_command_executor.py (`run_execute`)
- tests/unit/core/test_command_executor_pipeline.py (`run_serve_until`, `wire_raising_persist`)
- tests/unit/core/test_command_executor_execution_id.py (`execute_handler_and_get_record`)
- tests/unit/core/test_scheduler_service_reschedule.py (`dispatch_with_trigger`)
- tests/unit/core/test_scheduler_service_timeout.py (`get_executed_cmd`)

Issue:
The `make_*`-prefixed object-builder helpers extracted in this branch (`make_result_mock`, `make_executor_with_send_event`) follow the established `make_*`/`create_*`/`build_*` factory convention from `.claude/rules/test-conventions.md`/`tests/TESTING.md`. But the complementary category — helpers that perform an operation and return/assert on the result — used five different naming shapes across the four independently-executed task groups: `run_*` (twice), a bare verb phrase with no prefix, `wire_*`, `dispatch_with_*`, and `get_*`. Two different shapes even appear within the same task group (T01).

Why deferred:
Standardizing this naming would require touching files across all four already-shipped WIP commits, which is beyond issue #1616's scope (resolve PMD-flagged duplicate clusters). Not a correctness issue — all helpers work correctly and have live call sites.

Recommended follow-up:
If this "perform + return" helper category grows further, standardize on one verb-first prefix (e.g. `run_*`, since `run_execute`/`run_serve_until` already establish precedent) distinct from `make_*`/`get_*` builders/accessors. Consider a follow-up rename pass across the 5 helpers listed above.

Acceptance criteria:
- All "perform + return" test helpers in `tests/unit/core/` share one consistent naming prefix.

## KI-002: bus_service group left the "assert dispatched command type" idiom inline while scheduler_service extracted it

Status: open
Run: 90
Source: cross-file-review
Reason not fixed now: out-of-scope
Observed in: T02, T03 (WIP commits 293191ee, 016a2683)
Affected files:
- tests/unit/core/test_bus_service_error_handler.py
- tests/unit/core/test_bus_service_timeout.py
- tests/unit/core/test_scheduler_service_timeout.py (has the extracted `get_executed_cmd` helper for comparison)

Issue:
`test_scheduler_service_timeout.py` extracted a `get_executed_cmd(svc)` helper wrapping `cmd = svc._executor.execute.call_args[0][0]; assert isinstance(cmd, ExecuteJob); return cmd`, reused across 3 files (8 call sites). The structurally identical idiom for `InvokeHandler` (BusService's parallel dispatch layer) remains repeated inline 8 times across `test_bus_service_error_handler.py` and `test_bus_service_timeout.py`. Not flagged by PMD (the bare 2-line idiom is below PMD CPD's token-length minimum), so it was never a required fix under FR#1/FR#2 for either task, but it's a divergence: the next scheduler_service test author has a local precedent to imitate; the next bus_service test author does not.

Why deferred:
Both BusService and SchedulerService are intentionally-parallel command-dispatch layers per design.md's Approach section (see the `TestBusErrorHandlerInvocation`/`TestSchedulerErrorHandlerInvocation` mirror-class rationale) — this is stylistic consistency between sibling groups, not a functional defect, and touching `test_bus_service_*.py` again is outside T02's already-shipped, already-reviewed scope.

Recommended follow-up:
Add an equivalent `get_executed_invoke_handler_cmd(executor)` helper to `test_bus_service_error_handler.py`/`test_bus_service_timeout.py` for consistency with the scheduler_service group's pattern, if this file group is touched again.

Acceptance criteria:
- `test_bus_service_error_handler.py` and `test_bus_service_timeout.py` use a shared helper for the "assert dispatched command type" idiom, matching scheduler_service's pattern.

## KI-003: Repeated near-verbatim `dup-ignore-start` rationale prose across many files

Status: resolved — fixed during known issues walkthrough
Run: 90
Source: clean-code
Observed in: T01, T02, T03 (WIP commits 7ec3588a, 293191ee, 016a2683)

Issue:
The `# dup-ignore-start: <reason>` / `# dup-ignore-end` marker pairs are mechanically required by `tools/check_duplicate_code.py`, but the multi-line justification prose accompanying them is hand-authored and repeated near-verbatim across several call sites and files in this branch.

Resolution:
Audited all 4 flagged locations individually rather than treating the prose duplication as one uniform issue:
- `tests/unit/core/test_bus_service_error_handler.py`, `test_bus_service_timeout.py`, `tests/unit/bus/test_invocation.py` — verified valid: the duplication is genuinely cross-layer (`build_tracked_invoke_fn` behavior verified once at the Bus layer, once at the BusService layer, by design). Left as-is.
- `tests/unit/core/test_command_executor_pipeline.py:642-733` (serve-loop executor/recorder setup) — verified valid: one of the three occurrences needs a bespoke re-enqueue branch that a shared factory can't cleanly absorb. Left as-is.
- `tests/unit/core/test_command_executor_pipeline.py:350-425` (InvokeHandler test-double construction) — **not** valid: three near-identical in-file constructions with no bespoke variation, dup-ignored instead of extracted. Fixed by extracting a local `make_real_invoke_handler_cmd(*, listener_id=5, source_tier="app")` helper (named to match the repo's `make_real_*()` convention for a real, fully-constructed instance — see `make_real_job()` — and distinct from the shared `make_invoke_handler_cmd()` factory in `test_utils/factories.py`, which returns a `MagicMock` rather than a real `InvokeHandler`) and removing the three `dup-ignore` blocks. Reviewed via a single-pass `code-reviewer` dispatch (PASS, 2 LOW naming nitpicks, both addressed).
