# REVIEW.md — core/

## Dependency Ordering
Does the `wire_services()` construction order in `src/hassette/core/core.py` stay
consistent with the `depends_on` declarations across all children? A new child
appended before its dependency is constructed will fail the topological sort at
startup.

## Bootstrap Latch Semantics
`AppBootstrapCoordinator` in `src/hassette/core/app_bootstrap_coordinator.py` opens
a one-time latch that never re-closes. Does every caller of `is_released()` or
`wait_released()` account for the case where bootstrap released in a previous
connection generation but `src/hassette/core/state_proxy.py` has since marked the
cache `STALE`?

## Fatal Shutdown Recording
Does every fatal-outcome path in `src/hassette/core/service_watcher.py`
(`handle_restart_refused`, `handle_exhaustion`, `shutdown_if_crashed`, the
fatal-error check in `restart_service`) record `fatal_shutdown_reason` *before*
calling `request_shutdown()`? A path that requests shutdown first loses the
reason.

## Shutdown Wave Budget
`_shutdown_children()` in `src/hassette/core/core.py` divides the remaining deadline
across dependency waves via `children_budget_remaining()` in
`src/hassette/resources/lifecycle.py`. Does the division account for time already
consumed by earlier waves, or could early waves eating their floor allocation starve
the final wave (which holds `DatabaseService` and `SyncExecutorService`)?

## Tier Processing Parity
When a maintenance loop in `src/hassette/core/database_service.py` processes
multiple tiers or tables in sequence, does each tier get the same commit isolation,
error handling, and budget accounting? A failure in one tier that corrupts state for
the next, or an empty tier that silently consumes the deletion budget, has been a
repeated Codex finding.

## Bus Recovery Reconciliation
After `BusService` restarts, `reconcile_after_bus_recovery()` in
`src/hassette/core/service_watcher.py` scans for FAILED services with no budget
entry. Does it also cover services that failed *and were restarted* during the blind
window but now have an incorrect budget entry?
