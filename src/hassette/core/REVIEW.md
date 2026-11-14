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
and does a walk-away force-terminate what it leaves running, so its shutdown outcome is `INCOMPLETE`
and its ERROR names it? (`hassette run`'s exit check in `src/hassette/server.py` sees what is still
alive at exit; nothing records walked-away work for it.)

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

## Connection State Has One Writer
`WebsocketService.set_connection_state` in `src/hassette/core/websocket_service.py` is the only
writer of `_connection_state` under `src/` after `__init__`; it latches ever-connected, clears the
connected event and generation, and checks the edge against `WS_VALID_TRANSITIONS`. Does new code
(including `src/hassette/testing/`) assign `_connection_state` directly, skipping all three? And
does a new state or edge land in `WS_VALID_TRANSITIONS` and the test table `ALLOWED_TRANSITIONS`
together?

## App Status Writes and the Needs-Restart Flag
`AppRegistry.set_status()` in `src/hassette/core/app_registry.py` is the only writer of app instance status,
and lifecycle code reaches it only through `AppInstanceLifecycleMixin.set_app_status()`, which writes and sends
the event in one call. Does a new status write go through `set_app_status()` rather than calling
`registry.set_status()` directly (whose returned change would then go unsent)? The needs-restart flag lives on
the FAILED entry and is set by the FAILED write itself (`needs_restart=`); its `StatusChange` and
`HassetteAppStateEvent` carry it. Does a consumer of app status events read the flag from the event rather than
the registry, which may already hold a later write? Does every new FAILED outcome in
`src/hassette/core/app_lifecycle_instances.py` whose `ShutdownOutcome` is not restart-safe pass the flag on that
write (`fail_needs_restart()`)? Does a new path that creates an instance go through
`AppFactory.create_instances` or `_create_instance_unlocked` in `src/hassette/core/app_lifecycle_start_stop.py`,
whose `AppRegistry.refusal_reason` check keeps a replacement off a flagged name? That gate covers `(app_key, name)` only: a renamed instance
or a name moved to another app passes it by design (see the `refusal_reason` docstring).

## Debug-Capture State Sourcing
`AppRegistry` holds per-instance debug capture; `App.debug_capture` is a mirror that level resolution reads.
Does a new toggle or writer go through `AppHandler.set_debug_capture` (registry first, then the live instance)
rather than setting the attribute directly? Does every new path that removes an app or an instance name from
the config reach `prune_stale_debug_capture` or `clear_debug_capture`, so no pair is left that no route or
status read can see?

A capture pair is name-keyed intent, so it isn't pruned on every exit path, but an instance's logger levels must be
reset when it leaves. Does a new path that removes a live instance's entry go through `shutdown_instance`, whose `finally`
returns a departing captured instance's loggers to config, rather than writing its STOPPED or FAILED status on its own? Discarding
a failure entry, which holds no live instance, is the exception.
