# Design: Execution Timeouts for Scheduler Jobs and Event Handlers

**Date:** 2026-04-19
**Status:** approved
**Research:** /tmp/claude-mine-prior-art-okJvHe/brief.md

## Problem

Scheduled jobs and event bus handlers run without any execution time limit. A single stuck handler — whether from a slow network call, an accidental infinite loop, or a hung dependency — can block the scheduler or event bus indefinitely, degrading the entire system. There is no mechanism to detect, cancel, or surface these runaway executions.

Additionally, the two services that would host this logic (`BusService` and `SchedulerService`) share ~40 lines of identical registration-tracking code. Adding timeout enforcement on top of duplicated infrastructure increases the risk of the implementations drifting out of sync.

## Goals

- Every job and handler execution is bounded by a configurable timeout
- Timeouts are enforced by the framework, not by automation authors
- Timeout events are visible in telemetry and the monitoring dashboard
- The system recovers gracefully from timeouts — no cascading failures, no lost scheduled recurrences
- Registration-tracking duplication is eliminated before timeout logic is added

## Non-Goals

- Two-tier (soft + hard) timeout — single-tier enforcement is sufficient for home automation use cases
- Retry-on-timeout — automation authors can implement retry logic in their handlers if needed
- CPU-bound interruption — timeouts only fire at yield points (standard asyncio limitation)
- Sync handler thread interruption — for sync handlers run via `make_async_handler` in a `ThreadPoolExecutor`, `asyncio.timeout()` cancels the asyncio wrapper but the underlying thread continues running until the blocking operation completes. Thread-level interruption via `PyThreadState_SetAsyncExc` was rejected due to thread-ID race conditions (see Architecture § Sync Handler Timeout Behavior). Automation authors should use async handlers for potentially slow I/O
- `TimeoutError` swallowing — if user handler code catches `TimeoutError` without re-raising (e.g., from an inner HTTP client), the framework's timeout is silently disabled for that invocation. Users should catch specific exception types from inner libraries rather than bare `TimeoutError`

## User Scenarios

### Automation Author: Home Automation Developer

- **Goal:** Write automations without worrying about timeout configuration
- **Context:** Building Home Assistant automations using hassette's scheduler and event bus

#### Default protection

1. **Registers a handler or schedules a job**
   - Sees: No timeout-related parameters required
   - Then: The framework applies the global default timeout (10 minutes) automatically

#### Custom timeout for a fast-response handler

1. **Registers an event handler that should respond quickly**
   - Sees: Optional `timeout` parameter on registration methods
   - Decides: Sets `timeout=5.0` for this specific handler
   - Then: The handler is cancelled after 5 seconds if still running

#### Investigating a timeout

1. **Notices a handler or job timed out**
   - Sees: Warning in logs with handler/job name and timeout duration
   - Sees: "timed out" status on the execution record in the dashboard
   - Decides: Adjusts the timeout or fixes the slow handler

### Framework Operator: System Administrator

- **Goal:** Tune timeout thresholds for the deployment
- **Context:** Managing a hassette instance with multiple automations

#### Adjusting global defaults

1. **Wants to change the default timeout for all handlers**
   - Sees: Configuration fields in hassette.toml or environment variables
   - Decides: Sets a different global default
   - Then: All handlers/jobs without per-item overrides use the new default

## Functional Requirements

1. The system must enforce a configurable execution timeout on every scheduled job execution
2. The system must enforce a configurable execution timeout on every event handler invocation
3. Each job and handler must support an individual timeout override that takes precedence over the global default
4. When a timeout expires, the running execution must be cancelled cooperatively
5. Timeout events must be logged at WARNING level with the handler/job identity and the timeout duration
6. Timeout events must be recorded in telemetry with a distinct "timed_out" status
7. After a job times out, the job must still be rescheduled for its next occurrence
8. After a handler times out, once-listeners must still be removed from the bus
9. Timeout enforcement must not require any code changes in existing automations
10. A `None` timeout value on a per-item override must fall through to the global default; `timeout_disabled=True` disables timeout for that specific job/handler
11. Setting the global default to `None` must disable timeout enforcement entirely (opt-out escape hatch). A startup WARNING must be logged from `Hassette.on_initialize()` (after log infrastructure is running, once per startup — not from `HassetteConfig` model construction) when either global timeout is set to `None`: "execution timeout enforcement is disabled globally — framework components are unprotected"
12. Shared registration-tracking logic must be extracted into a single utility before timeout logic is added

## Edge Cases

- Handler or job completes exactly at the timeout boundary — should be treated as successful
- Debounced handler: timeout applies to the handler execution, not the debounce wait period
- Throttled handler: timeout applies to the handler execution, not the throttle window
- Job with jitter: timeout applies to execution duration, not scheduling delay
- Handler that catches `TimeoutError` internally — if user code catches `TimeoutError` from inner operations (e.g., HTTP client timeouts) without re-raising, it will also swallow the framework's timeout. This is a documented limitation (see Non-Goals). Users should catch specific library exceptions rather than bare `TimeoutError`
- Rate-limited listener with `once=True`: prohibited by existing validation, no interaction to handle
- `CancelledError` during timeout: `asyncio.timeout()` delivers `CancelledError` internally to the wrapped coroutine, then converts it to `TimeoutError` on propagation out of the scope. The `except TimeoutError` branch in `track_execution` catches this before the `except CancelledError` branch, ensuring correct status assignment. External `CancelledError` (e.g., from shutdown) bypasses the `asyncio.timeout()` scope and is handled by the existing `except CancelledError` branch as before

## Acceptance Criteria

1. A scheduled job that exceeds its timeout is cancelled and logged, and the next scheduled occurrence fires normally
2. An event handler that exceeds its timeout is cancelled and logged, and subsequent events are still dispatched to the handler
3. A `once=True` handler that times out is still removed from the bus after the timeout
4. The dashboard shows "timed out" status on execution records for timed-out jobs and handlers
5. Setting `timeout=5.0` on a specific handler causes that handler to be cancelled after 5 seconds, regardless of the global default
6. With default configuration (no user changes), all jobs and handlers are protected by a 10-minute timeout
7. Setting the global config to `None` disables timeout enforcement for jobs/handlers without per-item overrides
8. Existing automations continue to work without modification
9. All existing tests pass without changes after the registration-tracking refactor
10. After Phase 1, `BusService.await_registrations_complete()` timeout warning correctly reports the number of incomplete tasks (non-zero when tasks are still running at timeout)

## Dependencies and Assumptions

- Python 3.11+ is required (already the project minimum) — provides `asyncio.timeout()` as a stdlib cancel scope
- `asyncio.timeout()` raises `TimeoutError` (not `asyncio.TimeoutError`) in Python 3.11+
- The `CommandExecutor` already handles exceptions from job/handler execution and records status — timeout status needs to be added as a new outcome via an explicit `except TimeoutError` branch in `track_execution`
- The dashboard frontend uses hardcoded binary ternaries for status rendering — explicit code changes are required to surface `'timed_out'` with distinct styling

## Architecture

### Phase 1: Extract RegistrationTracker (#532)

Create `src/hassette/core/registration_tracker.py` containing a standalone `RegistrationTracker` class (no `Resource` dependency). It encapsulates:

- `_tasks: dict[str, list[asyncio.Task[None]]]` (initialized as `defaultdict(list)`)
- `prune_and_track(app_key, task)` — prunes completed tasks, appends the new one
- `async def await_complete(self, app_key: str, timeout: float, logger: Logger) -> None` — pops tasks, filters done, uses `asyncio.wait(..., timeout=)` (the `SchedulerService` strategy, which correctly reports incomplete count before cancellation), cancels stragglers, logs warning on timeout. Callers pass `self.hassette.config.registration_await_timeout` as the `timeout` argument
- `drain_framework_keys(await_fn)` — iterates framework-prefixed keys for the drain-at-shutdown pattern

Both `BusService` and `SchedulerService` replace their inline `_pending_registration_tasks` dict and associated logic with a `self._reg_tracker = RegistrationTracker()` instance. No happy-path behavioral regression — existing tests must pass unmodified. Note: `BusService` previously used `asyncio.wait_for(asyncio.gather(...))` which always reported 0 incomplete tasks in its warning message (a bug); adopting the `asyncio.wait()` strategy fixes this. Add a targeted regression test for the shutdown drain path on both services to cover this change.

### Phase 2: Scheduler Job Timeout (#63)

Add `timeout: float | None = None` field to `ScheduledJob`. Also add a `timeout_disabled: bool = False` field — when `True`, timeout enforcement is disabled for this job regardless of the global default. Include `timeout`, `timeout_disabled`, and the existing `jitter` field in the hand-written `matches()` method so that changes during hot-reload are detected by `if_exists="skip"` and not silently discarded (jitter's current exclusion is a bug). Update the `add_job()` error message to distinguish config-mismatch from name-collision: "A job named '...' already exists but its configuration has changed (changed fields: ...)". Semantics: `None` = use global default, positive `float` = explicit timeout in seconds, `timeout_disabled=True` = no timeout. Validate at registration time: `if isinstance(timeout, (int, float)) and timeout <= 0: raise ValueError("timeout must be a positive number")`, matching the existing `debounce > 0` / `throttle > 0` validation pattern. Thread `timeout=` through all `Scheduler` public methods (`schedule()`, `run_in()`, `run_once()`, `run_every()`, `run_daily()`, `run_minutely()`, `run_hourly()`, `run_cron()`).

Add `scheduler_job_timeout_seconds: float | None = Field(default=600.0)` to `HassetteConfig`.

The effective timeout is resolved at the service layer: if `job.timeout_disabled is True`, effective timeout is `None` (disabled); if `job.timeout` is a `float`, use that value; if `job.timeout is None`, fall through to `config.scheduler_job_timeout_seconds`. The resolved value is passed through the `ExecuteJob` command object as `effective_timeout: float | None`. The `asyncio.timeout()` scope lives inside `CommandExecutor._execute()`, wrapping the actual callable invocation. This placement ensures:

1. `track_execution` observes the `TimeoutError` directly and sets `status='timed_out'`
2. The timeout scope is created in the correct asyncio task — critical for debounced handlers where the callable runs in a background task spawned by `RateLimiter`

The nesting order inside `_execute()` is critical — `asyncio.timeout()` must be **inside** the `track_execution` context manager so that `TimeoutError` is observed by `track_execution`'s exception handling:

```python
async with track_execution(result):
    async with asyncio.timeout(cmd.effective_timeout):  # None = no deadline (valid no-op)
        await fn()
```

Note: `asyncio.timeout(None)` is a documented Python 3.11+ no-op (no deadline enforced), so no `if/else` branching is needed — the single unconditional `asyncio.timeout(cmd.effective_timeout)` handles both the timeout and no-timeout cases.

In `track_execution`, add an `except TimeoutError` branch **before `except Exception`** (not before `except CancelledError` — `TimeoutError` is a subclass of `Exception` in Python 3.11+, not of `CancelledError`):

```python
except TimeoutError:
    result.status = "timed_out"
    raise
except asyncio.CancelledError:
    result.status = "cancelled"
    raise
except Exception as exc:
    result.status = "error"
    ...
```

`effective_timeout=None` is the canonical "no timeout" value — both `timeout_disabled=True` on a job/handler and a global config of `None` collapse to this value. The distinction between sources is not preserved at the command layer. When `effective_timeout is None`, `asyncio.timeout(None)` acts as a no-op — no deadline is enforced.

After `execute()` returns (whether success, error, or timeout), `_dispatch_and_log` proceeds to `reschedule_job()` normally. No special shutdown guard is needed — during shutdown, `CancelledError` propagates from the serve loop and is caught/re-raised in `_dispatch_and_log` before `reschedule_job()` is reached.

Timeout WARNING logs are rate-limited per job (see Timeout Log Rate Limiting below).

### Phase 3: Event Handler Timeout (#64)

Add `timeout: float | None = None` field to `Listener` and `timeout_disabled: bool = False` — when `True`, timeout enforcement is disabled for this handler. Semantics: `None` = use global default, positive `float` = explicit timeout in seconds, `timeout_disabled=True` = no timeout. Validate at registration time: `if isinstance(timeout, (int, float)) and timeout <= 0: raise ValueError("timeout must be a positive number")`, matching the existing `debounce > 0` / `throttle > 0` validation in `Listener._validate_options()`. Add `timeout: float | None` and `timeout_disabled: bool` to the `Options` TypedDict (both fields must be added together). Thread `timeout=` and `timeout_disabled=` through `Listener.create()` and `Bus.on()` as explicit keyword arguments (matching the existing pattern for `once`, `debounce`, `throttle`). The `Bus.on()` → `**opts: Unpack[Options]` refactor is deferred to a standalone cleanup issue — adding two explicit kwargs is simpler and avoids a silent-ignore risk if `opts` aren't properly forwarded.

Add `event_handler_timeout_seconds: float | None = Field(default=600.0)` to `HassetteConfig`.

The effective timeout is resolved at the service layer using the same logic as for jobs: `timeout_disabled=True` → disabled, `float` → explicit value, `None` → fall through to `config.event_handler_timeout_seconds`. The resolved value is passed through the `InvokeHandler` command object as `effective_timeout: float | None`. The `asyncio.timeout()` scope lives inside `CommandExecutor._execute()` (same placement as for scheduler jobs), wrapping the actual handler invocation. This ensures:

1. `track_execution` observes the `TimeoutError` directly and sets `status='timed_out'`
2. For debounced handlers, the timeout scope is created inside the background task spawned by `RateLimiter`, correctly covering the actual handler execution rather than the parent dispatch task

No additional timeout scope is needed in `BusService._dispatch()` or `SchedulerService._dispatch_and_log()` — `_execute()` is called from inside the RateLimiter's background task for debounced handlers, so the single scope in `_execute()` covers all cases.

The `finally` clause in `_dispatch()` still fires after timeout, ensuring `once=True` listeners are removed. Timeout WARNING logs are rate-limited per listener (see Timeout Log Rate Limiting below).

### Sync Handler Timeout Behavior

For async handlers, `asyncio.timeout()` cancels at the next yield point. For sync handlers dispatched via `TaskBucket.run_in_thread()` → `asyncio.to_thread()`, the asyncio wrapper is cancelled but the underlying thread continues running until the blocking operation completes. The telemetry record will correctly show `status='timed_out'`, but the thread may occupy a thread pool slot beyond the timeout.

Thread-level interruption via `PyThreadState_SetAsyncExc` (Home Assistant's `async_raise` pattern) was evaluated but rejected due to unresolvable thread-ID race conditions: (1) the thread may not have started when the timeout fires, leaving the thread ID uninitialized, and (2) the thread pool may recycle the thread ID to an unrelated task between timeout and `async_raise`, injecting a spurious exception into the wrong function. These races make `async_raise` unsafe in a `ThreadPoolExecutor` context.

Automation authors should use async handlers for any potentially slow I/O. This limitation is documented in Non-Goals.

### Telemetry Changes

Both `JobExecutionRecord.status` and `HandlerInvocationRecord.status` gain `'timed_out'` as a valid value. The `CommandExecutor` needs to catch `TimeoutError` (via an explicit `except TimeoutError` branch in `track_execution`, placed before `except CancelledError`) and set `result.status = "timed_out"`.

All eight SQL aggregation query sites in `TelemetryQueryService` must be updated to include `'timed_out'` as a distinct bucket. Add a `timed_out: int` field to both `ListenerSummary` and `JobSummary` Pydantic models. Update the SQL CASE expressions to count `'timed_out'` separately (not merged into the `error` bucket — timeouts are qualitatively different from errors).

Add an `is_timed_out` property to `ExecutionResult` (`return self.status == "timed_out"`) alongside the existing `is_success`, `is_error`, and `is_cancelled` properties. The `log_error` gate in `_execute()` remains `result.is_error` only — timeout logging is handled by the rate-limited WARNING path, not the error callback. Routing timeouts through `log_error` would produce misleading ERROR-level "Handler error: None" messages for expected operational conditions.

A new Alembic migration (005) must add `'timed_out'` to the SQLite CHECK constraints on both `handler_invocations.status` and `job_executions.status`, following the table-recreation pattern established in migration 003. The updated CHECK: `status IN ('success', 'error', 'cancelled', 'timed_out')`. Also update the status docstrings in `JobExecutionRecord` and `HandlerInvocationRecord` to list the valid values.

The frontend currently uses a binary ternary (`status === "success" ? "success" : "danger"`) in both `job-executions.tsx` and `handler-invocations.tsx`. Extract a centralized `executionStatusVariant(status: string)` helper in `frontend/src/utils/status.ts` that maps: `"success"` → success (green), `"timed_out"` → warning (amber), everything else → danger (red). Update both components and `APP_STATUS_MAP` to use this helper. This prevents drift on future status additions.

### Timeout Log Rate Limiting

Timeout WARNING logs must be rate-limited per listener/job to prevent log flooding from high-frequency handlers that repeatedly time out. Track a `dict[int, float]` of in-memory ID (`Listener.listener_id` / `ScheduledJob.job_id`, not `db_id`) → `last_warn_ts` and suppress repeat WARNINGs within a 60-second window. Log a suppression count at the end of each window.

To prevent unbounded memory growth (IDs are auto-increment and never reused), evict stale entries lazily: during the rate-limit check, also evict entries where `now - last_warn_ts > 60s`. This bounds the dict without any cross-service lifecycle coupling — `CommandExecutor` handles its own cleanup internally.

## Alternatives Considered

### Two-tier soft + hard timeout (Celery model)

Celery uses `soft_time_limit` (raises catchable exception) + `hard_time_limit` (kills the process). This allows graceful cleanup but adds configuration complexity (two values per timeout). For home automation, single-tier enforcement via `asyncio.timeout()` is sufficient — the cancel scope already allows `finally` blocks to run for cleanup. Rejected for unnecessary complexity.

### No default timeout (Celery/APScheduler model)

Both Celery and APScheduler ship without default timeouts. This is widely cited as a production footgun — Dramatiq's creator explicitly built defaults into the framework as a response. Our research found that production teams consistently recommend "always set a timeout." Shipping with a 10-minute default follows Dramatiq's "safe by default" philosophy.

### Separate default values for jobs vs handlers

Initially considered 600s for jobs and 60s for handlers based on the intuition that handlers should be faster. Rejected in favor of a uniform 10-minute default for both — it keeps the mental model simpler (one default to learn), and per-item overrides provide granularity for users who want tighter control on specific handlers. The two config fields remain separate so the defaults can be tuned independently if desired.

### `asyncio.wait_for()` instead of `asyncio.timeout()`

`asyncio.wait_for()` is the older API. `asyncio.timeout()` (Python 3.11+) uses cancel scopes, composes correctly with nesting, and is the recommended modern primitive. Since hassette requires Python 3.11+, there's no compatibility concern. Preferred `asyncio.timeout()`.

## Test Strategy

- **Unit tests for RegistrationTracker**: Track tasks, prune done tasks, await with timeout, drain framework keys
- **Unit tests for ScheduledJob.timeout**: Field construction, default value, exclusion from `matches()`
- **Unit tests for Scheduler timeout threading**: Verify `timeout=` flows from each convenience method through `schedule()` to `ScheduledJob`
- **Unit tests for SchedulerService.run_job() timeout**: Timeout fires, error logged, reschedule proceeds, status recorded as `'timed_out'`
- **Unit tests for Listener.timeout**: Field construction via `Listener.create()`, Options TypedDict acceptance
- **Unit tests for Bus timeout threading**: Verify `timeout=` flows from `on_*` methods through to `Listener`
- **Unit tests for BusService._dispatch() timeout**: Timeout fires, error logged, once-removal still fires, status recorded
- **Regression**: All existing `test_scheduler_service_barrier.py` and `test_bus_service_public_accessors.py` tests pass unchanged after RegistrationTracker refactor
- **Timeout enforcement tests MUST use the real `CommandExecutor`**, not `HassetteHarness` — the harness bypasses `_execute()` where `asyncio.timeout()` lives and cannot verify timeout behavior
- **`matches()` tests**: Verify `matches()` returns `False` when only `jitter` differs; returns `False` when only `timeout` differs. Update `add_job()` error message to distinguish config-mismatch from name-collision

## Documentation Updates

- Update scheduler documentation to describe the `timeout` parameter on scheduling methods
- Update bus documentation to describe the `timeout` parameter on listener registration methods
- Document `scheduler_job_timeout_seconds` and `event_handler_timeout_seconds` config fields
- Add a "Timeouts" section to the configuration reference
- Document the `TimeoutError` swallowing limitation: handlers catching `TimeoutError` without re-raising silently disable the framework's timeout. Recommend catching specific library exception types instead

## Impact

**Files modified:**
- `src/hassette/core/registration_tracker.py` (new ~70 lines)
- `src/hassette/core/scheduler_service.py` — RegistrationTracker integration, effective timeout resolution + pass-through to command
- `src/hassette/core/bus_service.py` — RegistrationTracker integration, effective timeout resolution + pass-through to command
- `src/hassette/core/command_executor.py` — `asyncio.timeout()` scope inside `_execute()`, `TimeoutError` handling → `'timed_out'` status, timeout WARNING rate limiting
- `src/hassette/core/commands.py` — `effective_timeout: float | None` field on `ExecuteJob` and `InvokeHandler`
- `src/hassette/utils/execution.py` — `except TimeoutError` branch in `track_execution`, `is_timed_out` property on `ExecutionResult`
- `src/hassette/scheduler/classes.py` — `timeout` field on `ScheduledJob`, add `timeout` and `jitter` to `matches()`
- `src/hassette/scheduler/scheduler.py` — `timeout=` parameter on all public methods
- `src/hassette/bus/listeners.py` — `timeout` and `timeout_disabled` fields on `Listener`, update `create()` signature
- `src/hassette/task_bucket/task_bucket.py` — `make_async_adapter._sync_fn` must filter `TimeoutError` from exception logging
- `src/hassette/bus/bus.py` — `timeout` and `timeout_disabled` in `Options` TypedDict and as explicit kwargs on `on()`
- `src/hassette/config/config.py` — two new config fields + startup WARNING when `None`
- `src/hassette/migrations/versions/005_*.py` (new) — add `'timed_out'` to CHECK constraints on both tables
- `src/hassette/core/telemetry_query_service.py` — update all 8 aggregation queries with `'timed_out'` bucket
- `src/hassette/core/telemetry_models.py` — `timed_out: int` field on `ListenerSummary` and `JobSummary`
- `src/hassette/web/telemetry_helpers.py` — update status mapping
- `frontend/src/utils/status.ts` — new `executionStatusVariant()` helper
- `frontend/src/components/app-detail/job-executions.tsx` — use centralized status helper
- `frontend/src/components/app-detail/handler-invocations.tsx` — use centralized status helper

**Blast radius:** Medium — touches two core services, two user-facing APIs (Scheduler, Bus), config, telemetry (queries + models + migration), and frontend status rendering. All changes are additive (new fields, new parameters with defaults, new status value). No breaking changes to existing APIs — all new parameters have defaults.

## Open Questions

None.
