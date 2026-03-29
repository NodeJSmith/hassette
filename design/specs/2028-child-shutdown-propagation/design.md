# Design: Automatic Child Lifecycle Propagation in Resource

**Date:** 2026-03-29
**Status:** approved
**Issue:** #449
**Research:** `/tmp/claude-mine-research-init-propagation-Nvvi9k/brief.md`

## Problem

`Resource.shutdown()` and `Resource.initialize()` do not propagate to children. This creates three problems:

1. **Duplicated cleanup logic** — parents like `App` and `StateProxy` manually call `remove_all_jobs()` / `remove_all_listeners()` instead of relying on child `shutdown()` calls. Every parent must know which cleanup methods to call on each child type.
2. **Unreachable hooks** — `on_shutdown()` on child Resources (e.g., `Bus.on_shutdown()`) is never called by the parent, making it dead code. `Scheduler` can't have an `on_shutdown()` hook because it would never be invoked.
3. **Broken `restart()`** — `restart()` calls `shutdown()` then `initialize()`. Without symmetry, adding shutdown propagation alone would permanently kill children (they'd be shut down but never re-initialized). Additionally, `restart()` has a pre-existing bug: `shutdown_event` is never reset, so restarted Services whose `serve()` loops check `shutdown_event.is_set()` exit immediately.

Surfaced during design review of issues #412, #414, #436, #437, #438. Related: #69 (dependency ordering), #323 (lifecycle hook tests), #317 (mark_ready docs).

## Non-Goals

- **Changing `Hassette.on_shutdown()`** — it has a unique constraint where `close_streams()` must run after all children stop. The `_shutdown_completed` flag (see Idempotency section) makes double propagation a no-op.
- **Changing `StateProxy.on_disconnect()`** — runtime recovery path, not a shutdown path.
- **Dependency-based initialization ordering** (#69) — children initialize in insertion order, not dependency order. Hassette's phased startup remains explicit.

## Architecture

### 1. True Shutdown Idempotency: `_shutdown_completed` Flag

The existing `_shutting_down` flag resets to `False` in the `finally` block of `shutdown()` (`base.py:303`, `base.py:404`). It only guards against re-entrant shutdown, not sequential double-shutdown. When Hassette's `on_shutdown()` completes children (resetting their flags), `_finalize_shutdown()` propagation would re-trigger them.

Add a `_shutdown_completed: bool` flag to Resource, set to `True` at the end of `_finalize_shutdown()`, checked at the top of `shutdown()` before the `_shutting_down` guard. Reset only in `initialize()` to support `restart()`.

```python
# At top of Resource.shutdown() and Service.shutdown():
if self._shutdown_completed:
    return

# At end of Resource._finalize_shutdown():
self._shutdown_completed = True

# At top of Resource.initialize() and Service.initialize():
self._shutdown_completed = False
```

### 2. Shutdown Propagation: `Resource._finalize_shutdown()`

Add automatic child shutdown propagation in `_finalize_shutdown()`, after `cleanup()` and before `handle_stop()`. The Resource shutdown flow becomes:

```
shutdown()
  if _shutdown_completed: return          # true idempotency
  _shutting_down = True
  _run_hooks([before_shutdown, on_shutdown, after_shutdown])
  _finalize_shutdown()
    cleanup()                              # cancel parent's tasks, close cache
    children = list(reversed(self.children))   # snapshot
    results = gather(*[c.shutdown() for c in children], return_exceptions=True)
    for child, result in zip(children, results):
      if isinstance(result, Exception):
        logger.error("Child %s shutdown failed: %s", child.unique_name, result)
    _shutdown_completed = True
    if not hassette.event_streams_closed:  # guard: don't emit after streams close
      handle_stop()                        # emit STOPPED event
  _shutting_down = False
```

The **Service** shutdown flow is materially different and must be documented:

```
Service.shutdown()
  if _shutdown_completed: return
  _shutting_down = True
  _run_hooks([before_shutdown])
  cancel _serve_task                       # serve loop stops
  _serve_wrapper catches CancelledError → handle_stop()  # first STOPPED (idempotent)
  _run_hooks([on_shutdown, after_shutdown])
  _finalize_shutdown()                     # inherited from Resource
    cleanup()
    propagate to children (reversed)       # children shut down AFTER serve task cancelled
    _shutdown_completed = True
    handle_stop()                          # second call — no-op via status guard
  _shutting_down = False
```

Child propagation runs after the parent's serve task is cancelled. Children must not depend on the parent's serve loop during their own shutdown.

**Implementation constraint**: Section 1 (`_shutdown_completed` flag) and Section 2 (shutdown propagation) MUST be implemented atomically. Propagation without the idempotency flag causes Hassette's `on_shutdown()` to double-shutdown every child with real effects. Work packages must include both in the same unit.

**Error handling**: Snapshot children via `list(reversed(self.children))` before `gather`. Log each exception with the child's `unique_name`. Exceptions do not propagate out of `_finalize_shutdown`.

**Timeout**: Wrap the gather in `asyncio.wait_for(timeout=resource_shutdown_timeout_seconds)` for defense-in-depth.

### 3. Initialization Propagation: `Resource.initialize()` / `Service.initialize()`

Add automatic child initialization propagation after the parent's hooks complete. Skip children whose status is `STARTING` or `RUNNING` (actively-live children). All other statuses (`NOT_STARTED`, `STOPPED`, `FAILED`, `CRASHED`) are eligible for re-initialization. This handles the Hassette case (children started via `start()` are already `STARTING`) while also allowing crashed children to recover on restart.

Init propagation is **sequential** (awaiting each child in insertion order) while shutdown propagation is **concurrent** (gather). Rationale: children may depend on earlier siblings during initialization (insertion order preserves implicit dependencies), while shutdown should be fast and best-effort.

**Ordering constraint**: Parent hooks (`on_initialize`) run BEFORE child propagation. This means parents can register subscriptions on child Bus/Scheduler resources before those children have been re-initialized. This works because `Bus.on()` and `Scheduler.run_every()` do not gate on readiness — they operate on the underlying BusService/SchedulerService directly. Verify this invariant holds when implementing.

The Resource initialization flow becomes:

```
initialize()
  _shutdown_completed = False              # reset for re-use after restart
  _initializing = True
  handle_starting()
  _run_hooks([before_initialize, on_initialize, after_initialize])
  for child in self.children:              # insertion order
    if child.status not in (STARTING, RUNNING):
      await child.initialize()
  handle_running()                         # parent RUNNING only after children initialized
  _initializing = False
```

For Service, child propagation runs after `after_initialize()` (which is after the serve task is spawned):

```
Service.initialize()
  _shutdown_completed = False
  _initializing = True
  handle_starting()
  _run_hooks([before_initialize, on_initialize])
  spawn _serve_task
  _run_hooks([after_initialize])
  for child in self.children:
    if child.status not in (STARTING, RUNNING):
      await child.initialize()
  # Note: handle_running() is called by _serve_wrapper, not here
  _initializing = False
```

### 4. Fix `shutdown_event` Reset: Single Canonical Location in `initialize()`

`restart()` calls `shutdown()` then `initialize()`. Currently, `shutdown()` sets `shutdown_event` via `request_shutdown()`, but `initialize()` never clears it. After restart, Services whose `serve()` loops check `shutdown_event.is_set()` would exit immediately.

Fix: `initialize()` clears `shutdown_event` as its first action (before the `_initializing` guard check, alongside resetting `_shutdown_completed`). Use `.clear()` instead of replacing the Event object to preserve references held by serve loops or external waiters. Remove the duplicate reset from `start()` (`mixins.py:94`) — `initialize()` is the single canonical location for event reset.

```python
async def initialize(self) -> None:
    self._shutdown_completed = False
    self.shutdown_event.clear()            # clear, don't replace — preserves references
    if self._initializing:
        return
    ...
```

Also reset `_shutdown_completed` in `start()` before the early-return guard, so a `start()` call after shutdown doesn't get permanently stuck on a stale flag:

```python
def start(self) -> None:
    self._shutdown_completed = False       # allow re-use after shutdown
    if self._init_task and not self._init_task.done():
        ...
        return
    ...
```

### 5. Move `mark_ready()` from `__init__` to Lifecycle Hooks

Four leaf Resources call `mark_ready()` in their constructors. After shutdown clears readiness, re-initialization via propagation won't restore it. Move to `on_initialize()`:

| Class | Current location | New location | Notes |
|-------|-----------------|--------------|-------|
| `Bus` | `__init__` (`bus.py:132`) | new `on_initialize()` | No existing `on_initialize()` — create it |
| `Scheduler` | `__init__` (`scheduler.py:140`) | new `on_initialize()` | No existing `on_initialize()` — create it |
| `Api` | `__init__` (`api.py:202`) | new `on_initialize()` | No existing `on_initialize()` — create it |
| `ApiSyncFacade` | `__init__` (`api/sync.py:44`) | new `on_initialize()` | Child of Api, no existing hook |
| `_ScheduledJobQueue` | `__init__` (`core/scheduler_service.py:335`) | new `on_initialize()` | Child of SchedulerService, no existing hook |

`StateManager` already calls `mark_ready()` in `after_initialize()` — no change needed.
`ServiceWatcher` and `AppHandler` already call `mark_ready()` in `on_initialize()` — no change needed.

### 6. New Hook: `Scheduler.on_shutdown()`

Add `on_shutdown()` to `Scheduler` that awaits `remove_all_jobs()`. This mirrors `Bus.on_shutdown()` which already calls `await self.remove_all_listeners()`.

```python
async def on_shutdown(self) -> None:
    await self.remove_all_jobs()
```

Note: `remove_all_jobs()` returns `asyncio.Task` — it must be awaited. `_jobs_by_name.clear()` is not needed separately since `remove_all_jobs()` already clears it.

### 7. Simplified Parents

**`App.cleanup()`** (`app.py:133-153`): Remove the manual `scheduler.remove_all_jobs()`, `bus.remove_all_listeners()`, and redundant `task_bucket.cancel_all()` calls. The redundant `cancel_all()` call (present in both `super().cleanup()` and the gathered tasks) is also removed. The entire method body becomes `await super().cleanup(timeout=timeout)`. Note: the App-specific `app_shutdown_timeout_seconds` is preserved via the `timeout` parameter passed to `super().cleanup()`. The per-child timeout in `_finalize_shutdown` uses `resource_shutdown_timeout_seconds` for the propagation gather.

**`StateProxy.on_shutdown()`** (`state_proxy.py:93-104`): Remove `bus.remove_all_listeners()` and `scheduler.remove_all_jobs()` calls. Keep `mark_not_ready()`, `states.clear()`, and the defensive null-setting (`poll_job = None`, `state_change_sub = None`) — `on_disconnect()` checks these references and could race with shutdown.

**`ServiceWatcher.on_shutdown()`** (`service_watcher.py:39-40`): Remove `await self.bus.remove_all_listeners()`.

**`AppHandler.on_shutdown()`** (`app_handler.py:108-113`): Remove `await self.lifecycle.bus.remove_all_listeners()`. Keep `await self.lifecycle.shutdown_all()` — app instances are in the AppRegistry, not the Resource tree.

## Alternatives Considered

**Add an `after_children_shutdown()` hook** — would let Hassette override it for `close_streams()` instead of keeping the manual loop. Rejected: adds framework complexity for a single consumer. The `_shutdown_completed` flag is simpler.

**Use `asyncio.TaskGroup` instead of `gather`** — TaskGroup cancels remaining tasks on first failure. We want all children to get a shutdown attempt. `gather(return_exceptions=True)` is correct.

**Skip child propagation during `restart()` via `_restarting` flag** — creates a semantic split where "shutdown" means two different things. Adding symmetric init propagation is cleaner and fixes the underlying problem.

## Test Strategy

Unit tests covering:
- **Shutdown propagation**: parent shutdown calls children's `on_shutdown` in reverse order
- **Initialization propagation**: parent initialize calls children's `on_initialize` in insertion order
- **Status-based skip**: already-RUNNING children are not re-initialized during propagation
- **Error tolerance**: one child failing doesn't block others (shutdown)
- **True idempotency**: `_shutdown_completed` prevents sequential double-shutdown
- **`restart()` round-trip**: children survive restart (shut down then re-initialized, readiness restored)
- **`shutdown_event` reset**: after restart, `shutdown_event.is_set()` returns False
- **`Scheduler.on_shutdown()`** clears jobs via awaited Task
- **`mark_ready` in `on_initialize`**: leaf Resources are ready after init, not-ready after shutdown, ready again after re-init

Integration: run full suite (`uv run nox -s dev`) — pay attention to `test_state_proxy.py`, `test_core.py`, `test_app_factory_lifecycle.py`, `test_service_lifecycle.py`.

**Test utility**: `reset_state_proxy()` in `test_utils/reset.py` calls `proxy.on_shutdown()` directly — update to call `proxy.shutdown()` + `proxy.initialize()` for full lifecycle path.

## Open Questions

- **Propagation opt-out**: Should there be a mechanism for `add_child` consumers to register a child without subjecting it to lifecycle propagation? No current consumer needs this, but as the framework grows, infrastructure/monitoring children may want to opt out. Deferred unless a concrete need arises.

## Impact

**Files modified:**
- `src/hassette/resources/base.py` — `_shutdown_completed` flag, child propagation in `_finalize_shutdown()` and `initialize()`/`Service.initialize()`, `shutdown_event` reset, `restart()` unchanged (inherits fixes)
- `src/hassette/resources/mixins.py` — `_shutdown_completed` attribute declaration, remove `shutdown_event` replacement from `start()` (canonical reset now in `initialize()` via `.clear()`), add `_shutdown_completed` reset to `start()`
- `src/hassette/scheduler/scheduler.py` — new `on_shutdown()`, move `mark_ready` to `on_initialize()`
- `src/hassette/bus/bus.py` — move `mark_ready` to `on_initialize()`
- `src/hassette/api/api.py` — move `mark_ready` to `on_initialize()`
- `src/hassette/api/sync.py` — `ApiSyncFacade`: move `mark_ready` to new `on_initialize()`
- `src/hassette/core/scheduler_service.py` — `_ScheduledJobQueue`: move `mark_ready` to new `on_initialize()`
- `src/hassette/app/app.py` — `App.cleanup()` simplified
- `src/hassette/core/state_proxy.py` — `StateProxy.on_shutdown()` simplified (keep null-setting)
- `src/hassette/core/service_watcher.py` — remove manual `remove_all_listeners()`
- `src/hassette/core/app_handler.py` — remove manual `remove_all_listeners()`
- `src/hassette/test_utils/reset.py` — `reset_state_proxy()` uses full lifecycle; `reset_hassette_lifecycle()` resets new `_shutdown_completed` flag

**Files unchanged:**
- `src/hassette/core/core.py` — `Hassette.on_shutdown()` stays as-is (`_shutdown_completed` handles it); `Hassette.on_initialize()` starts children via `start()`, propagation skips them (already STARTING)

**New files:**
- `tests/unit/resources/test_lifecycle_propagation.py` — propagation and idempotency tests

**Blast radius:** Medium. Base class changes affect all Resource subclasses, but shutdown propagation only activates for Resources with children, and init propagation only activates for children in `NOT_STARTED`/`STOPPED` status.
