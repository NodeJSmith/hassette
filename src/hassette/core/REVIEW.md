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

## Failure Report Ordering
`Service._serve_wrapper()` in `src/hassette/resources/service.py` must call
`report_service_failure()` (in `src/hassette/core/core.py`, routed by `service_failure.py`) first at every failure exit after the
handoff, before `handle_failed()`/`handle_crash()`, which await a bounded event channel. Does any
exit (raise, `FatalError`, `ClosedResourceError`, unrequested return or cancellation) reach a status
send first, or add an `await` ahead of the report? Does anything on the path from the report to
`escalate_service_failure()` await, so a stalled bus or database could delay the process exit?

## Who Closes the Event Streams
Only `BusService` knows whether the event channel is still drained: its drain loop closes the streams
on every exit, and `Hassette._fail_startup()` asks it via `close_streams_unless_draining()`. Does new
code close the streams, or decide whether to, from the bus's status, `stop_requested()`, or another
stand-in for "is the bus draining"? Does a new direct `EventStreamService.send_event()` caller handle
`ClosedResourceError`/`BrokenResourceError` the way `Hassette.send_event()` does?

## Fatal Reason Before Shutdown
`escalate_service_failure()` in `src/hassette/core/service_failure.py` is the one fatal exit route. Does it
latch `_fatal_shutdown_reason` *before* requesting shutdown, and does any other code path request
shutdown for a service failure without going through it? A path that requests shutdown first loses
the reason, and a second route lets required and optional handling drift apart.

## Shutdown Deadlines
Shutdown deadlines are owned by operations (`src/hassette/resources/shutdown_deadline.py`): the
root's stop and foundation stages in `src/hassette/core/core.py`, and the entry deadline in
`src/hassette/core/app_lifecycle_instances.py`. Does new shutdown work bound itself only as a leaf
(its own cap clamped to the deadline), leaving interior waits unbounded and walking away to those two
owners? Does anything added to the foundation stage fit inside `FOUNDATION_SHUTDOWN_BUDGET_SECONDS`,
and does work a walk-away leaves running get recorded with `record_force_terminated()`?

## Tier Processing Parity
When a maintenance loop in `src/hassette/core/database_service.py` processes
multiple tiers or tables in sequence, does each tier get the same commit isolation,
error handling, and budget accounting? A failure in one tier that corrupts state for
the next, or an empty tier that silently consumes the deletion budget, has been a
repeated Codex finding.

## Recv-Task Detach Before Cancel
`_handle_recv_task_done` in `src/hassette/core/websocket_service.py` treats any
end of the still-attached `_recv_task`, cancellation included, as a lost
connection. Does every site that cancels the recv task on purpose (cleanup,
shutdown) set `_recv_task` to `None` first? A site that cancels while the task is
still attached turns a deliberate teardown into a spurious DISCONNECTED transition.

## Needs-Restart Flag Sourcing
`AppRegistry.resolve_instance_info()` in `src/hassette/core/app_registry.py` is the one place an
instance entry and its needs-restart record are combined; a flagged index can outlive its entry.
Does a new reader of per-instance state go through it (or `resolve_instance_infos()`) rather than
reading the instance map directly, which drops flagged indices? And does every new FAILED outcome in
`src/hassette/core/app_lifecycle_instances.py` whose `TeardownReport` is not restart-safe flag the
index before the status event is sent? Does a new path that creates an instance go through
`AppFactory.create_instances` or `_create_instance_unlocked` in `src/hassette/core/app_lifecycle_start_stop.py`,
whose `AppRegistry.refusal_for` check keeps a replacement off a flagged index?
