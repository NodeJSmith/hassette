# REVIEW.md — resources/

## Lifecycle Reentry Coverage
`reject_lifecycle_reentry()` in `src/hassette/resources/lifecycle.py` checks
`current_task` against `_init_task`, `_shutdown_task`, and `_shutdown_body_task`.
Does this catch a lifecycle hook that spawns a new task (via `task_bucket.spawn()`)
which then calls back into `initialize()` or `shutdown()` on the same resource?
That spawn runs in a different task, so the direct task check would miss it.

## Force-Terminal Outcome Storage
`_force_terminal()` in `src/hassette/resources/base.py` stores a shutdown outcome
before cancelling `_shutdown_task`. The coordinator cannot store
an outcome before the shutdown work that produces it. Does `_force_terminal()`
always store its outcome before issuing the cancellation, and does the
coordinator merge against that outcome rather than assuming it owns all storage?

## Shutdown Outcome Merge Order
`merge_outcomes()` in `src/hassette/resources/shutdown_outcome.py` keeps the worst
result and the first reason recorded at it, so it is intentionally non-commutative.
Does a new merge site pass the outcome whose reason should win first (a stored
outcome before later evidence, children in shutdown order), and does every
producer of a non-`DONE` result give it a reason naming the resource and step?

## Terminal-State Guard Completeness
`handle_failed()` in `src/hassette/resources/lifecycle.py` silently returns when
the resource's status is already in `TERMINAL_STATUSES` from
`src/hassette/types/enums.py` (just `STOPPED`). Can a status write reach a service
before `handle_failed()` records FAILED (for example a `handle_stop()` from a path
that doesn't check `ended_unrequested()`), so the guard swallows the failure and the
service ends STOPPED instead of FAILED?

## Implicit Task Creation After the Seal
At exit the root's TaskBucket is sealed and is the loop's task-factory fallback, so
a task created through the loop with no bucket in context is rejected (see
`create_lifecycle_task()` in `src/hassette/resources/lifecycle.py`). Does code that
runs in a shutdown hook or a root exit stage call `asyncio.gather()` on bare
coroutines, or `asyncio.wait_for()` (which wraps its awaitable in a task on Python
3.11), instead of `create_lifecycle_task()` and `asyncio.timeout()`?
