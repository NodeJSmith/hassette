# Design: Sync Handler Timeout — Visibility, Containment, and Shutdown Interruption

**Date:** 2026-06-15
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-06-15-sync-handler-timeout/research.md

> Parenthetical `(Finding N)` tags below trace a decision to the adversarial `/mine.challenge` review of this design — they are provenance markers, not references to an external document. `design.md:NNN` citations without a path point at `design/specs/036-execution-timeouts/design.md` (the prior timeouts spec), not this file.

## Problem

A timeout on a sync handler does not bound the handler's real execution time — it is a silent no-op against the work itself. When `asyncio.timeout(cmd.effective_timeout)` fires at `command_executor.py:268`, the caller's await unblocks, telemetry records `status='timed_out'`, and a rate-limited WARNING logs. But the sync handler runs in a worker thread via `asyncio.to_thread` (`task_bucket.py:176`), and `concurrent.futures` cannot cancel a thread once it has started. The worker runs the blocking call to natural completion and holds its slot the whole time.

Two consequences matter:

1. **The leak is invisible.** Nothing tells an operator that a timed-out sync handler's thread is still alive and consuming a slot. The timeout looks enforced; it isn't.
2. **There is no blast-radius containment.** Sync handlers run on asyncio's *shared default* `ThreadPoolExecutor` — the same pool used by framework internals (logging, database). A storm of slow sync handlers can starve framework work, and Hassette has no owned executor to interrupt at shutdown, so a thread blocked in user code can hold up a clean shutdown.

This is confirmed and was originally intentional: `design/specs/036-execution-timeouts/design.md:184` documents the leak, and `task_bucket.py:209` carries the comment "no task to cancel anymore."

## Goals

- A timed-out sync handler whose worker thread is still alive past its timeout is surfaced through telemetry and logs — the leak becomes observable.
- Sync user code runs on a dedicated Hassette-owned executor, isolated from the framework's default pool, so slow handlers cannot starve framework internals.
- Pool saturation (active workers approaching the configured ceiling) is surfaced before exhaustion.
- At shutdown, worker threads still blocking the shutdown are interrupted on a best-effort, time-budgeted basis using Home Assistant's `async_raise(SystemExit)` pattern, so a blocking sync handler cannot hang the process indefinitely.

## Non-Goals

- **Per-call mid-runtime thread interruption.** Forcibly killing a worker the moment a per-handler timeout fires is explicitly deferred. It carries a thread-ID-reuse race the original design rejected (`design.md:186`), requires a single-use-thread executor to be safe, and cannot interrupt C-blocked IO anyway. Revisit only if the observability shipped here shows meaningful Python-bound (non-C-blocked) runaway handlers. **If it is later implemented, it replaces — not extends — this design's reusable `InterruptibleThreadPoolExecutor`** (Finding 9): per-call safety requires a single-use-thread-per-call dispatcher, so the pool, routing, and shutdown logic here are not an extension point for that change. Future engineers should plan a replacement, not a graft.
- **Interrupting C-blocked threads at shutdown beyond best-effort.** `PyThreadState_SetAsyncExc` only delivers at the next Python bytecode boundary; a thread blocked in a C call (`socket.recv`, `time.sleep`, a native DB driver) will not be interrupted until it returns to Python. Shutdown interruption is best-effort within a budget, matching HA.
- **Changing the default executor for framework-internal `asyncio.to_thread` calls** (logging, database). Those stay on the loop default pool.
- **Registration-time warnings discouraging sync handlers.** Out of scope for this change.

## User Scenarios

### Operator: runs a Hassette instance with user automations

- **Goal:** know when a sync handler misbehaves and trust that shutdown completes.
- **Context:** monitoring a live instance via logs and the telemetry UI.

#### A sync handler exceeds its timeout and keeps running

1. **A sync handler blocks past its timeout.**
   - Sees: the existing timeout WARNING, plus a new signal that the worker thread is still alive after the timeout fired.
   - Decides: whether to investigate the handler or raise its timeout.
   - Then: the execution record carries a distinct marker (the thread outlived the timeout), queryable later.

2. **The sync-handler pool nears saturation.**
   - Sees: a rate-limited WARNING that active sync-handler workers are approaching the configured ceiling.
   - Decides: whether to raise the pool size or fix the slow handlers.
   - Then: continues operating; the warning recurs (rate-limited) while saturation persists.

#### Operator shuts the instance down while a sync handler is blocking

1. **Operator triggers shutdown (signal or operator action) while a worker thread is mid-handler.**
   - Sees: the normal shutdown sequence; if a worker is still alive after the join budget, a WARNING naming the thread and its stack, then a best-effort interrupt.
   - Decides: nothing — shutdown proceeds within its budget.
   - Then: the process exits within the total shutdown budget instead of hanging on a blocking thread (for Python-level work; C-blocked work is logged and abandoned at budget expiry).

## Functional Requirements

- **FR#1** Sync user code submitted through `TaskBucket.run_in_thread` runs on a dedicated Hassette-owned thread-pool executor, not asyncio's loop-default executor.
- **FR#2** Framework-internal blocking calls that use `asyncio.to_thread` directly (logging, database) continue to run on the loop-default executor, unchanged.
- **FR#3** When a sync handler's timeout fires and its worker thread is still alive after the await is cancelled, the system emits an observable signal (log and a distinct field/status on the execution record) indicating the thread outlived the timeout.
- **FR#4** When active workers in the dedicated executor approach the configured pool ceiling, the system emits a rate-limited saturation WARNING.
- **FR#5** The dedicated executor is created during Hassette startup and shut down during Hassette teardown as part of the existing lifecycle.
- **FR#6** During shutdown, worker threads in the dedicated executor that remain alive after a join budget are interrupted best-effort via `async_raise(SystemExit)`, with the thread name and stack logged before interruption.
- **FR#7** Shutdown interruption completes within a bounded wall-clock budget and never raises out of the shutdown path; benign `SystemError`/`ValueError` races from `async_raise` are suppressed.
- **FR#8** The dedicated executor's pool size and the shutdown interruption budget are configurable via `LifecycleConfig`, with defaults that preserve current behavior characteristics (pool size comparable to the prior default-executor sizing).
- **FR#9** The timeout still fires as a caller-visible signal exactly as today (the await unblocks, `status='timed_out'` is recorded, the existing WARNING logs) — this behavior is preserved, not replaced.

## Edge Cases

- **Timeout fires before the worker dequeues the callable.** The thread may not yet be running the target; the "thread alive past timeout" signal must not misfire for work that never started. Detect via the executor future's running state, not a bare timer.
- **Worker finishes naturally a moment after the timeout.** The leak signal is racy by nature; treat it as best-effort observability, not a hard guarantee. A brief grace check is acceptable.
- **Thread dies between the shutdown liveness check and the `async_raise` call.** Suppress `SystemError`/`ValueError` (HA does the same — benign race). This also covers `async_raise`'s `res == 0` ("Thread not found") path, which raises `ValueError`: a thread that vanished before the raise landed is already gone, so suppression is the intended policy, not a swallowed error.
- **C-blocked worker at shutdown.** `async_raise` cannot interrupt it; log it and abandon at budget expiry. The process still exits via the normal shutdown completion.
- **`async_raise` returns `res > 1`.** Revert with `SetAsyncExc(tid, None)` and raise `SystemError` (ported verbatim from HA) — must not corrupt interpreter state.
- **Pool saturated at submission time.** Submitting more sync work queues it (standard `ThreadPoolExecutor` behavior); the saturation warning is the operator's signal. No work is dropped.
- **Total pool starvation.** If every worker blocks (e.g. all on slow handlers), *all* sync handlers and sync jobs for *all* apps stop firing, and new sync work queues unbounded until a slot frees or shutdown. This is a different failure shape than today's shared pool — isolation contains blast radius from framework internals but concentrates it across all sync user code. Nothing reclaims a leaked slot before shutdown (per-call interruption is a Non-Goal). The periodic saturation probe (see Architecture) is the operator's recovery signal; the recourse is to raise `sync_executor_max_workers`, fix the handler, or move it to async. "Contained" means isolated, not smaller.
- **Test helper that stubs `make_async_adapter` as identity** (`test_utils/helpers.py:451`) bypasses the executor entirely; executor behavior needs tests that exercise the real path.

## Acceptance Criteria

- **AC#1** A sync handler that blocks past its timeout produces an execution record distinguishable from a clean timeout (a field/status indicating the thread outlived the timeout), verified against the real executor path. (FR#3)
- **AC#2** Sync user code runs on the dedicated executor and framework `asyncio.to_thread` calls run on the default executor, verified by thread/pool identity in a test. (FR#1, FR#2)
- **AC#3** With the pool near its ceiling, a rate-limited saturation WARNING is emitted; it does not spam on every submission. (FR#4)
- **AC#4** A worker thread running a Python-level busy loop at shutdown is interrupted within the shutdown budget and the process exits cleanly; the thread name and stack are logged before interruption. (FR#6, FR#7)
- **AC#5** A worker thread blocked in a C call at shutdown is logged and abandoned at budget expiry; shutdown still completes within `total_shutdown_timeout_seconds`. (FR#6, FR#7, Non-Goals)
- **AC#6** Configuring a non-default pool size and shutdown budget changes behavior accordingly; defaults preserve current characteristics. (FR#8)
- **AC#7** The existing timeout signal path is unchanged: caller unblocks, `status='timed_out'` recorded, existing WARNING logged. (FR#9)

## Key Constraints

- **Do not swap the loop-default executor.** Framework internals depend on `asyncio.to_thread` hitting the default pool; route sync user code through the dedicated executor explicitly (`loop.run_in_executor(dedicated, ...)`), leaving `asyncio.to_thread` alone.
- **`async_raise` is shutdown-only.** Do not call it mid-runtime against a live, reused pool — that is the rejected tid-reuse race. It is safe at shutdown because no new work is scheduled.
- **The interrupt exception is `SystemExit` (a `BaseException`).** A subclass of `Exception` would be swallowed by handler `except Exception` blocks. Match HA.
- **Shutdown interruption must never propagate.** Suppress benign races; the shutdown path must not crash because a thread died at the wrong moment.
- **Honesty about guarantees.** Document that shutdown interruption is best-effort and cannot interrupt C-blocked threads.
- **`SystemExit` runs `finally` and `__exit__` (Finding 7).** When `async_raise(SystemExit)` unwinds a worker thread, every `finally` block and context-manager `__exit__` in the user's sync handler runs before the thread dies. Unlike HA — which interrupts only at *process* exit, where half-written state vanishes — Hassette interrupts at *framework* shutdown while external systems (databases, files, APIs the handler touched) keep running. A `finally` that commits or flushes can leave a half-completed side effect that survives a restart. User code must not treat `finally` execution as proof of clean completion. This goes in the user docs.

## Dependencies and Assumptions

- `ctypes` (stdlib) for `PyThreadState_SetAsyncExc` — no new third-party dependency.
- CPython-specific behavior; must be exercised across the supported interpreters (3.11–3.14) already in CI.
- Home Assistant's `util/thread.py` and `util/executor.py` (local checkout at `~/source/core`) are the reference for the ported `async_raise` and `InterruptibleThreadPoolExecutor`.
- Assumes all current `run_in_thread` callers are user sync code (verified: App lifecycle sync hooks at `app.py:152-177` and `make_async_adapter` at `listeners.py:712`, `scheduler_service.py:320`, `command_executor.py:534`). Framework internals use `asyncio.to_thread` directly.

## Architecture

### Dedicated executor, owned by a Service (FR#1, FR#5, FR#8)

Port HA's `InterruptibleThreadPoolExecutor` (`~/source/core/homeassistant/util/executor.py:61-101`) and `async_raise` (`~/source/core/homeassistant/util/thread.py:38-55`) into a new module, e.g. `src/hassette/task_bucket/interruptible_executor.py`. The class is a `ThreadPoolExecutor` subclass whose `shutdown()` performs join-or-interrupt within a budget.

**Own the executor through a `Service`, not a bare attribute.** Introduce `SyncExecutorService` (a `Service` under `src/hassette/core/`) that constructs the `InterruptibleThreadPoolExecutor` in its `__init__` (the executor needs no running loop) with a descriptive `thread_name_prefix` (e.g. `hassette-sync`) so worker threads are identifiable in logs and stacks. The service exposes the executor (`service.executor`) and a saturation probe (below). `Hassette` holds the service and exposes `hassette.sync_executor` for `TaskBucket` to reach via `self.hassette`.

Constructing the executor in `__init__` — not lazily during startup — eliminates a `None` window: `TaskBucket` is built at `Hassette.__init__` (`core.py:79`) and any test or partial harness that reaches `run_in_thread` before the run loop starts would otherwise hit a `None` dereference (Finding 6).

**Shutdown ordering is declarative, via the dependency graph.** `BusService` and `SchedulerService` (which dispatch sync handlers and jobs) and `AppHandler` (whose AppSync lifecycle hooks route through `run_in_thread`) declare `depends_on=[SyncExecutorService]`. Wave-based shutdown tears down dependents before their dependencies, so the executor shuts down *after* every component that submits sync work — the app shutdown wave and all sync lifecycle hooks have completed before `SyncExecutorService.on_shutdown()` runs. This closes the race where an AppSync hook submits to an already-closed pool and raises `RuntimeError: cannot schedule new futures after shutdown` (Finding 1). Expressing the ordering in the graph rather than imperative sequencing in `Hassette.shutdown()` matches the codebase pattern (`BusService`/`SchedulerService` already declare `depends_on=[DatabaseService]`) and keeps future ordering needs (e.g. "drain sync work before closing the telemetry DB") expressible declaratively (Finding 4).

`SyncExecutorService.on_shutdown()` calls `executor.shutdown(...)` within the interruption budget (FR#8), and must complete inside `total_shutdown_timeout_seconds`.

### Routing sync user code (FR#1, FR#2)

`TaskBucket.run_in_thread` (`task_bucket.py:153-176`) currently returns `asyncio.to_thread(_call)`. Change it to submit to the dedicated executor: `await loop.run_in_executor(self.hassette.sync_executor, _call)` (wrapped so it returns an awaitable matching the current contract). This is the single seam — every sync handler, sync job, and App sync lifecycle hook flows through `run_in_thread`, so one change routes them all. `asyncio.to_thread` calls elsewhere (logging, database) are untouched and keep using the default pool.

`run_in_executor` returns an `asyncio.Future` wrapping a `concurrent.futures.Future`, which gives the observability hook a handle to inspect (see below) — `asyncio.to_thread` hid it.

### Observability: thread-outlived-timeout (FR#3)

The timeout is applied in `command_executor._execute` (`command_executor.py:266-269`); cancellation propagates into `run_in_thread`'s await. `_execute` awaits `fn()` as an opaque awaitable and holds no reference to the worker thread or its future, so the leak check must not reach back into pool internals from the command layer (Finding 2).

**Mechanism (committed, not deferred):** `run_in_thread` creates a small mutable cell — `cell: list[threading.Thread | None] = [None]` — captured in the `_call` closure, and `_call` sets `cell[0] = threading.current_thread()` as its first line on the worker. The cell is exposed to the caller so the command layer can read `cell[0]` and check `is_alive()` at the timeout site. **A `ContextVar` does NOT work here** and must not be used: `loop.run_in_executor` copies the loop thread's context into the worker callable, so a value the worker writes to a ContextVar mutates the worker's copy — the loop thread reads back `None`. The shared mutable cell is the only mechanism that carries the worker's thread identity back to the reader. No `concurrent.futures.Future` handle is threaded up through `make_async_adapter` to `_execute`; the command layer sees only a thread reference and a liveness boolean, keeping it decoupled from the executor. The check is best-effort (the thread may finish microseconds later). For executions where `_call` never started (the worker had not dequeued the job when the timeout fired — see Edge Cases), `cell[0]` is still `None` and the leak marker is not raised — a not-started timeout is not a leak.

The flag travels to the record via `ExecutionResult`: `_execute` sets a new `thread_leaked` field on the result after the liveness check, and `build_record` reads it. This keeps the carrier explicit rather than re-deriving liveness in two places.

Surface the signal two ways:

- A log line at the existing timeout-warning site, distinguishing "thread still alive" from a clean timeout.
- A distinct field on the execution record — `thread_leaked` (see Migration), kept separate from `status` so the caller-visible `status='timed_out'` contract (FR#9) is preserved.

### Saturation gauge (FR#4)

Mirror the **write-queue** capacity-warning pattern (`command_executor.py:328-346`), which uses a single global timestamp (`_last_capacity_warn_ts`) for rate-limiting — pool saturation is a global condition, not per-entity, so the simpler global-timestamp model fits, not the per-entity dict in `log_timeout_rate_limited` (`:290-326`, shown elsewhere only for its lazy-eviction shape). Read active vs. `max_workers` from the dedicated executor and emit a rate-limited WARNING when active crosses a threshold (e.g. 75%, matching `_CAPACITY_WARN_THRESHOLD`).

**Two trigger paths, because submission-only goes silent at total saturation (Finding 5).** A submission-triggered check (in `run_in_thread`) catches a rising pool. But when all workers are blocked and no new submissions arrive, a submission-only check never fires — the operator's signal dies exactly when the pool is fully starved. So `SyncExecutorService` also runs a **periodic background probe** (a scheduled coroutine, ~30s cadence) that reads pool occupancy and fires the same rate-limited WARNING while saturation persists. The probe is the live "8/8 workers stuck" signal an operator needs at 2am; the submission check is the early-rise signal. Active-worker count is an approximation derived from the executor's accounting — note it as such in code.

### Shutdown interruption (FR#6, FR#7)

`InterruptibleThreadPoolExecutor.shutdown()` encapsulates the join-or-interrupt loop: `super().shutdown(wait=False, cancel_futures=True)` then `join_threads_or_timeout()`, which calls `join_or_interrupt_threads` — joining each thread within a per-thread slice of the budget, logging the stack of any straggler (`_log_thread_running_at_shutdown`), then `async_raise(thread.ident, SystemExit)` with `SystemError`/`ValueError` suppressed. Port the `async_raise` core and the join/interrupt structure, **but adapt — not verbatim — the budget plumbing** (Finding 8): HA hard-codes `EXECUTOR_SHUTDOWN_TIMEOUT = 10` and reads it as a module constant in three places (`executor.py:81,92,96`), with no `timeout` parameter. The port must take `timeout: float` (the configured budget, FR#8) and thread it through `join_threads_or_timeout`/`join_or_interrupt_threads` in place of the constant.

C-blocked threads cannot be interrupted; HA's budget-divided-by-thread-count join spends the budget joining threads that will never join, then abandons them. That is the accepted best-effort behavior (Non-Goals); the budget cap guarantees shutdown does not hang on them.

### Config (FR#8)

Add to `LifecycleConfig` (`config/models.py:218-259`):
- `sync_executor_max_workers: int` — pool ceiling. Default to the prior implicit sizing (`min(32, (os.cpu_count() or 1) + 4)`). Note this is *not* exactly behavior-preserving (Finding 4, MEDIUM): the old shared default pool also served logging and DB, so a dedicated pool of the same size gives sync handlers more effective headroom, not equal. The default is a reasonable starting ceiling, not a literal equivalence.
- `sync_executor_shutdown_timeout_seconds: float` — interruption budget, default `10.0` (HA's value). A `@model_validator` on `LifecycleConfig` enforces `sync_executor_shutdown_timeout_seconds < total_shutdown_timeout_seconds` with a clear error (Finding 8) — without it, an operator can set a 60s budget inside a 30s total, and the outer shutdown `asyncio.timeout` fires mid-join, leaving threads partially interrupted. The interruption loop receives the *remaining* shutdown budget at call time, not the raw config value, so it never overruns the total.

## Replacement Targets

- **`asyncio.to_thread(_call)` in `TaskBucket.run_in_thread` (`task_bucket.py:176`)** is replaced by submission to the dedicated executor. The old default-pool routing for user sync code is superseded — remove it, do not keep both paths. The comment "no task to cancel anymore" (`task_bucket.py:209`) and the `TimeoutError` re-raise in `make_async_adapter` remain accurate and stay.

Everything else is additive (new executor module, new config fields, new observability signal, executor lifecycle wiring).

## Migration

Add a new column `thread_leaked INTEGER NOT NULL DEFAULT 0` to the execution-records table via a forward SQL migration under `src/hassette/migrations_sql/` following the existing numbered pattern (`001.sql`), and add the corresponding field to `ExecutionRecord` (`execution_record.py`). **Do not reuse a reserved column or overload `status`** (Finding 3): the reserved columns (`trigger_mode`, `retry_count`, `attempt_number`, `execution_record.py:87-98`) have documented future semantics, and `status` carries a DB-level `CHECK` constraint (`001.sql:91-92`) whose value set cannot grow without an `ALTER TABLE` of the constraint itself. A dedicated nullable-with-default column is one migration now versus a migration plus API and frontend rework later.

The `DEFAULT 0` makes every historical row read as "not leaked"; no backfill is required. The change is forward-only (the repo uses `PRAGMA user_version` migrations; there is no down-migration convention).

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

The new observability signal hooks into this same single enforcement point. Follow the existing tier-aware, record-then-continue shape.

### Sync/async adapter branch

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

`run_in_thread` is the seam to reroute. The adapter itself does not change shape.

### Rate-limited WARNING with lazy eviction

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

The saturation gauge (FR#4) follows this rate-limiting shape rather than inventing a new one.

### Config field with docstring and validator

**Source:** `src/hassette/config/models.py` (`LifecycleConfig`)

```python
event_handler_timeout_seconds: float | None = Field(default=600.0)
"""Default timeout in seconds for event handler execution. ``None`` disables the default timeout.
Individual listeners can override via ``timeout=`` or ``timeout_disabled=True``."""
```

New executor config fields live in `LifecycleConfig` with the same docstring-as-documentation style.

## Alternatives Considered

- **Per-call mid-runtime interruption (original #549 proposal).** Forcibly `async_raise` into the worker the instant a per-handler timeout fires. Rejected for this change: requires a single-use-thread executor to dodge the tid-reuse race the original design rejected (`design.md:186`), adds thread churn, has no upstream precedent (HA does not do this), and cannot interrupt C-blocked IO — the most common slow path. Deferred to a telemetry-gated follow-up.
- **Document-and-monitor only (no executor, no shutdown-kill).** Just surface the leak and warn at registration. Smaller, but leaves sync handlers sharing the framework's default pool (no containment) and offers no recourse when a blocking handler hangs shutdown. Rejected: the operator explicitly wants containment and shutdown safety.
- **Process-pool / subprocess isolation.** Truly killable and interrupts C-blocked work, but handlers must be picklable and lose `self`/shared state — incompatible with the `App` instance-method handler model. Rejected as a poor fit.
- **Do nothing.** The leak stays invisible and shutdown can hang on a blocking handler. Rejected — that is the reported problem.

## Test Strategy

### Existing Tests to Adapt

- `tests/unit/test_make_async_adapter_timeout.py` — exercises `run_in_thread`'s timeout propagation; its `hassette` stub sets `_loop_thread_id = None`. Update so the stub provides the dedicated executor (or routes through it), since `run_in_thread` will now submit to `hassette.sync_executor` instead of `asyncio.to_thread`. Verify `TimeoutError` still propagates cleanly.
- `tests/unit/scheduler/test_scheduler_timeout_threading.py` and `tests/unit/bus/test_bus_timeout_threading.py` — assert timeout *config threading* (params flow to job/listener options), not executor internals. Expected to pass unchanged; confirm after the executor change.
- `tests/TESTING.md` harness stubs — `HassetteHarness` must construct/expose the dedicated executor for integration tests; `create_hassette_stub()` must provide it for any test that reaches `run_in_thread`. The identity stub at `test_utils/helpers.py:451` bypasses the executor — leave it for tests that don't care, but executor tests must use the real path.

### New Test Coverage

- **FR#1/FR#2 (AC#2):** sync user code runs on the dedicated executor; framework `asyncio.to_thread` runs on the default — assert via `thread_name_prefix` / pool identity.
- **FR#3 (AC#1):** a sync handler blocking past its timeout yields an execution record marked thread-leaked, distinct from a clean timeout; the start-before-dequeue case does not misfire (Edge Cases).
- **FR#4 (AC#3):** saturation WARNING fires near the ceiling and is rate-limited.
- **FR#6/FR#7 (AC#4):** a Python busy-loop worker at shutdown is interrupted within budget; stack logged; process exits. Use the project's `asyncio.Event` gate pattern (CLAUDE.md regression patterns) to hold a worker across the shutdown boundary.
- **FR#6/FR#7 (AC#5):** a C-blocked worker (`time.sleep` in a thread) at shutdown is logged and abandoned at budget expiry; shutdown still completes within `total_shutdown_timeout_seconds`.
- **FR#8 (AC#6):** custom pool size and shutdown budget take effect; defaults apply when unset.
- **FR#8 config validator:** `sync_executor_shutdown_timeout_seconds >= total_shutdown_timeout_seconds` is rejected at config load with a clear error (Finding 8).
- **FR#9 (AC#7):** the caller-visible timeout signal is unchanged.
- **Shutdown ordering (Finding 1/4):** an AppSync shutdown hook submitting sync work during shutdown completes — the executor is still alive because `SyncExecutorService` tears down after its dependents. A regression test should gate the hook across the shutdown boundary (CLAUDE.md `asyncio.Event` pattern) and assert no `RuntimeError: cannot schedule new futures`.
- **Saturation heartbeat (Finding 5):** with all workers blocked and no new submissions, the periodic probe still emits the rate-limited WARNING.
- **Not-started timeout (Finding 2 / Edge Cases):** a timeout that fires before `_call` begins does not set `thread_leaked`.
- **Core-change suites:** this touches `src/hassette/core/` and `task_bucket/`; run `nox -s system` and `nox -s e2e` before shipping per CLAUDE.md (do not run `pytest -n auto`).

### Tests to Remove

No tests to remove — the old default-pool routing for user sync code had no dedicated test beyond the propagation test, which is adapted rather than deleted.

## Documentation Updates

- `design/specs/036-execution-timeouts/design.md` — update the Non-Goals/limitation note: the sync timeout is observable but unenforced against the work; document the new containment + shutdown-interruption behavior and that per-call interruption remains deferred.
- Docs site (`docs/pages/`) — wherever execution timeouts and sync vs. async handlers are explained, state plainly that a sync handler's timeout signals and reclaims the caller but does not kill the worker mid-run; the worker is contained on a dedicated pool and interrupted only at shutdown (best-effort, not for C-blocked threads). Run `doc-persona-review` and `doc-accuracy-review` on touched pages per `.claude/rules/doc-rules.md`.
- Config docs — document the two new `LifecycleConfig` fields (pool size, shutdown interruption budget) and the validator that requires the budget to be under `total_shutdown_timeout_seconds`.
- Docs site — document that a worker interrupted at shutdown runs its `finally`/`__exit__` blocks before terminating, so user sync handlers must not treat `finally` as proof of clean completion (Key Constraints / Finding 7).
- `CLAUDE.md` Architecture section mentions the executor model only implicitly; add a one-line note that sync user code runs on a dedicated interruptible executor if it aids future readers (optional).
- Changelog: ship under `feat:` (user-facing: new observability + shutdown safety + config). Not a breaking change — the caller-visible timeout contract is preserved.

## Impact

### Changed Files

- `src/hassette/task_bucket/interruptible_executor.py` (**new**) — ported `InterruptibleThreadPoolExecutor` + `async_raise`, with a `timeout`-parameterized join/interrupt.
- `src/hassette/core/sync_executor_service.py` (**new**) — `SyncExecutorService` owning the executor (constructed in `__init__`), the periodic saturation probe, and `on_shutdown()` interruption.
- `src/hassette/task_bucket/task_bucket.py` — `run_in_thread` routes to `hassette.sync_executor`; records worker-thread identity for the liveness check; submission-time saturation check.
- `src/hassette/core/core.py` — register `SyncExecutorService` in the child set; expose `hassette.sync_executor`. No imperative teardown — ordering is via `depends_on`.
- `src/hassette/core/bus_service.py`, `src/hassette/core/scheduler_service.py`, and the `AppHandler` service (`src/hassette/core/app_handler.py` — confirm exact path during Phase 2) — add `SyncExecutorService` to `depends_on` so they shut down before it. `AppHandler` is included because its AppSync lifecycle hooks (`app.py:152-177`) submit sync work through `run_in_thread`.
- `src/hassette/core/command_executor.py` — emit the thread-leaked observability signal at the timeout site via the thread-liveness check (no pool-internal coupling).
- `src/hassette/core/execution_record.py` — add the `thread_leaked` field.
- `src/hassette/migrations_sql/00N.sql` (**new**) — add the `thread_leaked` column.
- `src/hassette/config/models.py` — two new `LifecycleConfig` fields plus a `@model_validator` enforcing the shutdown-budget relationship.
- Telemetry/UI surface — if the leak marker should be visible in the monitoring UI, the response model and frontend types must follow (see Blast Radius); regenerate schemas per `.claude/rules/frontend-worktree.md`.
- Tests — adapt `test_make_async_adapter_timeout.py` and harness stubs; add new executor/shutdown/observability tests.
- Docs — as listed above.

### Behavioral Invariants

- The caller-visible timeout contract is unchanged (FR#9): await unblocks, `status='timed_out'` recorded, existing WARNING logged.
- Framework-internal `asyncio.to_thread` calls (logging, database) keep running on the default pool (FR#2).
- App sync lifecycle hooks (`on_initialize_sync`, etc.) and sync jobs continue to run and complete as before — they now run on the dedicated pool, but their success/error/timeout semantics are unchanged.
- Shutdown still completes within `total_shutdown_timeout_seconds`.

### Blast Radius

- Every sync handler, sync job, and App sync lifecycle hook now runs on the dedicated pool instead of the loop default. Functionally transparent; the observable change is pool isolation and identifiable thread names.
- If the leak marker is persisted and surfaced, the telemetry DB schema, the web API response model, and the frontend monitoring views are affected (per `design-completeness.md` — a new status/field visible in the UI is in-scope, not a follow-up). Decide during implementation whether the marker is UI-surfaced or log/telemetry-only; if UI-surfaced, include the backend model + frontend type regeneration in the same PR.
- Real consumers are user apps outside this repo (Hassette is a framework). Any app relying on a timed-out sync handler *completing its side effects* would still see completion mid-run (interruption is shutdown-only here), so no app-visible contract change from this scope.

## Open Questions

_None open. The decisions surfaced during adversarial review are now committed in the design: the persistence marker is a new `thread_leaked` column surfaced in the UI (Migration); the observability seam is a thread-liveness check via `ContextVar`, not future-handle plumbing (Architecture); the executor is a `Service` in the dependency graph with shutdown ordering expressed via `depends_on` (Architecture); the shutdown budget is a validated config field threaded as a parameter (Config). Two are intentionally deferred to follow-ups, not open: per-call mid-runtime interruption (Non-Goals) and any change to the framework-internal default-pool usage._
