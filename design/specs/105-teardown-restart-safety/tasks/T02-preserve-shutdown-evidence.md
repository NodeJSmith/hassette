---
task_id: "T02"
title: "Preserve task and hook shutdown evidence"
status: "done"
depends_on: []
implements: ["FR#11"]
---

## Summary

Turn TaskBucket cancellation and shutdown-hook execution into evidence-producing primitives. Seal owner task admission
before cancellation, reject and observe late work safely, and return deterministic names for tasks that remain pending.
Return handled shutdown-hook failures instead of logging and discarding them.

## Target Files

- read: `design/specs/105-teardown-restart-safety/design.md`
- modify: `src/hassette/task_bucket/task_bucket.py`
- modify: `src/hassette/resources/mixins.py`
- modify: `src/hassette/resources/operations.py`
- modify: `tests/integration/test_task_bucket.py`
- modify: `tests/unit/resources/test_run_hooks.py`

## Prompt

Implement the evidence primitives from `Architecture → Evidence collection` and the first two replacement targets.
Add explicit sealed admission to TaskBucket, a clean reopen operation for accepted initialization, and a synchronous
deterministic pending-name snapshot. A sealed `spawn()` must close an unsubmitted coroutine when possible and raise a
bucket-identifying `RuntimeError`; a sealed task-factory `add()` must cancel the already-created task, attach exception
consumption, and raise the same error. Change `cancel_all()` to return the deterministic tuple of names still pending
after its bounded wait. Update the lifecycle TaskBucket protocol accordingly. Change `run_hooks(...,
continue_on_error=True)` to continue in order and return an immutable tuple of handled failures while preserving
raise-on-first-error initialization behavior. Write the failing task/hook regressions first, using explicit event gates
for resistant work.

## Focus

- `make_task_factory()` creates an `asyncio.Task` before calling `owner.add()`, so rejection must cancel and observe it.
- Cross-thread `spawn()` must close the coroutine on every pre-submission rejection path; do not introduce warning leaks.
- Keep existing exception-recorder FIFO behavior and ordinary task-factory tracking intact.
- Sealing is idempotent; reopening occurs only from a lifecycle admission decision in T03.
- `cancel_all_sync()` remains fire-and-forget, but force-terminal code must still be able to inspect pending names.
- Do not move lifecycle coordination into TaskBucket or put lifecycle coordinator tasks in its ownership set.

## Verify

- [ ] FR#11: `uv run pytest tests/integration/test_task_bucket.py tests/unit/resources/test_run_hooks.py -q` proves sealing precedes cancellation, both admission paths reject safely, and cancellation/final snapshots return every deterministic pending task name.
