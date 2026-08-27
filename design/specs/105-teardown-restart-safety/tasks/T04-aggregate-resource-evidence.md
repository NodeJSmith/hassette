---
task_id: "T04"
title: "Aggregate Resource teardown evidence"
status: "planned"
depends_on: ["T03"]
implements: ["FR#1", "FR#2", "FR#3", "FR#7", "FR#10", "FR#11", "FR#17", "AC#1", "AC#3", "AC#5"]
---

## Summary

Make generic Resource shutdown collect positive evidence across hooks, TaskBucket work, cleanup, children, timeout, and
force-terminal handling. Replace boolean child compression and cleanup-owned TaskBucket cancellation with immutable
report aggregation, while preserving later stages and terminal lifecycle bookkeeping after failures.

## Target Files

- read: `design/specs/105-teardown-restart-safety/design.md`
- modify: `src/hassette/resources/base.py`
- modify: `src/hassette/resources/operations.py`
- modify: `tests/unit/resources/lifecycle/conftest.py`
- modify: `tests/unit/resources/lifecycle/test_shutdown.py`
- modify: `tests/unit/resources/lifecycle/test_force_terminal.py`
- modify: `tests/unit/resources/test_shutdown_edge_cases.py`
- modify: `tests/unit/resources/test_add_child_and_restart.py`

## Prompt

Implement the Resource portions of `Architecture → Evidence collection` and `Force-terminal and root timeout`.
Build a safe report at shutdown start, merge every stage's immutable evidence, and store only through the coordinator.
Run TaskBucket seal/cancel/final inspection as a first-class stage before subclass cleanup; base `cleanup()` must stop
owning TaskBucket cancellation. Record named hook, cleanup, initialization, TaskBucket, child, body-timeout, body-failure,
body-pending, and force-terminal causes exactly as designed. Make `_shutdown_children()` gather reports in reverse
insertion order, continue siblings after exceptions, identify affected children, force only unfinished children on a
wave timeout, and call `_on_children_stopped()` only when every child report is SAFE. Force-terminal must merge
`FORCED_TERMINAL` before cancellation or terminal bookkeeping, preserve a completed SAFE child, and never allow late
completion to erase causes. Add failing deterministic tests for each unsafe path first, then retain existing clean
restart and hook-order behavior.

## Focus

- The whole body deadline already belongs to the T03 coordinator; enclosing cancellation must not erase TaskBucket's
  final synchronous pending-name snapshot.
- Shutdown hook cancellation still propagates to the coordinator/body timeout path; ordinary handled hook exceptions
  continue to later hooks and stages.
- Child-returned UNSAFE is not an exception: merge its details and add `CHILD_RESTART_UNSAFE` with child identity.
- Child exceptions add `CHILD_SHUTDOWN_FAILED`; unfinished children add `CHILD_SHUTDOWN_TIMED_OUT` and force evidence.
- Status-event emission failure does not itself prove owned work survived and therefore does not change restart safety.
- Keep `ResourceStatus.STOPPED` possible alongside an UNSAFE report; no status enum or transition-table change.

## Verify

- [ ] FR#1: `uv run pytest tests/unit/resources/lifecycle/test_shutdown.py -q` proves every completed generic Resource shutdown returns and stores an immutable report, including repeated calls.
- [ ] FR#2: `uv run pytest tests/unit/resources/lifecycle/test_shutdown.py tests/unit/resources/test_shutdown_edge_cases.py -q` proves SAFE is returned only when every generic shutdown stage has positive completion evidence.
- [ ] FR#3: `uv run pytest tests/unit/resources/lifecycle/test_shutdown.py tests/unit/resources/test_shutdown_edge_cases.py -q` proves each generic negative path produces its named cause, operation, task, or resource detail.
- [ ] FR#7: `uv run pytest tests/unit/resources/test_add_child_and_restart.py tests/unit/resources/lifecycle/test_shutdown.py -q` proves child-driven UNSAFE teardown blocks restart, start, and direct initialize without a second hook run.
- [ ] FR#10: `uv run pytest tests/unit/resources/lifecycle/test_force_terminal.py -q` proves force-terminal stores UNSAFE evidence before cancelling work or writing STOPPED bookkeeping.
- [ ] FR#11: `uv run pytest tests/unit/resources/lifecycle/test_shutdown.py tests/unit/resources/test_shutdown_edge_cases.py -q` proves Resource shutdown seals TaskBucket before cancellation and records its final pending names even when the body is interrupted.
- [ ] FR#17: `uv run pytest tests/unit/resources/lifecycle/test_shutdown.py -q` proves late body completion can add failure evidence but cannot remove existing causes or lose exception observation.
- [ ] AC#1: `uv run pytest tests/unit/resources/lifecycle/test_shutdown.py tests/unit/resources/test_add_child_and_restart.py -q` proves child timeout adds child/force causes and prevents all three initialization paths from running a second hook.
- [ ] AC#3: `uv run pytest tests/unit/resources/test_shutdown_edge_cases.py tests/unit/resources/lifecycle/test_shutdown.py -q` proves hook failure, cleanup failure/timeout, and TaskBucket stragglers retain named evidence while later shutdown stages still run.
- [ ] AC#5: `uv run pytest tests/unit/resources/lifecycle/test_shutdown.py tests/unit/resources/lifecycle/test_force_terminal.py tests/unit/resources/test_add_child_and_restart.py -q` proves repeated report reuse, one-time SAFE consumption, and permanent force-terminal refusal.
