# Context: Sync Handler Timeout — Visibility, Containment, and Shutdown Interruption

## Problem & Motivation

A timeout on a sync handler does not bound the handler's real execution time. When `asyncio.timeout(cmd.effective_timeout)` fires at `command_executor.py:268`, the caller's await unblocks and telemetry records `status='timed_out'`, but the sync handler runs in a worker thread via `asyncio.to_thread` (`task_bucket.py:176`), and `concurrent.futures` cannot cancel a started thread. The worker runs to completion and holds its slot. Two problems follow: the leak is invisible (nothing tells an operator the thread is still alive), and there is no blast-radius containment (sync handlers share asyncio's default pool with framework internals, and Hassette owns no executor it can interrupt at shutdown, so a blocking handler can hang shutdown). This was originally intentional (`design/specs/036-execution-timeouts/design.md:184`).

## Visual Artifacts

None.

## Key Decisions

1. **Dedicated executor owned by a `Service`, not the loop default.** A new `SyncExecutorService` owns a ported `InterruptibleThreadPoolExecutor`. Framework-internal `asyncio.to_thread` calls (logging, DB) stay on the loop default pool; only sync *user* code (handlers, jobs, App sync lifecycle hooks — all of which flow through `TaskBucket.run_in_thread`) routes to the dedicated executor.
2. **Shutdown ordering is declarative.** `BusService`, `SchedulerService`, and `AppHandler` declare `depends_on=[SyncExecutorService]`, so wave-based shutdown tears them down *before* the executor — no AppSync hook can submit to a closed pool. The executor is constructed in the service's `__init__` (no `None` window).
3. **Shutdown-only interruption, ported from Home Assistant.** At shutdown, worker threads still alive after a join budget get `async_raise(thread.ident, SystemExit)` (HA `~/source/core/homeassistant/util/thread.py:38-55`). This is safe because no new work is scheduled at shutdown (no tid-reuse race). Per-call mid-runtime interruption is explicitly OUT of scope.
4. **Observability via thread-liveness, not future plumbing.** `run_in_thread` records the worker thread (ContextVar/closure); the command layer checks `thread.is_alive()` at the timeout site. A distinct `thread_leaked` column on the executions table (new migration `004.sql`) records the leak, kept separate from `status` so the `status='timed_out'` contract is preserved.
5. **Saturation has two triggers.** A submission-time check plus a periodic probe in the service's `serve()` loop, because a submission-only check goes silent exactly when the pool is fully starved.
6. **Budget plumbing is adapted, not verbatim.** HA's `join_threads_or_timeout` reads a module constant; the port takes a `timeout: float` parameter. A `@model_validator` enforces `sync_executor_shutdown_timeout_seconds < total_shutdown_timeout_seconds`.

## Constraints & Anti-Patterns

- **Do NOT swap the loop-default executor.** `asyncio.to_thread` callers (logging_service, database_service) must keep hitting the default pool.
- **Do NOT call `async_raise` mid-runtime** against the live reused pool — that is the rejected tid-reuse race. Shutdown only.
- **Interrupt exception is `SystemExit`** (a `BaseException`) — an `Exception` subclass would be swallowed by handler `except Exception` blocks.
- **`SystemExit` runs `finally`/`__exit__` blocks** before the thread dies — a half-completed external side effect can survive restart. Document this; do not treat `finally` as proof of clean completion.
- **Shutdown interruption must never propagate.** Suppress benign `SystemError`/`ValueError` (including `async_raise`'s `res == 0` "thread not found" path).
- **Do NOT implement per-call mid-runtime interruption** (Non-Goal). It would replace, not extend, this pool architecture.
- **Do NOT run `pytest -n auto`** — it has frozen this machine. Run specific files/markers; let CI run heavy suites. Core changes also require `nox -s system` and `nox -s e2e` before shipping.

## Design Doc References

- `## Architecture` — the dedicated executor (Service-owned), routing seam, observability mechanism, saturation gauge, shutdown interruption, config.
- `## Migration` — the new `thread_leaked` column and forward-only migration approach.
- `## Edge Cases` — not-started timeout, total pool starvation, `res == 0`/`res > 1`, C-blocked threads.
- `## Key Constraints` — anti-patterns, `SystemExit`/`finally` semantics.
- `## Test Strategy` — existing tests to adapt, new coverage mapped to FR#N.
- `## Impact` — changed files, behavioral invariants, blast radius.

## Convention Examples

### Exception-tier execution contract

**Source:** `src/hassette/core/command_executor.py`

```python
try:
    async with track_execution(known_errors=known) as result:
        result.execution_id = execution_id
        async with asyncio.timeout(cmd.effective_timeout):
            await fn()
except asyncio.CancelledError:
    self.enqueue_record(self.build_record(cmd, result, execution_start_ts, execution_id))
    raise
except Exception:  # noqa: S110 — intentional: ExecutionResult populated and error logged upstream
    pass
if result.is_timed_out:
    if cmd.effective_timeout is not None:
        self.log_timeout_rate_limited(cmd, result)
```

### Sync/async adapter branch (the seam to reroute)

**Source:** `src/hassette/task_bucket/task_bucket.py`

```python
@functools.wraps(cast("Callable[..., object]", fn))
async def _sync_fn(*args: P.args, **kwargs: P.kwargs) -> R:
    try:
        return await self.run_in_thread(cast("Callable[P, R]", fn), *args, **kwargs)
    except TimeoutError:
        raise
    except Exception:
        self.logger.exception("Error in sync function '%s'", getattr(fn, "__name__", repr(fn)))
        raise
```

### Rate-limited WARNING with lazy eviction (the saturation gauge mirrors this)

**Source:** `src/hassette/core/command_executor.py` (`log_timeout_rate_limited`)

```python
now = time.monotonic()
stale_ids = [k for k, ts in self._timeout_warn_timestamps.items() if now - ts > _TIMEOUT_WARN_SUPPRESS_SECS]
for k in stale_ids:
    del self._timeout_warn_timestamps[k]
last_ts = self._timeout_warn_timestamps.get(entity_id)
if last_ts is not None and now - last_ts < _TIMEOUT_WARN_SUPPRESS_SECS:
    return  # suppressed
self._timeout_warn_timestamps[entity_id] = now
self.logger.warning(...)
```

### Config field + cross-field validator

**Source:** `src/hassette/config/models.py` (`LifecycleConfig`, validator pattern at `:208-215`)

```python
@model_validator(mode="after")
def fill_event_defaults(self) -> "LoggingConfig":
    if self.all_hass_events is None:
        self.all_hass_events = self.all_events
    return self
```

### Service declaration (template for SyncExecutorService)

**Source:** `src/hassette/core/bus_service.py`

```python
class BusService(Service):
    depends_on: ClassVar[list[type["Resource"]]] = [DatabaseService]
    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.PERMANENT,
        budget_intensity=2,
        budget_period_seconds=30,
    )

    async def serve(self) -> None:
        self.mark_ready(reason="...")
        while True:
            if self.shutdown_event.is_set():
                return
            ...
```
