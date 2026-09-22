# REVIEW.md — resources/

## Lifecycle Reentry Coverage
`reject_lifecycle_reentry()` in `src/hassette/resources/lifecycle.py` checks
`current_task` against `_init_task`, `_shutdown_task`, and `_shutdown_body_task`.
Does this catch a lifecycle hook that spawns a new task (via `task_bucket.spawn()`)
which then calls back into `initialize()` or `shutdown()` on the same resource?
That spawn runs in a different task, so the direct task check would miss it.

## Force-Terminal Report Storage
`_force_terminal()` in `src/hassette/resources/base.py` stores a teardown report
(lines 379-385) before cancelling `_shutdown_task`. The coordinator cannot store
a report before the shutdown work that produces it. Does `_force_terminal()`
always store its report before issuing the cancellation, and does the
coordinator merge against that report rather than assuming it owns all storage?

## Teardown Report Merge Idempotency
`merge_teardown_reports()` in `src/hassette/resources/teardown.py` deduplicates
causes while preserving first-seen order — it is idempotent but intentionally
non-commutative. Does a double-merge from `_run_post_hook_shutdown_stage()` and
`_run_shutdown_coordinator()` produce duplicate `TeardownCause` entries, or does
deduplication keep each cause to one occurrence?

## Terminal-State Guard Completeness
`handle_failed()` in `src/hassette/resources/lifecycle.py` silently returns when
the resource's status is already in `TERMINAL_STATUSES` from
`src/hassette/types/enums.py`. Does `TERMINAL_STATUSES` include every status where
a late failure should be dropped (`STOPPED`, `EXHAUSTED_DEAD`), or could a resource
in `EXHAUSTED_COOLING` swallow a failure that should trigger a different outcome?
