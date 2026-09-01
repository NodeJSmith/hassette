# Context: Scope restart-refusal escalation to the failing service instead of the whole process

## Problem & Motivation

`ServiceWatcher.handle_restart_refused()` escalates every `RestartRefusedError` to a root-wide process shutdown, even when the recorded `TeardownCause`s are just timeout overruns (`CLEANUP_TIMED_OUT`, `TASKS_PENDING`, `SERVE_TASK_PENDING`, `SHUTDOWN_BODY_TIMED_OUT`) rather than a genuine failure. On a resource-constrained home-automation host this can trip routinely, taking down every unrelated service and app in the process for what may just be momentary CPU/network pressure.

## Key Decisions

1. Classify a `TeardownReport` as "timeout-only" when every recorded cause is one of the four timeout causes above — anything else (a hook raising, `CHILD_RESTART_UNSAFE`, `FORCED_TERMINAL`, etc.) is a real failure and keeps escalating immediately, unchanged.
2. A resource's actual current quiescence (task bucket empty, shutdown-body task done) can be checked *after* the report was generated, since tracked tasks self-remove from the bucket the moment they actually finish. This lets us confirm — rather than assume — that nothing from the failed teardown is still running before treating it as safe to leave alone.
3. For services with `restart_spec.degrade_on_confirmed_quiescent_refusal` set to `True` (the default for `TRANSIENT`/`TEMPORARY` services), wait up to half of `resource_shutdown_timeout_seconds` for confirmed quiescence — half, not the full value, since the full timeout already governed the original teardown attempt and reusing it would double time-to-escalation for a genuinely-stuck resource. If confirmed, mark just that one service `EXHAUSTED_DEAD` (existing terminal status, existing telemetry/UI support) instead of shutting down the whole process. If not confirmed in time, fall back to today's unchanged root-shutdown behavior.
4. `PERMANENT`-restart-type services (`BusService`, `SchedulerService`, `SyncExecutorService`) are excluded from the new degrade path entirely via `RestartSpec.degrade_on_confirmed_quiescent_refusal=False` — they already treat exhaustion as needing full process replacement, and degrading one of them alone would leave the rest of the framework "running" while doing nothing useful. `WebsocketService` gets the same exclusion despite being `TRANSIENT`, not `PERMANENT` — it's the framework's sole connection to Home Assistant, and the identical "leaves everything else uselessly running" argument applies to it.
5. Full self-healing (automatically reconstructing and reinitializing the affected service) is explicitly out of scope — filed separately as issue #1767 — because it requires a generic per-service factory mechanism the framework doesn't have today. This fix only narrows *when* root shutdown fires; it never attempts an in-process restart of the confirmed-dead service.

## Constraints

- Do not attempt to reconstruct, re-initialize, or retry the affected resource object in any way — `TeardownReport` is cached once and immutable, and there is no in-process reset path for a restart-unsafe report. Any code that tries to call `initialize()` again on the same object, or to `add_child()` a replacement, is out of scope (see issue #1767).
- Do not change behavior for non-timeout-only causes or for services with `degrade_on_confirmed_quiescent_refusal=False` (`PERMANENT`-restart-type services, and `WebsocketService`) — those must continue to escalate to root shutdown exactly as today.
- Do not grow `tests/integration/test_service_watcher.py` further — it is already past the 800-line ceiling and tracked for a split in issue #1721. New integration tests go in a new file, `tests/integration/test_service_watcher_refusal_scoping.py`.
- Use `shutdown_safe_sleep()` for the confirmation-wait polling loop, not a bare `asyncio.sleep()` — it already exists on `ServiceWatcher` and aborts early if shutdown is requested mid-wait.
- Follow the deterministic event-gated test pattern from `CLAUDE.md`'s "Regression test patterns for this project" — signal task completion via an `asyncio.Event` the test controls, never `asyncio.sleep(0)` or a real-time race.
