# Design: Timeout Enforcement and Lifecycle Contract Fixes

**Date:** 2026-03-29
**Status:** approved
**Spec:** design/specs/2028-child-shutdown-propagation/design.md (parent design)
**Research:** design/research/2026-03-29-lifecycle-timeout-enforcement/research.md

## Problem

The child lifecycle propagation PR (#449) adds solid propagation logic, but its timeout enforcement path is incomplete. A challenge review surfaced 5 HIGH findings:

1. **Timeout force-patches without cleanup** (`base.py:268-277`) — sets flags and status but never calls `cleanup()` or `handle_stop()`. Task buckets, bus listeners, scheduler jobs, and caches leak. No STOPPED event is emitted, so monitoring consumers never learn the child stopped.

2. **Hassette double-shutdown bypasses timeout** — `Hassette.on_shutdown()` manually gathers `child.shutdown()` on all children (no timeout), then `_finalize_shutdown()` propagation runs the same children again (with timeout). The `_shutdown_completed` flag makes the second pass a no-op, meaning the PR's timeout enforcement never fires for Hassette's top-level children.

3. **Service.initialize() status asymmetry** — `Resource.initialize()` guarantees `RUNNING` on return. `Service.initialize()` defers `handle_running()` to the spawned serve task, returning while still `STARTING`. A Service child calling `await self.parent.wait_ready()` during `on_initialize` deadlocks.

4. **Timeout budget multiplication** — Each tree level applies its own independent `asyncio.wait_for(timeout=resource_shutdown_timeout_seconds)`. A depth-4 tree blocks for up to 4x the configured timeout.

5. **STARTING children orphaned on restart** — `initialize()` skips children with status `STARTING`. A child stuck in `STARTING` after a crash is silently orphaned on restart.

These gaps undermine the lifecycle contract the propagation PR establishes. The timeout was described as "defense-in-depth" in the parent design, but the recovery path was never designed.

## Non-Goals

- **Full deadline propagation** — passing an absolute deadline through the tree (Option B from research) is the theoretically correct solution for F4, but overkill for a tree with max depth 3-4. Option C's top-level safety timeout is sufficient. Deadline propagation remains a valid future migration path.
- **New lifecycle hooks beyond `_between_children_and_stop()`** — no `after_children_shutdown()` or `post_children_initialize()` hooks beyond the single protected hook needed for Hassette's `close_streams()` ordering.
- **Changing `shutdown()` or `initialize()` signatures** — both are `@final` and must remain `async def shutdown(self) -> None`.

## Architecture

### 1. Switch from `asyncio.wait_for` to `asyncio.timeout` Context Manager

**Problem:** `asyncio.wait_for` creates a wrapper task, which changes event loop scheduling. This caused a test failure in `test_bus_driven_failed_events_trigger_shutdown_after_max_attempts` when we attempted to wrap `cleanup()` in `wait_for`.

**Fix:** Replace `asyncio.wait_for(asyncio.gather(...), timeout=timeout)` in `_finalize_shutdown()` with `async with asyncio.timeout(timeout)`. The context manager does not create a new task — it raises `TimeoutError` at the `async with` boundary, and `CancelledError` propagates naturally to gathered coroutines. Their `finally` blocks run without racing against a parent's timeout handler.

```python
# base.py: _finalize_shutdown()
# Before:
try:
    results = await asyncio.wait_for(
        asyncio.gather(*[child.shutdown() for child in children], return_exceptions=True),
        timeout=timeout,
    )
    ...
except TimeoutError:
    ...

# After:
try:
    async with asyncio.timeout(timeout):
        results = await asyncio.gather(
            *[child.shutdown() for child in children],
            return_exceptions=True,
        )
        ...
except TimeoutError:
    ...
```

Also wrap the `cleanup()` call in `Resource._finalize_shutdown()` (the base class, not just Hassette's override) with `asyncio.timeout`. This protects against a hung `task_bucket.cancel_all()` or `_init_task` drain (both async) at any level of the tree. **Note:** `asyncio.timeout` cannot interrupt synchronous calls — `cache.close()` (SQLite WAL checkpoint) is synchronous and uninterruptible by this mechanism. Running it in a thread executor is a potential future improvement if this becomes a practical issue:

```python
# base.py: Resource._finalize_shutdown()
timeout = self.hassette.config.resource_shutdown_timeout_seconds
try:
    async with asyncio.timeout(timeout):
        await self.cleanup()
except TimeoutError:
    self.logger.warning("cleanup() timed out after %ss for %s", timeout, self.unique_name)
except Exception as e:
    self.logger.exception("Error during cleanup: %s %s", type(e).__name__, e)
```

### 2. Best-Effort Cleanup and STOPPED Event in Timeout Handler

**Problem:** The timeout handler at `base.py:272-277` force-patches flags but skips `cleanup()` (task cancellation, cache close) and `handle_stop()` (STOPPED event emission). Resources leak; monitoring consumers never learn the child stopped.

**Fix:** After the timeout fires, recursively force all timed-out children (and their descendants) into a terminal state. Use a `_force_terminal()` method on `Resource` that walks the full subtree. Making it a method (not a free function) lets `Service` override it to also cancel `_serve_task`:

```python
# base.py: Resource
def _force_terminal(self) -> None:
    """Recursively force this resource and all descendants to STOPPED terminal state.

    Cancels tasks for resources that were never given a shutdown signal (grandchildren).
    Service overrides this to also cancel _serve_task.
    """
    if self._shutdown_completed:
        return
    # Cancel tasks — safe for resources that never entered shutdown()
    self.cancel()
    self.task_bucket.cancel_all_sync()  # fire-and-forget, non-awaited
    self._shutting_down = False
    self._shutdown_completed = True
    self.status = ResourceStatus.STOPPED
    self.mark_not_ready("shutdown timed out")
    for child in self.children:
        child._force_terminal()

# base.py: Service
def _force_terminal(self) -> None:
    """Override to also cancel the serve task."""
    if self._serve_task and not self._serve_task.done():
        self._serve_task.cancel()
    super()._force_terminal()
```

The timeout handler becomes:

```python
except TimeoutError:
    self.logger.error("Timed out waiting for children to shut down after %ss", timeout)
    for child in children:
        child._force_terminal()
```

**Note:** `cancel()` and `task_bucket.cancel_all_sync()` are non-awaited cancellation requests — they do not race with `cleanup()` because grandchildren (whose `shutdown()` was never called) have no in-flight cleanup. For direct children (whose `finally` blocks may be running), the `_shutdown_completed` check short-circuits before any mutation.

**Design decision: Skip best-effort cleanup in the timeout handler.** The challenge review (Finding 6) identified that calling `child.cleanup()` in the timeout handler races with the child's own `finally` block, which is already running `_finalize_shutdown()` -> `cleanup()` after receiving `CancelledError`. Since `cleanup()` has no re-entrancy guard, concurrent calls from two paths are unsafe. Instead, the timeout handler only force-patches state flags. The child's own `finally` block handles whatever cleanup it can before being cancelled.

**Race condition note:** When `asyncio.timeout` fires on the gather, the gathered coroutines receive `CancelledError`. Their `finally` blocks attempt `_finalize_shutdown()`, but since `_finalize_shutdown()` itself awaits `cleanup()` and `handle_stop()`, these are also cancelled. The `_shutdown_completed` flag check in `_force_terminal_state()` ensures we skip children that completed on their own.

### 3. Remove Manual Gather from `Hassette.on_shutdown()`

**Problem:** `Hassette.on_shutdown()` manually gathers `child.shutdown()` on all children with no timeout. `_finalize_shutdown()` propagation then runs the same children again (no-op due to `_shutdown_completed`). The timeout enforcement in `_finalize_shutdown` never fires for Hassette's top-level children.

**Fix:** Remove the manual gather from `Hassette.on_shutdown()`. Let `_finalize_shutdown()` own child propagation with timeout. Handle the `close_streams()` ordering constraint via a protected `_on_children_stopped()` hook in `Resource._finalize_shutdown()`.

The ordering constraint: `close_streams()` must run AFTER all children emit STOPPED events (via their own `handle_stop()` in `_finalize_shutdown()`) but BEFORE the parent Hassette's `handle_stop()`.

**Hook in Resource._finalize_shutdown():**

Add a protected `_on_children_stopped()` hook called after child propagation completes (or times out) but before `handle_stop()`. Default is a no-op. Hassette overrides it to close streams.

```python
# base.py: Resource._finalize_shutdown()
async def _finalize_shutdown(self) -> None:
    """Common shutdown cleanup: cancel tasks, propagate to children, emit stopped event."""
    timeout = self.hassette.config.resource_shutdown_timeout_seconds
    try:
        async with asyncio.timeout(timeout):
            await self.cleanup()
    except TimeoutError:
        self.logger.warning("cleanup() timed out after %ss for %s", timeout, self.unique_name)
    except Exception as e:
        self.logger.exception("Error during cleanup: %s %s", type(e).__name__, e)

    # Propagate shutdown to children
    children = self._ordered_children_for_shutdown()
    children_timed_out = False
    if children:
        try:
            async with asyncio.timeout(timeout):
                results = await asyncio.gather(
                    *[child.shutdown() for child in children],
                    return_exceptions=True,
                )
                for child, result in zip(children, results, strict=True):
                    if isinstance(result, Exception):
                        self.logger.error("Child %s shutdown failed: %s", child.unique_name, result)
        except TimeoutError:
            children_timed_out = True
            self.logger.error("Timed out waiting for children to shut down after %ss", timeout)
            for child in children:
                if not child._shutdown_completed:
                    _force_terminal_state(child)

    self._shutdown_completed = True
    if self._initializing:
        if self.shutdown_event.is_set():
            self.logger.debug("%s shutting down with _initializing=True (shutdown requested during init)", self.unique_name)
        else:
            self.logger.warning("%s shutting down with _initializing=True — this indicates a bug", self.unique_name)
        self._initializing = False

    # Hook runs only on clean shutdown — not after timeout, where children
    # are force-patched and may still have running tasks. The Hassette total
    # timeout's finally block handles close_streams() as a fallback.
    if not children_timed_out:
        await self._on_children_stopped()

    if not self.hassette.event_streams_closed:
        try:
            await self.handle_stop()
        except Exception as e:
            self.logger.exception("Error during stopping %s %s", type(e).__name__, e)
    else:
        self.logger.debug("Skipping STOPPED event as event streams are closed")

async def _on_children_stopped(self) -> None:
    """Called after children shut down cleanly, before this resource's STOPPED event.

    Only runs on the success path — skipped when child propagation times out
    (the timeout handler force-patches children and the caller handles fallback
    teardown, e.g., Hassette's finally block calls close_streams()).

    Override to run logic that must happen after children are shut down but
    before the parent emits its own STOPPED event. Default is a no-op.
    Overrides MUST call await super()._on_children_stopped().

    Note: _finalize_shutdown() is intentionally not @final — this hook exists
    so subclasses do NOT need to override _finalize_shutdown() for post-children
    behavior.
    """
    pass
```

**Hassette uses the hook:**

```python
# core.py: Hassette

async def on_shutdown(self) -> None:
    """Shutdown hook — no longer manually shuts down children.
    Child shutdown is handled by _finalize_shutdown() propagation with timeout.
    """
    pass  # Children are shut down by _finalize_shutdown()

async def _on_children_stopped(self) -> None:
    """Close event streams after children have emitted their STOPPED events."""
    await self._event_stream_service.close_streams()
```

This replaces the ~50-line `_finalize_shutdown()` override with a 3-line hook override. All child propagation logic stays in the base class.

**Key change from parent design:** The parent design doc explicitly listed "Changing `Hassette.on_shutdown()`" as a non-goal, accepting the double-shutdown behavior. This design revisits that decision because the challenge review demonstrated that the non-goal creates a timeout bypass — the timeout enforcement added by the PR never fires for Hassette's top-level children, which is where it matters most.

**`before_shutdown` is unchanged:** `Hassette.before_shutdown()` removes bus listeners and finalizes the session. This still runs before `_finalize_shutdown()` via the `shutdown()` hook chain.

### 4. Top-Level Safety Timeout for Hassette Shutdown

**Problem:** Each tree level applies its own independent timeout. A depth-4 tree can block for up to 4x the configured timeout. Max depth in practice is 3-4 (Hassette -> AppHandler -> AppLifecycleService -> Bus).

**Fix:** Add a `total_shutdown_timeout_seconds` config value (default: 30s) as a top-level safety net. Hassette overrides `shutdown()` (via a `FinalMeta` exemption, mirroring the existing `Service` exemption) to wrap the entire shutdown call in `asyncio.timeout`. Per-level timeouts remain for diagnostics — they tell you which level timed out. The top-level timeout ensures the total wall-clock never exceeds the configured bound.

This approach keeps `_finalize_shutdown()` un-overridden — consistent with the Section 3 guidance that subclasses should use `_on_children_stopped()` instead.

```python
# config.py
total_shutdown_timeout_seconds: int = 30
"""Maximum wall-clock seconds for the entire Hassette shutdown (hooks + propagation).
Individual resource_shutdown_timeout_seconds still applies per-level for diagnostics."""
```

```python
# base.py: FinalMeta.__init__
# Add Hassette exemption alongside the existing Service exemption:
if subclass_name in ("hassette.resources.base.Service", "hassette.core.core.Hassette"):
    return
```

```python
# core.py: Hassette
@final
async def shutdown(self) -> None:
    """Override to wrap the entire shutdown in a total timeout.

    FinalMeta exempts Hassette from the @final on Resource.shutdown().
    This ensures hooks + child propagation + cleanup all share one budget.
    """
    try:
        async with asyncio.timeout(self.config.total_shutdown_timeout_seconds):
            await super().shutdown()
    except TimeoutError:
        self.logger.critical(
            "Total shutdown timeout (%ss) exceeded — forcing termination",
            self.config.total_shutdown_timeout_seconds,
        )
        # Force-patch any remaining children and their descendants
        for child in self.children:
            child._force_terminal()
    finally:
        # _shutdown_completed FIRST — prevents re-entry regardless of what follows.
        self._shutdown_completed = True
        # Emit Hassette's own STOPPED event while streams are still open,
        # then close streams and set terminal status.
        if not self.event_streams_closed:
            with suppress(Exception):
                await self.handle_stop()
        with suppress(Exception):
            await self._event_stream_service.close_streams()
        self.status = ResourceStatus.STOPPED
        self.mark_not_ready("shutdown complete")
```

**Note:** `_on_children_stopped()` is called inside `_finalize_shutdown()` (via `super().shutdown()`) only on the clean path. On total timeout, `close_streams()` is handled by this `finally` block.

### 5. Document Service.initialize() Status Asymmetry + Deadlock Guard

**Problem:** `Service.initialize()` returns while status is still `STARTING` (deferred to `_serve_wrapper`). A child calling `await self.parent.wait_ready()` during `on_initialize` deadlocks.

**Why this is intentional:** Services are ready when `serve()` is actually running, not when `initialize()` returns. WebsocketService marks ready only after authenticating with Home Assistant — that happens inside `serve()`. Moving `handle_running()` before `serve()` starts would lie about the Service's status.

**Fix:** Document the asymmetry. No runtime guard — the deadlock is a programming error detectable at development time, and a runtime guard has unacceptable false-positive risk (fires for legitimate external `wait_ready()` callers during startup).

Docstring addition to `Service.initialize()`:

```python
async def initialize(self) -> None:
    """NOTE: Unlike Resource.initialize(), Service.initialize() returns while
    status is still STARTING.  handle_running() is called by _serve_wrapper()
    when serve() actually begins.  Children MUST NOT call
    self.parent.wait_ready() during their on_initialize — this will deadlock
    because the parent's readiness depends on serve() running, which cannot
    start until child initialization completes.

    Keep flag resets and child propagation in sync with Resource.initialize().
    """
```

Add a test asserting that `Service` status is `STARTING` after `initialize()` returns (mirrors the existing `test_init_propagation_runs_before_handle_running` for Resource).

### 6. Reset `_initializing` in `_finalize_shutdown()` as Defense-in-Depth

**Problem:** If a child is stuck in `STARTING` after a crash (between `handle_starting` and `handle_running` in `_serve_wrapper`), `initialize()` skips it during restart. If `_initializing` is also left True, the child's next `initialize()` returns immediately.

**Actual severity:** Lower than originally stated. The `_serve_wrapper` catches all exceptions and transitions to FAILED/CRASHED, so the STARTING orphan requires a very specific failure mode. The `_initializing` flag is always reset by the `finally` block in `initialize()`. But defense-in-depth is cheap.

**Fix:** Add `self._initializing = False` to `_finalize_shutdown()` with a warning log when the flag is unexpectedly True. Silent resets mask bugs; a warning makes the anomaly visible:

```python
async def _finalize_shutdown(self) -> None:
    ...
    self._shutdown_completed = True
    if self._initializing:
        self.logger.warning("%s shutting down with _initializing=True — this indicates a bug", self.unique_name)
        self._initializing = False
    ...
```

The scenario that bypasses `initialize()`'s `finally` block (cancellation before the `try` block is entered) has no `await` points in the current code, making it unreachable. The warning ensures that if this changes, the anomaly is visible rather than silently fixed.

## Alternatives Considered

**Option B: Full deadline propagation** — Pass an absolute deadline (`loop.time() + timeout`) from the top of the tree to all descendants via a `_shutdown_deadline` instance attribute. Each level computes `remaining = deadline - now` instead of using its own timeout. Rejected for now: the tree is max 3-4 levels deep, and the top-level safety timeout achieves the same bound. Deadline propagation is a valid future migration if the tree deepens.

**Full `_finalize_shutdown()` override on Hassette** — Override the entire method to insert `close_streams()` at the right point. Rejected after challenge review: duplicates ~50 lines of lifecycle-critical code from the base class, creating a maintenance trap that silently diverges on future changes. The `_on_children_stopped()` hook achieves the same result with 3 lines.

**Keep `Hassette.on_shutdown()` as-is** — The parent design doc's non-goal. Rejected because the challenge review demonstrated that the double-shutdown bypasses timeout enforcement for the resources that matter most (Hassette's direct children).

## Test Strategy

**Unit tests (new):**
- `asyncio.timeout` migration: verify timeout fires and children are cleaned up (replaces existing `wait_for` timeout test)
- Best-effort cleanup in timeout handler: verify `cleanup()` and `handle_stop()` are called on timed-out children; verify STOPPED event is emitted
- `Hassette._finalize_shutdown()` override: verify `close_streams()` runs after children stop
- Top-level safety timeout: verify `total_shutdown_timeout_seconds` caps wall-clock time
- Service status after `initialize()`: assert `STARTING`, not `RUNNING`
- Deadlock guard in `wait_ready()`: verify `RuntimeError` raised when called from initializing parent
- `_initializing` reset: verify flag is cleared in `_finalize_shutdown()`

**Integration tests (update):**
- `TestHassetteShutdownIdempotent`: update to verify single-pass shutdown (no longer double-shutdown)
- Restart round-trip: verify children survive restart with `_initializing` reset
- Full Hassette shutdown: verify `close_streams()` ordering (children STOPPED events delivered before stream close)

**Existing tests to verify:**
- `test_bus_driven_failed_events_trigger_shutdown_after_max_attempts` — pre-existing flaky test (fails with random ordering on unmodified code). The `asyncio.timeout` migration should not make this worse. Run 10x to verify.

## Open Questions

- **`asyncio.timeout` + `asyncio.gather` interaction** (GATE — must resolve before implementation): The switch from `asyncio.wait_for` to `asyncio.timeout` is the architectural justification for this design. Before implementing, write the `asyncio.timeout(gather(...))` replacement in isolation and run `test_bus_driven_failed_events_trigger_shutdown_after_max_attempts` 50x with `pytest-repeat` to confirm the scheduling behavior doesn't reproduce the `wait_for` quirk. If it does, fall back to the existing `asyncio.wait_for` pattern and accept the test flakiness as a known limitation.

## Impact

**Files modified:**
- `src/hassette/resources/base.py` — `Resource._finalize_shutdown()`: switch to `asyncio.timeout`, wrap `cleanup()` in timeout, add `_force_terminal()` method + Service override, add `_on_children_stopped()` hook, add `_initializing` warning+reset. `FinalMeta`: add Hassette exemption for `shutdown()` override.
- `src/hassette/core/core.py` — `Hassette.on_shutdown()`: remove manual gather. `Hassette._on_children_stopped()`: new 3-line hook override for `close_streams()`. `Hassette.shutdown()`: total timeout wrapper via FinalMeta exemption.
- `src/hassette/config/config.py` — add `total_shutdown_timeout_seconds` config
- `tests/unit/resources/test_lifecycle_propagation.py` — update timeout tests, add Service status test, add deadlock guard test
- `tests/integration/test_lifecycle_propagation.py` — update Hassette shutdown idempotency test, add close_streams ordering test

**Files unchanged:**
- `src/hassette/app/app.py` — App.cleanup() already delegates to super()
- `src/hassette/scheduler/scheduler.py`, `src/hassette/bus/bus.py` — on_shutdown hooks are correct
- `src/hassette/core/state_proxy.py` — no changes needed (the Finding 10 idempotent subscribe fix is already applied separately)

**Blast radius:** Medium. Changes to `_finalize_shutdown()` affect all Resource subclasses. The Hassette override is isolated. The `wait_ready()` guard is additive and won't break existing code (no existing code calls `wait_ready()` on a parent during child initialization).
