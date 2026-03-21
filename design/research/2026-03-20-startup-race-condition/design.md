# Design: Eliminate Startup Race Conditions

**Date**: 2026-03-20
**Status**: Approved (post-challenge round 2)
**Inputs**: research.md, critique.md

## Problem

Every Hassette startup drops 50+ handler invocation records and logs warnings because:
1. `session_id=0` — handlers fire before `SessionManager.create_session()` runs
2. `listener_id=0` — internal handlers (ServiceWatcher, StateProxy) have no `db_id` because they skip DB registration

## Architecture

Two independent, minimal fixes:

### Fix 1: Phased startup (eliminates session_id=0)

Change `run_forever()` in `core.py` to start DatabaseService first, wait for it, create the session, then start all remaining services.

```
Current:
  _start_resources()          # starts ALL children
  ready_event.set()
  wait_for_ready(db)          # partial fix from earlier attempt
  create_session()
  wait_for_ready(all)

New:
  database_service.start()    # start DB only
  wait_for_ready(db)
  mark_orphaned_sessions()
  create_session()            # session exists before anything else starts
  _start_remaining()          # start everything except DB
  ready_event.set()
  wait_for_ready(all)
```

Key invariant: by the time any service can fire a handler, the session already exists.

Files: `src/hassette/core/core.py` (run_forever, _start_resources)

### Fix 2: Direct dispatch for internal handlers (eliminates listener_id=0)

In `BusService._dispatch()`, when `listener.db_id is None`, invoke the handler directly without going through `CommandExecutor.execute()`. No `InvokeHandler` command, no telemetry record.

```python
async def _dispatch(self, topic, event, listener):
    if listener.db_id is None:
        # Internal handler — invoke directly, no telemetry record
        try:
            await listener.invoke(event)
        except Exception:
            self.logger.exception("Internal handler error (topic=%s, handler=%r)", topic, listener)
        finally:
            if listener.once:
                self.remove_listener(listener)
        return
    cmd = InvokeHandler(listener=listener, event=event, topic=topic, listener_id=listener.db_id)
    await self._executor.execute(cmd)
    if listener.once:
        self.remove_listener(listener)
```

Internal handlers are framework plumbing (ServiceWatcher log events, StateProxy state cache updates). They fire at high volume and their telemetry would pollute the app-focused dashboard metrics.

Error handling: the direct dispatch path wraps `invoke()` in try/except with structured logging (topic + handler). The `finally` block ensures `once` listeners are removed even on error. This matches the error isolation of `CommandExecutor._execute_handler()` without creating telemetry records.

Files: `src/hassette/core/bus_service.py` (_dispatch)

### Fix 2b: Direct dispatch for internal scheduled jobs

Apply the same pattern in `SchedulerService._dispatch_and_log()` for jobs with `db_id is None`.

Files: `src/hassette/core/scheduler_service.py` (_dispatch_and_log)

### Cleanup

Remove the drop-and-warn filter in `_do_persist_batch()` — with both fixes in place, `session_id=0` and `listener_id=0` records should never reach the persist layer. Convert the filter to an assertion-level guard (log error + drop, not warning) to catch future regressions.

Remove the `_safe_session_id()` fallback to 0 — the session always exists when handlers fire. Keep the method but have it raise if session is missing (bug, not expected).

Files: `src/hassette/core/command_executor.py` (_do_persist_batch, _safe_session_id)

## Test Plan

1. **Phased startup**: Update `test_run_forever_starts_and_shuts_down` — verify `wait_for_ready` is called for DB before other services start. Verify `create_session` is called before `_start_remaining`.
2. **Direct dispatch**: New test — internal listener (no app_key) dispatches without going through CommandExecutor. Verify no `InvokeHandler` command is created.
3. **Integration**: Verify no "Dropping" warnings in logs during full startup (existing smoke test).

## Alternatives Considered

- **Option A (session_id backfill)**: Rejected — adds permanent complexity to persist hot path, re-enqueue creates busy-wait loop, shutdown path loses records (critique findings #1, #2)
- **Option C (register internal listeners in DB)**: Rejected — creates ServiceWatcher bootstrap deadlock, pollutes UI data model (critique findings #1, #3)

## Implementation Order

All changes ship in a single PR. The cleanup (removing `_safe_session_id` fallback, upgrading drop filter severity) is only safe when both Fix 1 and Fix 2 are in place. Deploy atomically.

## Risks

- Phased startup adds DB init latency before other services start. Mitigated: SQLite init + session INSERT is milliseconds.
- Internal handler errors no longer recorded in telemetry DB. Acceptable: structured logging in `_dispatch()` provides equivalent context (topic, handler repr, traceback).

## Challenge Round 2 Findings (Addressed)

- **Error isolation** (HIGH, Senior+Adversarial): Added try/except/finally in direct dispatch path with structured logging.
- **SchedulerService coverage** (HIGH, Architect+Adversarial): Added Fix 2b for internal scheduled jobs.
- **`once` listener removal bug** (MEDIUM, Adversarial): Used `finally` block for removal.
- **Implementation ordering** (MEDIUM, Senior+Adversarial): Specified single-PR atomic deployment.
