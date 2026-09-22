# REVIEW.md — resources/

## Lifecycle Reentry Coverage
`reject_lifecycle_reentry()` in `src/hassette/resources/lifecycle.py` checks
`current_task` against `_init_task`, `_shutdown_task`, and `_shutdown_body_task`.
Does this catch a lifecycle hook that spawns a new task (via `task_bucket.spawn()`)
which then calls back into `initialize()` or `shutdown()` on the same resource?
That spawn runs in a different task, so the direct task check would miss it.

## Shutdown Coordinator and Report Integrity
When `_force_terminal()` in `src/hassette/resources/base.py` cancels
`_shutdown_task`, the cancellation is absorbed only if `_teardown_report` was
already stored. Does every path through `_run_shutdown_coordinator()` in
`src/hassette/resources/lifecycle.py` store its report *before* any suspension
point where `_force_terminal()`'s cancellation could land?

## Teardown Report Merge Ordering
`merge_teardown_reports()` in `src/hassette/resources/teardown.py` is called from
both `_run_post_hook_shutdown_stage()` and `_run_shutdown_coordinator()`. When
`_force_terminal()` stores a report concurrently, is the merge commutative and
idempotent — can `TeardownCause.FORCED_TERMINAL` appear twice if both paths
record it independently?

## Terminal-State Guard Completeness
`handle_failed()` in `src/hassette/resources/lifecycle.py` silently returns when
the resource's status is already in `TERMINAL_STATUSES` from
`src/hassette/types/enums.py`. Does `TERMINAL_STATUSES` include every status where
a late failure should be dropped (`STOPPED`, `EXHAUSTED_DEAD`), or could a resource
in `EXHAUSTED_COOLING` swallow a failure that should trigger a different outcome?
