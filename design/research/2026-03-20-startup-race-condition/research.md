# Research Brief: Eliminate Startup Race Conditions Causing Dropped Invocation Records

**Date**: 2026-03-20
**Status**: Ready for Decision
**Proposal**: Eliminate all dropped handler invocation and job execution records during startup, ensuring every handler fire is accurately persisted to the database with valid `listener_id` and `session_id` values.
**Initiated by**: Investigation of "Dropping N handler invocation record(s) with listener_id=0 or session_id=0" warnings during every startup.

## Context

### What prompted this

Every Hassette startup produces warnings about dropped telemetry records. These represent real handler invocations that executed but whose records are silently discarded because they carry sentinel values (0) for foreign keys (`listener_id`, `session_id`) that would violate database constraints. The user wants both clean logs AND complete data -- every handler invocation should be recorded in the database.

### Current state

The system has two telemetry recording tables with FK constraints:

- `handler_invocations` requires valid `listener_id -> listeners(id)` and `session_id -> sessions(id)`
- `job_executions` requires valid `job_id -> scheduled_jobs(id)` and `session_id -> sessions(id)`

A partial fix already exists on this worktree branch: `BusService._register_then_add_route()` and `SchedulerService._register_then_enqueue()` now await DB registration before adding routes/enqueuing, ensuring app-owned listeners and jobs have valid `db_id` before they can fire. This eliminates `listener_id=0` for **app-owned** handlers.

However, two categories of dropped records remain:

1. **Internal/system listeners** (empty `app_key`) never go through `_register_then_add_route()` and therefore never get a `db_id`, producing `listener_id=0` on every invocation
2. **`session_id=0`** for ALL handler invocations during the startup window before `SessionManager.create_session()` completes

### Key constraints

- FK constraints are enforced (`PRAGMA foreign_keys = ON`) -- records with id=0 cannot be inserted
- `HandlerInvocationRecord` and `JobExecutionRecord` are frozen dataclasses -- `session_id` is baked in at fire time, not at persist time
- The DB write queue uses batch inserts via `executemany` -- individual record patching at persist time would require restructuring the batch path
- Internal listeners (ServiceWatcher, StateProxy, etc.) are legitimate telemetry targets -- their invocations should be tracked

## Detailed Findings

### 1. Full Event Flow

The complete path from event arrival to record persistence:

```
HA WebSocket event arrives
  -> WebsocketService._raw_recv() -> _dispatch() -> _dispatch_hass_event()
  -> hassette.send_event() -> EventStreamService._send_stream.send()
  -> BusService.serve() receives from stream
  -> BusService.dispatch() -> _expand_topics() -> match listeners
  -> For each matching listener:
       task_bucket.spawn(BusService._dispatch())
         -> Create InvokeHandler command (listener_id = listener.db_id or 0)
         -> CommandExecutor.execute() -> _execute_handler()
           -> listener.invoke(event)        [actual handler runs]
           -> Create HandlerInvocationRecord(
                listener_id=cmd.listener_id,     # from InvokeHandler, set at dispatch time
                session_id=self._safe_session_id()  # resolved at fire time
              )
           -> self._write_queue.put_nowait(record)
  -> CommandExecutor.serve() drains queue
  -> _drain_and_persist() -> _persist_batch() -> _do_persist_batch()
    -> Filter out records with listener_id=0 or session_id=0  [DATA LOSS]
    -> executemany INSERT into handler_invocations
```

**Critical observation**: Both `listener_id` and `session_id` are captured at **fire time**, not at **persist time**. The frozen dataclass prevents later modification.

### 2. Write Queue Mechanics

- `CommandExecutor._write_queue` is an unbounded `asyncio.Queue[HandlerInvocationRecord | JobExecutionRecord]`
- `serve()` starts draining immediately after `mark_ready()` -- which happens at the top of `serve()` before any data is dequeued
- `CommandExecutor.on_initialize()` only waits for `DatabaseService` to be ready, NOT for session creation
- Records accumulate in the queue as soon as handlers fire
- Batching: drains up to 100 items per cycle via `_drain_and_persist()`
- On shutdown: `_flush_queue()` drains all remaining items

**Timeline issue**: `CommandExecutor.serve()` starts draining the queue before the session exists. Records with `session_id=0` flow through immediately and get dropped in `_do_persist_batch()`.

### 3. Startup Ordering (Exact Sequence)

```
run_forever():
  1. _start_resources()                    # calls .start() on ALL children
     -> Each child spawns initialize() as a task
     -> EventStreamService marks ready immediately (streams created in __init__)
     -> DatabaseService.on_initialize() runs migrations, opens DB
     -> SessionManager.on_initialize() marks ready immediately (no-op)
     -> CommandExecutor.on_initialize() waits for DB ready
     -> BusService.before_initialize() waits for hassette.ready_event
     -> WebsocketService.serve() connects to HA, authenticates
     -> ServiceWatcher.on_initialize() registers internal bus listeners  <--- EARLY LISTENERS
     -> FileWatcherService starts
     -> WebUiWatcherService starts
     -> AppHandler.on_initialize() waits for WebSocket ready
     -> SchedulerService.before_initialize() waits for hassette.ready_event
     -> StateProxy.on_initialize() waits for WS+API+Bus+Scheduler ready

  2. ready_event.set()                     # unblocks BusService and SchedulerService

  3. wait_for_ready(database_service)       # wait for DB
  4. session_manager.mark_orphaned_sessions()
  5. session_manager.create_session()       # SESSION NOW EXISTS

  6. wait_for_ready(all children)           # wait for everything

  ...
  (After all services ready):
  7. AppHandler.after_initialize() -> bootstrap_apps()
     -> Apps register their bus listeners via _register_then_add_route()
```

**The race window**:

Between step 1 (resources start) and step 5 (session created), any handler that fires will get `session_id=0`. Key events in this window:

- **Resource lifecycle events**: Every `handle_starting()`, `handle_running()` call sends a `HassetteServiceEvent` through the bus. With ~15+ resources starting, this produces ~30+ events.
- **WebSocket connection**: Once WebsocketService authenticates (step 1), it sends `WEBSOCKET_CONNECTED` and subscribes to HA events. State change events start streaming immediately.
- **ServiceWatcher handlers**: Registered during `on_initialize()` (step 1), these fire on every service status event.
- **StateProxy handlers**: Once it subscribes (after step 2), every state_changed event triggers `_on_state_change`.

### 4. Who Fires Before Session?

Two categories of handlers fire during the pre-session window:

**Internal/system handlers (listener_id=0 AND session_id=0)**:
- `ServiceWatcher.restart_service` -- fires on FAILED service events
- `ServiceWatcher.shutdown_if_crashed` -- fires on CRASHED events
- `ServiceWatcher.log_service_event` -- fires on ALL service status events (~30+ during startup)
- `ServiceWatcher._on_service_running` -- fires on RUNNING events
- `StateProxy._on_state_change` -- fires on every state_changed event from HA
- `StateProxy.on_reconnect` -- fires on WEBSOCKET_CONNECTED
- `StateProxy.on_disconnect` -- fires on WEBSOCKET_DISCONNECTED

These handlers have `app_key=""`, so `BusService.add_listener()` takes the direct path (line 92) that skips DB registration entirely. They NEVER get a `db_id`.

**App-owned handlers (session_id=0 only)**:
- App handlers registered during `bootstrap_apps()` (step 7). With the `_register_then_add_route` fix, these get valid `listener_id` values. But if any events arrive between route-add and session creation, records get `session_id=0`.
- In practice, by the time apps are bootstrapped (step 7), the session already exists (step 5), so app handlers mostly avoid the session_id=0 race. The primary source of session_id=0 is internal handlers.

### 5. Source Analysis Summary

| Source | listener_id | session_id | Volume | Notes |
|--------|-------------|------------|--------|-------|
| ServiceWatcher handlers | 0 (no db_id) | 0 (pre-session) | ~30-50/startup | Fires on every resource status transition |
| StateProxy handlers | 0 (no db_id) | 0 (pre-session) | Varies | Depends on HA state change rate |
| App handlers (pre-session) | Valid (post-fix) | 0 (pre-session) | Low | Mostly avoided since apps start after session |
| Session crash handler | 0 (no db_id) | Valid | Rare | `_bus.on_hassette_service_crashed` in core.py line 314 |

### 6. Edge Cases

- **Session creation failure**: `run_forever()` catches the exception, logs it, and calls `shutdown()`. Records already in the queue would be flushed with `session_id=0` and dropped.
- **Shutdown-time handlers**: During `before_shutdown()`, `_bus.remove_all_listeners()` runs before `finalize_session()`. Handlers that fire during shutdown teardown would have a valid session_id since the session exists by then.
- **Orphan session marking**: `mark_orphaned_sessions()` runs before `create_session()`, so it operates on prior sessions, not the current one. No interaction with the race.

## Options Evaluated

### Option A: Backfill session_id at persist time (replace 0 with current session_id)

**How it works**: Instead of dropping records with `session_id=0` in `_do_persist_batch()`, replace the sentinel with the current `self._safe_session_id()` value. If the session still does not exist at persist time, buffer the records back into the queue (or a side buffer) and retry on the next drain cycle.

This works because the `_write_queue` is drained by `serve()`, which runs continuously. By the time the queue is drained after startup settles, the session will exist. Records queued during the pre-session window will have `session_id=0` baked in, but the persist layer can substitute the real value.

For `listener_id=0` (internal handlers), this approach alone does NOT help -- the listener was never registered in the DB, so there is no valid ID to substitute. This option must be combined with Option C or D for complete coverage.

**Implementation**: Change `_do_persist_batch()` to:
1. Check current session_id via `_safe_session_id()`
2. If still 0, re-enqueue all records and return (they will be retried next cycle)
3. If valid, create new record objects replacing `session_id=0` with the real value
4. Filter only `listener_id=0` / `job_id=0` records (which are a separate problem)

**Pros**:
- Minimal changes -- only `_do_persist_batch()` needs modification
- No changes to the startup sequence or event routing
- Records accumulate naturally in the queue; no data loss window
- Works even if session creation is slow

**Cons**:
- Frozen dataclass means you must create new record objects (not a mutation, but extra allocations)
- Does not solve `listener_id=0` for internal handlers
- Records get a slightly misleading `session_id` -- they ran before the session existed, but are attributed to it

**Effort estimate**: Small

**Dependencies**: None

### Option B: Gate the write queue drain until session exists

**How it works**: Modify `CommandExecutor.on_initialize()` or `serve()` to not start draining until a session exists. The queue buffers records in memory. Once the session is created, draining begins and all records get the valid session_id.

Two sub-approaches:
- **B1**: `CommandExecutor.on_initialize()` waits for `SessionManager` to have a valid session_id (requires a new ready signal or event)
- **B2**: `serve()` checks `_safe_session_id() != 0` before calling `_drain_and_persist()`; if 0, skip the drain and wait for next cycle

**Pros**:
- Clean separation -- records only flow to DB when session is valid
- No record modification needed

**Cons**:
- B1 creates a dependency cycle risk: CommandExecutor waits for session, but session creation uses DatabaseService which CommandExecutor also depends on. Needs careful ordering.
- B2 is simpler but has a polling delay -- records sit in memory until the next drain cycle after session creation
- Neither sub-approach solves `listener_id=0` for internal handlers
- If session creation fails, records accumulate forever in memory (memory leak risk, though shutdown flushes them)

**Effort estimate**: Small (B2) to Medium (B1)

**Dependencies**: None (B2) or new signaling mechanism (B1)

### Option C: Register internal listeners in the DB

**How it works**: Extend `BusService.add_listener()` to register ALL listeners in the DB, not just app-owned ones. Currently the `if listener.app_key:` guard on line 88 skips DB registration for internal listeners. Remove this guard so that ServiceWatcher, StateProxy, and other internal handlers get `db_id` values.

This requires deciding on a `app_key` convention for internal listeners. Options:
- Use `"__hassette__"` or similar sentinel as the app_key
- Add a new column to distinguish internal vs app listeners
- Use the `owner_id` (e.g., `"Hassette.ServiceWatcher"`) as the app_key

**Pros**:
- Completely eliminates `listener_id=0` -- every listener gets a DB row
- Internal handler telemetry becomes queryable (useful for debugging/monitoring)
- Consistent data model -- no special cases

**Cons**:
- Increases DB rows for listeners table (adds ~10-20 internal listeners)
- Changes the semantics of the `listeners` table (previously app-only)
- `ListenerRegistration` requires `app_key` -- need to synthesize one for internal handlers
- All internal listeners would go through `_register_then_add_route()`, adding latency to internal subscription setup during startup. This could delay ServiceWatcher becoming active, though the DB is already ready by then.

**Effort estimate**: Medium

**Dependencies**: None (but requires a DB convention decision)

### Option D: Treat internal handlers as "non-telemetry" -- skip recording entirely

**How it works**: Instead of trying to record invocations for internal handlers, explicitly opt them out of telemetry. In `BusService._dispatch()`, if `listener.db_id is None`, skip creating the `InvokeHandler` command and invoke the handler directly (bypassing `CommandExecutor.execute()`).

**Pros**:
- Eliminates `listener_id=0` records at the source
- No DB schema changes
- Reduces write queue volume (fewer records to persist)
- Clean conceptual model: internal handlers are framework plumbing, not user-visible telemetry

**Cons**:
- Loses visibility into internal handler performance/errors
- Two code paths for handler invocation (executor vs direct) -- divergence risk
- If a user later wants to debug internal handler performance, the data is not there
- Error handling for internal handlers would need its own path

**Effort estimate**: Small-Medium

**Dependencies**: None

### Option E: Startup reordering -- create session before starting services that fire events

**How it works**: Move session creation earlier in `run_forever()`:
1. Start DatabaseService only
2. Wait for it to be ready
3. Create session
4. Start all remaining services

This ensures the session exists before any handler can fire.

**Pros**:
- Eliminates `session_id=0` at the root cause
- No record modification or backfilling needed
- Clean startup sequence

**Cons**:
- Requires restructuring `_start_resources()` into phased startup
- DatabaseService is currently started alongside everything else; extracting it requires careful ordering
- Does NOT solve `listener_id=0` for internal handlers
- Adds startup latency (DB must be fully ready before anything else starts)
- The current `_start_resources()` loop starts all children in one pass; splitting it changes the fundamental startup contract

**Effort estimate**: Medium-Large

**Dependencies**: None

### Option F: Deferred session_id resolution (lazy FK)

**How it works**: Instead of capturing `session_id` as an `int` at fire time, store a callable or reference that resolves to the actual session_id at persist time. The `HandlerInvocationRecord` and `JobExecutionRecord` would store either `int` or a `Callable[[], int]`, and `_do_persist_batch()` would resolve it.

**Pros**:
- Records always get the correct session_id
- No startup reordering needed

**Cons**:
- Breaks the frozen dataclass contract (need mutable or a resolve step)
- Adds complexity to the record types -- they become "pending" objects
- Type safety degradation -- the field is no longer a plain int
- Every persist call must handle resolution failure
- Does NOT solve `listener_id=0`

**Effort estimate**: Medium

**Dependencies**: None

## Recommended Approach: Option A + C Combined

The two remaining race conditions have distinct root causes requiring distinct fixes:

### For session_id=0: Option A (backfill at persist time)

This is the simplest, lowest-risk fix. When `_do_persist_batch()` encounters records with `session_id=0`:
1. Get the current session_id via `_safe_session_id()`
2. If still 0 (session not yet created), re-enqueue the records and return
3. If valid, create new frozen dataclass instances with the real session_id substituted
4. Proceed with normal persistence

This is safe because:
- The session, once created, never changes during a run
- Records are small; re-enqueueing adds negligible overhead
- The queue is unbounded; no backpressure risk from temporary buffering
- Once the session exists (typically within seconds of startup), all buffered records flush immediately

### For listener_id=0: Option C (register internal listeners in DB)

Internal handlers are legitimate telemetry targets. The ServiceWatcher and StateProxy handlers process real events and their performance/error data is valuable. Registering them in the DB with a synthetic `app_key` like `"__hassette__"` or using their `owner_id` as the key:
- Gives them valid `db_id` values, eliminating `listener_id=0`
- Makes internal handler telemetry queryable
- Maintains a single code path for all handler invocations

The `_register_then_add_route()` path already handles the async registration-before-route pattern. Removing the `if listener.app_key:` guard (and ensuring a fallback app_key is set) routes all listeners through this path uniformly.

### Why not Option D (skip internal handler telemetry)?

While simpler, it creates a permanent blind spot. Internal handlers (particularly `_on_state_change` in StateProxy) process high volumes of events and are exactly the kind of handlers where performance telemetry is most useful for debugging.

### Why not Option E (startup reordering)?

It adds startup latency, requires restructuring the startup contract, and still does not solve the `listener_id=0` problem. The backfill approach (Option A) achieves the same result with less disruption.

## Concerns

### Technical risks

- **Re-enqueue loop**: If session creation fails entirely, records will cycle through the queue forever. Mitigation: add a max-retry count or check `shutdown_event` before re-enqueuing.
- **Record attribution accuracy**: Records created before the session are attributed to the session retroactively. This is technically imprecise but pragmatically correct -- the session represents the entire Hassette run, including startup.
- **Internal listener registration timing**: If `_register_then_add_route()` is slow for internal listeners (DB contention during startup), ServiceWatcher might miss early service status events. Mitigation: ServiceWatcher's `on_initialize()` already runs after `_start_resources()`, so the DB is being initialized concurrently.

### Complexity risks

- Adding internal listeners to the DB introduces a new convention (`app_key` for non-app resources) that must be documented and maintained
- The backfill logic in `_do_persist_batch()` adds a new code path that must be tested

### Maintenance risks

- The `__hassette__` app_key convention becomes a permanent part of the data model
- Any new internal listener automatically gets DB registration (which is desirable but increases DB volume slightly)

## Open Questions

- [ ] Should internal listener registrations use `owner_id` (e.g., `"Hassette.ServiceWatcher"`) or a fixed sentinel (e.g., `"__hassette__"`) as the `app_key`? Using `owner_id` gives better granularity in queries; using a sentinel simplifies filtering.
- [ ] Should backfilled records get a flag or annotation indicating they were created before the session? (e.g., a boolean `pre_session` column or a comment in the record)
- [ ] Is there a UI/query impact from internal listeners appearing in the listeners table? The web dashboard may need to filter or distinguish internal vs app listeners.
- [ ] How many internal listeners exist in a typical deployment? (Rough count from code: ~8-12 across ServiceWatcher, StateProxy, core.py crash handler, and FileWatcher)

## Suggested Next Steps

1. **Write a design doc** (`/mine.design`) covering the combined A+C approach with specific implementation details for the backfill logic and internal listener registration convention
2. **Add tests first** (TDD per project convention): write failing tests for session_id backfill and internal listener DB registration before implementing
3. **Implement in two phases**: Phase 1 = session_id backfill (Option A), Phase 2 = internal listener registration (Option C). Each phase is independently shippable and testable.

## Key Files

| File | Role in the fix |
|------|----------------|
| `src/hassette/core/command_executor.py` | Backfill logic in `_do_persist_batch()`, `_safe_session_id()` |
| `src/hassette/core/bus_service.py` | Remove `if listener.app_key:` guard in `add_listener()`, or add fallback app_key |
| `src/hassette/core/scheduler_service.py` | Same pattern as bus_service for job registration |
| `src/hassette/bus/bus.py` | Set `app_key` for internal Bus instances (ServiceWatcher, StateProxy, etc.) |
| `src/hassette/bus/invocation_record.py` | Frozen dataclass -- no changes needed (new instances created during backfill) |
| `src/hassette/core/session_manager.py` | No changes needed (session creation timing stays the same) |
| `src/hassette/core/core.py` | No changes needed (startup sequence stays the same) |
| `tests/integration/test_command_executor.py` | Add backfill and internal listener tests |
