---
proposal: "Fix 5 HIGH findings in the child lifecycle propagation PR: timeout cleanup gaps, double-shutdown bypass, Service status asymmetry, timeout budget multiplication, and STARTING child orphaning."
date: 2026-03-29
status: Draft
flexibility: Exploring
motivation: "Ship the propagation PR correctly -- the timeout/shutdown path is part of the propagation contract, shipping it broken undermines the PR's value."
constraints: "Python 3.11+ (asyncio.timeout available), async-first single-loop framework, ~15 core services at Hassette level, ~20 children of Hassette"
non-goals: "None stated"
depth: deep
---

# Research Brief: Lifecycle Contract Gaps in Child Propagation PR

**Initiated by**: Challenge review of PR #449 (automatic child lifecycle propagation) identified 5 HIGH-severity findings in timeout enforcement, shutdown ordering, and status consistency.

## Context

### What prompted this

PR #449 adds automatic child lifecycle propagation to `Resource._finalize_shutdown()` and `Resource.initialize()` / `Service.initialize()`. The propagation logic itself is solid, but a challenge review surfaced 5 HIGH findings where the contract is incomplete or self-defeating. The timeout handler leaks resources, Hassette's manual shutdown bypasses the timeout entirely, Service initialization has a status asymmetry that can deadlock children, the timeout budget multiplies with tree depth, and crashed children can get stuck in STARTING.

### Current state

**Resource tree structure (relevant to these findings):**

```
Hassette (Resource)
  +-- EventStreamService (Service)
  +-- DatabaseService (Service)
  +-- SessionManager (Resource)
  +-- CommandExecutor (Service)
  +-- BusService (Service)
  +-- ServiceWatcher (Resource)
  |     +-- Bus
  +-- WebsocketService (Service)
  +-- FileWatcherService (Service)
  +-- WebUiWatcherService (Service)
  +-- AppHandler (Resource)
  |     +-- AppLifecycleService (Resource)
  |           +-- Bus
  +-- SchedulerService (Service)
  |     +-- _ScheduledJobQueue (Resource)
  +-- ApiResource (Resource)
  +-- StateProxy (Resource)
  |     +-- Bus (priority=100)
  |     +-- Scheduler
  +-- RuntimeQueryService (Resource)
  |     +-- Bus
  +-- TelemetryQueryService (Resource)
  +-- WebApiService (Service)
  +-- Bus (Hassette's own)
  +-- Scheduler (Hassette's own)
  +-- StateManager
  +-- Api
       +-- ApiSyncFacade
```

App instances are **not** in Hassette's children list. They are created by `AppFactory` with `parent=None` and managed explicitly by `AppLifecycleService`. Their tree is:

```
App (Resource, parent=None)
  +-- Api
  |     +-- ApiSyncFacade
  +-- Scheduler
  +-- Bus (priority=0)
  +-- StateManager
```

**Maximum tree depth:** 4 levels (Hassette -> AppHandler -> AppLifecycleService -> Bus). For App instances managed outside the tree, depth is 3 (App -> Api -> ApiSyncFacade).

**Shutdown flow (current PR):**

1. `shutdown()` sets guards, runs hooks (`before_shutdown`, `on_shutdown`, `after_shutdown`)
2. `_finalize_shutdown()`:
   - Calls `cleanup()` (cancels init task, cancels task bucket, closes cache)
   - Gathers `child.shutdown()` for all children (reversed insertion order) with `asyncio.wait_for(timeout=resource_shutdown_timeout_seconds)`
   - On timeout: force-patches `_shutdown_completed=True`, `status=STOPPED` on incomplete children
   - Sets `self._shutdown_completed = True`
   - Calls `handle_stop()` (emits STOPPED event)

**Timeout config defaults:** `resource_shutdown_timeout_seconds` defaults to `app_shutdown_timeout_seconds` which defaults to 10s. `task_cancellation_timeout_seconds` defaults to 5s.

### Key constraints

- Python 3.11+ gives us `asyncio.timeout()` (context manager) as an alternative to `asyncio.wait_for()`
- Single event loop, no multi-threading for lifecycle operations
- ~20 children at Hassette level; all must shut down within reasonable wall-clock time
- Event streams must stay open until all children emit STOPPED events (ordering constraint in `Hassette.on_shutdown()`)

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Finding 1: Timeout cleanup | `base.py` (_finalize_shutdown timeout handler) | Low | Low -- localized to timeout path |
| Finding 2: Double-shutdown | `core.py` (Hassette.on_shutdown), `base.py` | Medium | Medium -- stream closure ordering must be verified |
| Finding 3: Service status | `base.py` (Service.initialize), docs | Low | Low -- documentation + guard, no behavior change |
| Finding 4: Deadline propagation | `base.py` (_finalize_shutdown), `mixins.py` | Medium | Medium -- threading deadline through call chain |
| Finding 5: STARTING orphans | `base.py` (initialize, _finalize_shutdown) | Low | Low -- flag reset |

### What already supports this

1. **`_shutdown_completed` flag is already in place** -- the PR added this correctly, and the timeout handler already uses it. The fix for Finding 1 builds on this.
2. **`cleanup()` is a standalone method** -- it can be called independently of the full shutdown flow. The timeout handler can call `cleanup()` directly.
3. **`handle_stop()` has an idempotency guard** -- it checks `if self.status == ResourceStatus.STOPPED: return`, so calling it on a timed-out child that may have partially stopped is safe.
4. **`asyncio.timeout()` context manager (Python 3.11+)** -- does not create a new task (unlike `wait_for`), which avoids the scheduling quirks mentioned in Finding 9 of the challenge review.
5. **`after_shutdown` hook exists** -- provides a natural place for `close_streams()` if moved out of `on_shutdown`.

### What works against this

1. **`Hassette.on_shutdown()` has an ordering constraint** -- `close_streams()` must run after all children emit STOPPED events. Moving it to `after_shutdown` requires proving that `after_shutdown` runs before `_finalize_shutdown` (it does -- that's the hook ordering).
2. **`asyncio.wait_for` wrapping `asyncio.gather`** -- when the timeout fires, `wait_for` cancels the task running the gather. This sends CancelledError to all gathered coroutines. Their `finally` blocks run, which means `_finalize_shutdown` of child resources can race with the parent's timeout handler that force-patches flags. This is the core race condition in Finding 1.
3. **Service.initialize() status is intentionally deferred** -- the design doc explicitly says "Services' readiness is tied to serve() running." Changing this breaks the contract.
4. **No existing deadline/absolute-time mechanism** -- adding one requires either an instance attribute or a parameter change, neither of which is trivial to thread through the `shutdown()` -> `_finalize_shutdown()` call chain.

## Detailed Analysis Per Finding

### Finding 1: Timeout force-patches child state without cleanup

**The problem in detail:**

At `base.py:268-277`, when `asyncio.wait_for` raises `TimeoutError`:

```python
except TimeoutError:
    self.logger.error("Timed out waiting for children to shut down after %s seconds", timeout)
    for child in children:
        if not child._shutdown_completed:
            child._shutting_down = False
            child._shutdown_completed = True
            child.status = ResourceStatus.STOPPED
            child.mark_not_ready("shutdown timed out")
```

This skips:
- **`cleanup()`** -- task buckets remain active (tasks keep running), `_init_task` is not cancelled, disk cache stays open
- **`handle_stop()`** -- no STOPPED event emitted, so ServiceWatcher, DatabaseService session tracking, and web UI status displays never learn the child stopped

**What leaks per resource type:**

| Resource type | What `cleanup()` does | What leaks if skipped |
|---|---|---|
| Any Resource | `cancel()` (_init_task), `task_bucket.cancel_all()`, `cache.close()` | Running init tasks, tracked tasks in WeakSet, open diskcache file handles |
| Bus | `on_shutdown` calls `remove_all_listeners()` | Listeners remain registered in BusService, continue firing on events |
| Scheduler | `on_shutdown` calls `remove_all_jobs()` | Jobs remain in SchedulerService, continue executing |
| App | Calls `super().cleanup()` with app-specific timeout | All of the above, plus app-owned tasks |

**Race condition with cancellation:**

When `asyncio.wait_for` times out, it cancels the gather task. This sends `CancelledError` to each child's `shutdown()` coroutine. If a child is mid-`_finalize_shutdown()`, its `finally` block in `shutdown()` will still call `_finalize_shutdown()`:

```python
# Resource.shutdown()
try:
    await self._run_hooks([...], continue_on_error=True)
finally:
    await self._finalize_shutdown()  # <-- runs even on CancelledError
    self._shutting_down = False
```

But `_finalize_shutdown()` itself awaits `cleanup()` and `handle_stop()`, which will also be cancelled. Meanwhile, the parent's timeout handler is force-patching the child's flags. The child's `finally` block and the parent's timeout handler race on `_shutdown_completed`, `_shutting_down`, and `status`.

**Key insight:** The `finally` block in `shutdown()` re-raises `CancelledError` after `_finalize_shutdown()`. But `_finalize_shutdown()` does NOT have a `try/except CancelledError` -- it will propagate through `cleanup()` and `handle_stop()`, meaning those may not complete even in the finally path.

### Finding 2: Hassette.on_shutdown() double-shutdown bypass

**The problem in detail:**

```python
# Hassette.on_shutdown()
async def on_shutdown(self) -> None:
    shutdown_tasks = [resource.shutdown() for resource in reversed(self.children)]
    results = await asyncio.gather(*shutdown_tasks, return_exceptions=True)
    # ... log results ...
    await self._event_stream_service.close_streams()
```

This runs as part of `shutdown()` -> `_run_hooks([before_shutdown, on_shutdown, after_shutdown])`. After it completes, `_finalize_shutdown()` runs and gathers `child.shutdown()` again. But every child already has `_shutdown_completed=True`, so the second pass is a no-op. The timeout enforcement in `_finalize_shutdown` never fires.

**Can `close_streams()` move to `after_shutdown()`?**

Yes. The hook execution order is:
1. `before_shutdown()` -- removes bus listeners, finalizes session
2. `on_shutdown()` -- currently does manual gather + close_streams
3. `after_shutdown()` -- currently empty for Hassette
4. `_finalize_shutdown()` -- cleanup, child propagation, handle_stop

If `close_streams()` moves to `after_shutdown()`:
- Children would shut down in `_finalize_shutdown()` (step 4), with timeout enforcement
- `close_streams()` would run in step 3, **before** children shut down -- this is WRONG

If `close_streams()` moves to a position AFTER `_finalize_shutdown()`:
- There is no hook for this. `_finalize_shutdown` is called in the `finally` block of `shutdown()`, and nothing runs after it.

**The ordering constraint requires careful handling:**

```
Children emit STOPPED events during their shutdown
  -> EventStreamService must still be open to deliver those events
    -> close_streams() must run AFTER all children (including EventStreamService itself) have stopped
```

But `_finalize_shutdown` calls `handle_stop()` after child propagation, and that's where STOPPED events are emitted. So the flow needs to be:

1. Children shut down (emit STOPPED events via handle_stop)
2. Parent calls close_streams()
3. Parent emits its own STOPPED event (or skips if streams are closed)

This is achievable by moving the manual child shutdown INTO `_finalize_shutdown()` (which already does this), and then calling `close_streams()` between child propagation and the parent's `handle_stop()`.

**Approach: Override `_finalize_shutdown()` on Hassette** to insert `close_streams()` at the right point. Or add a hook between child propagation and handle_stop. Or move close_streams to run after child propagation but before handle_stop in the existing _finalize_shutdown flow.

However, `_finalize_shutdown` is not marked `@final` -- Hassette could override it. But the design doc's Non-Goals section says "Changing Hassette.on_shutdown()" is a non-goal. The PR author explicitly accepted the double-shutdown behavior.

**Reassessment:** The design doc states: "The `_shutdown_completed` flag makes double propagation a no-op." This was an intentional design choice. The question is whether the timeout bypass is acceptable given that Hassette's `on_shutdown` has no timeout either. In practice, Hassette's children are all Services with their own serve task cancellation -- if one hangs, the whole process hangs. The timeout enforcement was meant to prevent exactly this.

### Finding 3: Service.initialize() status asymmetry

**The problem in detail:**

```python
# Resource.initialize()
async def initialize(self):
    ...
    await self._run_hooks([self.before_initialize, self.on_initialize, self.after_initialize])
    for child in self.children:
        if child.status not in (ResourceStatus.STARTING, ResourceStatus.RUNNING):
            await child.initialize()
    await self.handle_running()  # <-- RUNNING guaranteed on return
    ...

# Service.initialize()
async def initialize(self):
    ...
    await self._run_hooks([self.before_initialize, self.on_initialize])
    self._serve_task = self.task_bucket.spawn(self._serve_wrapper(), ...)
    await self._run_hooks([self.after_initialize])
    for child in self.children:
        if child.status not in (ResourceStatus.STARTING, ResourceStatus.RUNNING):
            await child.initialize()
    # <-- NO handle_running() here -- status is still STARTING
    ...
```

`_serve_wrapper()` calls `handle_running()` when it actually starts executing. But since it's spawned as a task, it doesn't run until the current coroutine yields. Child propagation runs synchronously, so children are initialized while the parent Service is still STARTING.

**Deadlock scenario:** If a child's `on_initialize()` calls `await self.parent.wait_ready()`, it blocks forever -- the parent won't be ready until `_serve_wrapper` runs, but `_serve_wrapper` can't run until child initialization completes (it's all on the same event loop, and child init is sequential).

**Current impact:** No existing code calls `self.parent.wait_ready()` from `on_initialize()`. The deadlock is latent -- it only manifests if a user writes an app or service that does this. The 8 existing Service subclasses (BusService, SchedulerService, WebsocketService, CommandExecutor, FileWatcherService, WebUiWatcherService, WebApiService, DatabaseService) all call `mark_ready()` inside their `serve()` method, and none have children that depend on parent readiness during init.

**Why this is intentional:** Services are ready when `serve()` is actually running, not when `initialize()` returns. The WebsocketService, for example, marks ready only after successfully authenticating with Home Assistant -- that happens inside `serve()`, potentially seconds after `initialize()` returns. Moving `handle_running()` before `serve()` starts would lie about the Service's status.

### Finding 4: Timeout budget multiplies across tree depth

**The problem in detail:**

Each level's `_finalize_shutdown` calls `asyncio.wait_for(..., timeout=resource_shutdown_timeout_seconds)`. If a child's `_finalize_shutdown` is running its own `wait_for` on grandchildren, the parent's timeout covers the child's full shutdown time, which includes the grandchild timeout. With default 10s timeout and max depth 4:

```
Hassette timeout: 10s
  -> AppHandler timeout: 10s (nested)
    -> AppLifecycleService timeout: 10s (nested)
      -> Bus: instant
```

Worst case: 30s (3 levels with non-trivial children), not 40s (leaf has no children).

**Actual tree depths where this matters:**

| Path | Depth | Max wall-clock |
|---|---|---|
| Hassette -> StateProxy -> Bus/Scheduler | 2 | 20s |
| Hassette -> AppHandler -> AppLifecycleService -> Bus | 3 | 30s |
| Hassette -> SchedulerService -> _ScheduledJobQueue | 2 | 20s |
| App -> Api -> ApiSyncFacade | 2 | 20s (but apps are outside Hassette's tree) |

**Deadline propagation feasibility:**

The Trio/structured concurrency approach is to pass an **absolute deadline** through the cancel scope. In this codebase, that would mean:

```python
async def _finalize_shutdown(self, deadline: float | None = None) -> None:
    ...
    if deadline is None:
        deadline = asyncio.get_event_loop().time() + timeout
    remaining = deadline - asyncio.get_event_loop().time()
    if remaining <= 0:
        # already past deadline, force-patch all children
        ...
    else:
        async with asyncio.timeout(remaining):
            await asyncio.gather(*[child.shutdown(deadline=deadline) for child in children])
```

But `shutdown()` is `@final` and its signature is `async def shutdown(self) -> None`. Threading a deadline through requires either:

1. **Instance attribute**: `self._shutdown_deadline: float | None = None`, set before calling `shutdown()`. Safe because we're single-threaded.
2. **Parameter change**: Break the `@final` signature. Not viable without changing all subclasses.
3. **ContextVar**: Thread-local-like storage for the current deadline. Clean but adds complexity.

Option 1 (instance attribute) is simplest and fits the single-loop model. The parent sets `child._shutdown_deadline = deadline` before calling `child.shutdown()`.

### Finding 5: STARTING children silently skipped during restart

**The problem in detail:**

```python
# In initialize():
for child in self.children:
    if child.status not in (ResourceStatus.STARTING, ResourceStatus.RUNNING):
        await child.initialize()
```

If a Service crashes mid-initialization (e.g., its `on_initialize` throws), the `finally` block sets `_initializing = False`, and the Service goes through `handle_failed()` (status becomes FAILED). The FAILED status is eligible for re-initialization, so this case is actually handled.

But if the crash happens **inside** `_serve_wrapper()` before `handle_running()` completes -- the status is still STARTING (set by `handle_starting()` in `initialize()`). On restart, `initialize()` skips it because `STARTING` is in the skip list.

Additionally, if `initialize()` itself raises an exception (not caught by the `try/finally`), the `_initializing = False` in the `finally` block runs, but `_shutdown_completed` is already `False` (set at the top of `initialize()`). The `_initializing` flag is correctly reset. So the `_initializing` flag issue is actually less severe than stated in the finding -- the `finally` block handles it.

**The real issue is the STARTING skip semantics during restart.** When `restart()` calls `shutdown()` then `initialize()`:

1. `shutdown()` sets `_shutdown_completed = True`
2. `initialize()` sets `_shutdown_completed = False` (top of method)
3. Child propagation skips children with `STARTING` status

A child stuck in STARTING after a crash would be skipped. But `_finalize_shutdown()` sets `status = STOPPED` on timed-out children (Finding 1's force-patch). And normal shutdown calls `handle_stop()` which sets `STOPPED`. So a child should only be in STARTING if:
- It was never shut down (parent crashed before shutdown propagation reached it)
- Its `_serve_wrapper` is still running (legitimate STARTING, should be skipped)

**The `_initializing` flag concern is valid but narrow:** If `initialize()` is interrupted by `CancelledError` (not Exception), the `finally` block runs `_initializing = False`. CancelledError inherits from BaseException, and the `finally` block catches it. So `_initializing` is always reset.

**Wait -- re-reading the code:** The `_initializing` guard returns early WITHOUT setting `_shutdown_completed = False`. If a previous `initialize()` was interrupted between `_initializing = True` and the `finally` block... but that's impossible because `_initializing = True` and `finally: _initializing = False` are in the same `try/finally`. The only gap is between `_shutdown_completed = False` and `_initializing = True`, and between those two lines, nothing can yield.

**Conclusion:** Finding 5 is real but lower severity than stated. The STARTING skip during restart is the main concern, and it requires a Service's `_serve_wrapper` to crash between `handle_starting()` and `handle_running()` without transitioning to FAILED/CRASHED. Looking at `_serve_wrapper`:

```python
async def _serve_wrapper(self) -> None:
    try:
        await self.handle_running()  # <-- could fail here
        await self.serve()
    except asyncio.CancelledError:
        ...
        raise
    except FatalError as e:
        await self.handle_crash(e)  # -> CRASHED status
    except Exception as e:
        await self.handle_failed(e)  # -> FAILED status
```

If `handle_running()` itself throws (unlikely -- it just sets status and emits an event), the exception would be caught by the `except Exception` block and status would move to FAILED. So the STARTING orphan scenario requires a very specific failure mode.

## Options Evaluated

### Option A: Incremental fixes -- address each finding independently

**How it works:**

**F1 fix -- Cleanup and STOPPED event in timeout handler:**
After force-patching flags, attempt cleanup and handle_stop on each timed-out child. Use fire-and-forget with a short safety timeout to avoid blocking the parent's shutdown indefinitely:

```python
except TimeoutError:
    for child in children:
        if not child._shutdown_completed:
            # Attempt cleanup (best-effort)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(child.cleanup(), timeout=2.0)
            # Attempt STOPPED event (best-effort)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(child.handle_stop(), timeout=1.0)
            # Force terminal state
            child._shutting_down = False
            child._shutdown_completed = True
            child.status = ResourceStatus.STOPPED
            child.mark_not_ready("shutdown timed out")
```

**F2 fix -- Remove manual gather from Hassette.on_shutdown:**
Move `close_streams()` call to after child propagation completes. Override `_finalize_shutdown()` on Hassette to insert `close_streams()` between child propagation and handle_stop. Or add a new protected method `_post_children_shutdown()` called by `_finalize_shutdown()`.

**F3 fix -- Document Service status asymmetry + add guard:**
Add a docstring note on `Service.initialize()` explaining the STARTING-on-return behavior. Add a runtime guard that detects `wait_ready()` called on a parent during child initialization and raises a clear error instead of deadlocking.

**F4 fix -- Document timeout multiplication:**
Add a config comment explaining max wall-clock = depth x timeout. No code change. Alternatively, add a `total_shutdown_timeout_seconds` config that wraps the top-level `Hassette.shutdown()` call.

**F5 fix -- Reset `_initializing` in `_finalize_shutdown()`:**
Add `self._initializing = False` to `_finalize_shutdown()` as defense-in-depth. This ensures a crashed resource can always be re-initialized.

**Pros:**
- Each fix is small, testable, and reviewable independently
- Minimal risk of introducing new bugs
- Can be shipped incrementally (F1 and F5 first, F2 and F3 later)

**Cons:**
- F2 requires a design decision about where `close_streams()` goes
- Does not solve the fundamental timeout multiplication issue (F4)
- The timeout handler race condition (F1) is mitigated but not eliminated -- cancelled finally blocks can still race with the cleanup attempts

**Effort estimate:** Medium -- 5 localized changes, each needs tests

**Dependencies:** None new

### Option B: Deadline propagation with unified shutdown path

**How it works:**

Introduce an absolute deadline mechanism inspired by Trio's cancel scopes. A single deadline is set at the top of the tree and propagated to all descendants.

1. Add `_shutdown_deadline: float | None = None` instance attribute to `LifecycleMixin`
2. `_finalize_shutdown()` computes the deadline on first entry and passes it to children via the instance attribute
3. Children's `_finalize_shutdown()` reads the inherited deadline instead of computing their own timeout
4. Hassette's `on_shutdown()` is simplified to just set the deadline and call `close_streams()` at the right time

```python
async def _finalize_shutdown(self) -> None:
    await self.cleanup()

    children = self._ordered_children_for_shutdown()
    if children:
        loop = asyncio.get_event_loop()
        timeout = self.hassette.config.resource_shutdown_timeout_seconds

        # Use inherited deadline or create a new one
        if self._shutdown_deadline is not None:
            deadline = self._shutdown_deadline
        else:
            deadline = loop.time() + timeout

        # Propagate deadline to children
        for child in children:
            child._shutdown_deadline = deadline

        remaining = max(0, deadline - loop.time())
        try:
            async with asyncio.timeout(remaining):
                results = await asyncio.gather(
                    *[child.shutdown() for child in children],
                    return_exceptions=True,
                )
                # ... handle results ...
        except TimeoutError:
            # ... cleanup timed-out children (F1 fix) ...

    self._shutdown_completed = True
    # ... handle_stop ...
```

For Hassette specifically, override `_finalize_shutdown()` to insert `close_streams()` after children finish:

```python
async def _finalize_shutdown(self) -> None:
    # Custom: cleanup, propagate to children, close streams, handle_stop
    await self.cleanup()
    # ... child propagation with deadline ...
    await self._event_stream_service.close_streams()
    self._shutdown_completed = True
    # handle_stop skipped -- streams already closed
```

And simplify `on_shutdown()`:
```python
async def on_shutdown(self) -> None:
    # No manual gather -- _finalize_shutdown handles children
    pass  # or just remove the override
```

**Pros:**
- Fixes F1, F2, and F4 in a single coherent design
- Max wall-clock is exactly 1x the configured timeout regardless of tree depth
- Uses `asyncio.timeout` context manager (no extra task creation)
- Eliminates the double-shutdown pattern entirely
- Aligns with structured concurrency best practices (Trio cancel scope pattern)

**Cons:**
- Larger change surface than Option A
- Override of `_finalize_shutdown()` on Hassette adds complexity
- `_shutdown_deadline` instance attribute is mutable state set by a parent on a child -- unusual pattern
- Needs careful testing of the edge case where deadline expires at different tree levels

**Effort estimate:** Large -- touches `base.py`, `mixins.py`, `core.py`; requires new tests for deadline propagation at multiple depths

**Dependencies:** None new

### Option C: Pragmatic middle ground

**How it works:**

Apply the incremental fixes from Option A, but use `asyncio.timeout` (context manager) instead of `asyncio.wait_for` to avoid the task-creation race condition, and add a simple top-level `total_shutdown_timeout_seconds` config for Hassette-level defense.

1. **F1:** Replace `asyncio.wait_for` with `asyncio.timeout` context manager. Add cleanup + handle_stop in the timeout handler.
2. **F2:** Move `close_streams()` to `after_shutdown()`. Let `_finalize_shutdown()` own child propagation with timeout. Add `_post_children_shutdown()` hook or just handle the stream closure ordering explicitly.
3. **F3:** Document + guard (same as Option A).
4. **F4:** Add `total_shutdown_timeout_seconds` config (default: 30s). Wrap `Hassette.shutdown()` in `asyncio.timeout(total)` as a safety net. Per-level timeouts remain for logging/diagnostics.
5. **F5:** Reset `_initializing` in `_finalize_shutdown()`.

The key difference from Option A: using `asyncio.timeout` context manager instead of `asyncio.wait_for` avoids creating a wrapper task. The cancellation is delivered directly to the current task, which means `finally` blocks in child `shutdown()` will run naturally without racing against a parent's timeout handler.

**From Python docs:** `asyncio.timeout()` cancels the current task by raising `TimeoutError` at the `async with` boundary. The gathered coroutines receive `CancelledError`, their `finally` blocks run, and then control returns to the timeout handler. This is cleaner than `asyncio.wait_for` which creates a new task.

**Pros:**
- Fixes all 5 findings
- Each change is localized and testable
- `asyncio.timeout` eliminates the task-creation race condition
- Top-level safety timeout provides defense-in-depth without full deadline propagation
- Lower risk than Option B

**Cons:**
- Does not solve timeout multiplication at intermediate levels (F4 is mitigated, not fixed)
- `total_shutdown_timeout_seconds` is a blunt instrument -- it doesn't help with diagnosing which level timed out
- `close_streams()` ordering requires careful verification

**Effort estimate:** Medium -- same scope as Option A but with `asyncio.timeout` migration

**Dependencies:** None new

## Concerns

### Technical risks

- **Race condition in timeout handler (F1):** Even with `asyncio.timeout`, the timeout handler runs cleanup on children that may still be executing their `finally` blocks from the CancelledError. The `_shutdown_completed` flag check (`if not child._shutdown_completed`) provides some protection, but there is a window between the child's `finally` block checking `_shutdown_completed=False` and the timeout handler setting it to `True`. This is a single-threaded event loop so no true data race, but the interleaving depends on task scheduling order.

- **Stream closure ordering (F2):** If `close_streams()` is moved out of `on_shutdown()`, there must be a point AFTER children stop but BEFORE the parent's `handle_stop()`. The natural place is inside `_finalize_shutdown()`, but only Hassette needs this. A Hassette-specific override or a new hook adds complexity.

- **`asyncio.timeout` vs `asyncio.wait_for` behavioral difference:** `asyncio.timeout` does NOT cancel internal tasks -- it raises `CancelledError` in the current task. When used with `gather`, the gather itself receives `CancelledError` and propagates it to all gathered coroutines. This is functionally equivalent to `wait_for` cancelling the wrapper task, but the scheduling is slightly different. Test coverage must verify both the happy path and the timeout path.

### Complexity risks

- **Deadline propagation (Option B)** adds a new concept (`_shutdown_deadline`) that every developer must understand when writing Resource/Service lifecycle code. The instance attribute pattern (parent sets child attribute before calling child method) is not used elsewhere in the codebase.

- **F2 fix** changes a shutdown contract that the design doc explicitly called a non-goal to change. The design doc says "Changing Hassette.on_shutdown()" is a non-goal. This decision needs to be revisited given the timeout bypass finding.

### Maintenance risks

- **Timeout handler cleanup attempts** (F1) add best-effort async operations in an already-failed path. If these cleanup attempts themselves hang, the safety timeout prevents indefinite blocking, but the child is left in a partially cleaned-up state. This is strictly better than no cleanup, but the "partially cleaned" state is a new failure mode.

## Open Questions

- [ ] Should `Hassette.on_shutdown()`'s manual gather be removed, or is the design doc's "non-goal" statement still binding? The finding shows the non-goal creates a timeout bypass.
- [ ] Is `asyncio.timeout` (context manager) safe to use with `asyncio.gather` in this pattern? The challenge review (Finding 9) suggests `wait_for` breaks the service watcher restart cascade test. Does `asyncio.timeout` avoid this?
- [ ] Should F4 (timeout multiplication) be solved with full deadline propagation (Option B), or is a top-level safety timeout sufficient for a tree with max depth 3-4?
- [ ] For F1, should the timeout handler attempt cleanup synchronously (blocking the parent's shutdown) or fire-and-forget via `task_bucket.spawn()`? Fire-and-forget risks the cleanup outliving the parent's shutdown.
- [ ] Does the STARTING orphan scenario (F5) have any real-world trigger, or is it purely theoretical? The code paths that could produce it (crash between handle_starting and handle_running in _serve_wrapper) seem to always transition to FAILED or CRASHED.

## Recommendation

**Option C (pragmatic middle ground)** is the best fit for this PR. It addresses all 5 findings with localized, testable changes while avoiding the complexity of full deadline propagation. The key improvements over Option A are:

1. Using `asyncio.timeout` instead of `asyncio.wait_for` to eliminate the task-creation race
2. Adding a top-level `total_shutdown_timeout_seconds` as defense-in-depth for F4
3. Moving `close_streams()` out of `on_shutdown()` to let `_finalize_shutdown` own child propagation for F2

Option B (deadline propagation) is the theoretically correct solution for F4 but adds complexity disproportionate to the benefit given the shallow tree (max 3-4 levels). It should be considered if/when the tree gets deeper or timeout multiplication becomes a practical problem.

The design doc's explicit non-goal of "Changing Hassette.on_shutdown()" should be revisited. The finding demonstrates that the non-goal was made without full awareness of the timeout bypass it creates. Suggest running `/mine.challenge` on the proposed approach before implementation.

### Suggested next steps

1. **Write a design doc via `/mine.design`** covering Option C with specific code changes for each finding
2. **Prototype the `asyncio.timeout` migration** in a branch to verify it doesn't break the service watcher restart cascade test (mentioned in Finding 9 of the challenge review)
3. **Decide on the `Hassette.on_shutdown()` question** -- this is a design decision that affects the scope of F2

## Sources

- [Coroutines and tasks -- Python 3.14 documentation](https://docs.python.org/3/library/asyncio-task.html) -- asyncio.wait_for, asyncio.timeout, asyncio.gather behavior
- [Timeouts and cancellation for humans -- njs blog](https://vorpus.org/blog/timeouts-and-cancellation-for-humans/) -- deadline propagation, cancel scopes, structured concurrency patterns
- [Trio reference documentation](https://trio.readthedocs.io/en/stable/reference-core.html) -- nursery cancellation and structured concurrency
- [Waiting in asyncio -- Hynek Schlawack](https://hynek.me/articles/waiting-in-asyncio/) -- practical asyncio patterns for waiting and timeout
- [Graceful Shutdown -- Trio forum](https://trio.discourse.group/t/graceful-shutdown/93) -- structured concurrency shutdown patterns
- [Why TaskGroup and Timeout Are Crucial in Python 3.11](https://www.dataleadsfuture.com/why-taskgroup-and-timeout-are-so-crucial-in-python-3-11-asyncio/) -- TaskGroup vs gather comparison
