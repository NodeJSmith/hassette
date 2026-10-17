# REVIEW.md — core/

## Constructor-Injection Ordering
`wire_services()` in `src/hassette/core/core.py` constructs all children before
`topological_sort()` determines init order, so `depends_on` ordering is handled
automatically. But some children receive constructor-injected instances (e.g.
`executor=self._command_executor`). When a new child is added that takes an
injected instance, is that instance constructed before the child that receives it?

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
triggering shutdown (via `request_shutdown()` or `hassette.shutdown()`)? A path
that triggers shutdown first loses the reason.

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

## Restart Episode Ownership
`execute_restart()` in `src/hassette/core/service_watcher.py` holds a service's
`_restarting` key for its whole restart episode, and `restart_service()` drops
FAILED events for services no longer in FAILED. Does every path that retries,
exhausts, or changes a supervised service's status keep the key held until the
service has left FAILED, so a FAILED event delivered during an `await` cannot
start a second episode or run `handle_exhaustion()` twice?

## Bus Recovery Reconciliation
After `BusService` restarts, `reconcile_after_bus_recovery()` in
`src/hassette/core/service_watcher.py` scans for FAILED services with no budget
entry. Does it also cover services that failed *and were restarted* during the blind
window but now have an incorrect budget entry?

## Recv-Task Detach Before Cancel
`_handle_recv_task_done` in `src/hassette/core/websocket_service.py` treats any
end of the still-attached `_recv_task`, cancellation included, as a lost
connection. Does every site that cancels the recv task on purpose (cleanup,
shutdown) set `_recv_task` to `None` first? A site that cancels while the task is
still attached turns a deliberate teardown into a spurious DISCONNECTED transition.
