# Design: Exception Handlers for Event and Scheduler Callbacks

**Date:** 2026-04-21
**Status:** archived
**Research:** design/research/2026-04-21-exception-handler-callbacks/research.md

## Problem

When an automation callback fails, the framework catches the exception, logs it, and moves on. The user has no way to run custom logic in response — no alerting, no recovery actions, no context-specific error handling. The only visibility is reading framework logs or querying telemetry after the fact.

Users need the ability to react to failures: send a notification when a critical sensor handler crashes, execute a fallback action when a light automation fails, or log domain-specific diagnostics that the framework can't know about.

## Goals

- Users can register error handlers that run when their event listeners or scheduled jobs fail
- Error handlers receive enough context to make informed decisions: the exception, traceback, which callback failed, and what data was being processed
- Error handling is layered: specific handlers for individual registrations, with an app-level fallback for everything else
- The framework's own error logging continues regardless of user-registered handlers
- Error handlers that themselves fail do not cascade or disrupt the system

## Non-Goals

- Retry logic or automatic recovery (users implement this in their handlers if needed)
- Per-exception-type routing (users can inspect the exception type in their handler)
- Error handlers for framework-internal failures (only user-registered callbacks)

## User Scenarios

### App Author: Home Automation Developer
- **Goal:** React to automation failures with custom logic
- **Context:** Writing automations that control physical devices where failures have real-world consequences

#### Register app-level error fallback

1. **Register a default error handler during app initialization**
   - Sees: The Bus and Scheduler resources available on the app
   - Decides: What generic error handling to apply across all callbacks
   - Then: All future callback failures that lack a specific handler invoke this fallback

#### Register per-listener error handler

1. **Register an event listener with a specific error handler**
   - Sees: The registration method accepting an optional error callback parameter
   - Decides: Which listeners need custom error handling vs. the app-level fallback
   - Then: When that specific listener fails, only its dedicated handler runs (not the fallback)

#### Diagnose a failure from error context

1. **Receive an error callback with full context**
   - Sees: The exception object, formatted traceback, topic/job identity, and the event payload that triggered the failure
   - Decides: What recovery action to take based on the specific failure
   - Then: Executes recovery logic (notify, call a service, log diagnostics) and returns

#### Error handler itself fails

1. **An error handler raises an exception**
   - Sees: Nothing — the framework handles it transparently
   - Then: The framework logs the error handler failure at ERROR level and continues; no cascading, no infinite loops

## Functional Requirements

1. The Bus must accept an app-level error handler that is invoked when any listener callback fails, unless that listener has its own error handler
2. The Scheduler must accept an app-level error handler that is invoked when any job callback fails, unless that job has its own error handler
3. Each listener registration method must accept an optional error handler parameter
4. Each job scheduling method must accept an optional error handler parameter
5. When both a per-registration and app-level handler exist, only the per-registration handler runs
6. Error handlers must receive a context object containing: the exception, formatted traceback (when available), the identity of the failed callback (topic for bus, job name for scheduler), and the input data (event payload for bus handlers)
7. Error handlers may be sync or async callables
8. If an error handler raises an exception, the framework must catch it, log it at ERROR level, and continue — no cascading
9. The framework must continue logging errors at its current level regardless of whether a user error handler is registered
10. Exceptions are routed to user handlers except for `CancelledError`, which continues to be handled by the framework's existing contract; timeout-related failures are routed to user handlers (challenge F2)
11. The app-level error handler is resolved at invocation time, not captured at registration time — calling `on_error()` at any point applies the handler to all listeners/jobs that lack a per-registration handler, regardless of registration order
12. The error context for scheduler jobs must include the job identity but not the trigger input (scheduler jobs are time-triggered, not data-triggered)
13. Error handler invocation must be bounded by a configurable timeout (default: 5 seconds) to prevent hung handlers from blocking the system
14. Error handlers must run in a separate spawned task from the original callback's dispatch task, so that dispatch slot accounting (`_dispatch_pending`) is not extended by error handler duration

## Edge Cases

1. **Error handler registered after some listeners already exist** — the app-level handler is resolved at invocation time, so all existing listeners without a per-registration handler immediately use the new fallback. No ordering constraint on when `on_error()` is called relative to listener registration.
2. **Error handler replaced mid-lifecycle** — calling `on_error()` again replaces the app-level handler. The change takes effect immediately for all future invocations of listeners without per-registration handlers.
3. **Multiple listeners on the same topic, one with on_error= and one without** — each listener's error behavior is independent. The one with `on_error=` uses its handler; the other falls back to app-level or framework default.
4. **Error handler is a sync function but accesses async resources** — the framework must support both sync and async handlers. Sync handlers that need async resources should be written as async.
5. **Error handler takes too long** — error handler invocation is wrapped in `asyncio.timeout()` using the `error_handler_timeout_seconds` config key (default: 5 seconds). On timeout, the framework logs a WARNING and continues. The error handler runs in a separate spawned task (via `task_bucket.spawn`) so the original dispatch task completes at its natural end — `await_dispatch_idle()` is not extended by error handler duration.
6. **App shutdown while error handler is running** — follows the existing cancellation contract. The error handler task receives `CancelledError` like any other task.
7. **App reload clears the app-level error handler** — `on_initialize()` resets `_error_handler = None` as part of standard Bus/Scheduler lifecycle reset. `App.on_initialize()` must re-register the handler. This is not an edge case but the standard framework lifecycle — `on_initialize()` is the designated setup hook and all state is expected to be re-established there.

## Acceptance Criteria

- [ ] An app can register an app-level error handler on Bus via `bus.on_error(handler)`
- [ ] An app can register an app-level error handler on Scheduler via `scheduler.on_error(handler)`
- [ ] An app can register a per-listener error handler via `on_error=` parameter on any Bus registration method
- [ ] An app can register a per-job error handler via `on_error=` parameter on any Scheduler scheduling method
- [ ] When a listener fails and has `on_error=` set, only that handler runs (not the app-level fallback)
- [ ] When a listener fails and has no `on_error=`, the app-level fallback runs (if registered)
- [ ] When no error handler is registered at any level, existing framework behavior is unchanged
- [ ] The error context object contains the exception, traceback, callback identity, and event payload (bus only)
- [ ] Both sync and async error handlers are supported
- [ ] An error handler that raises is caught, logged at ERROR, and does not cascade
- [ ] Framework ERROR logging continues when user error handlers are registered
- [ ] Task cancellations are not routed to user error handlers; timeouts **are** routed (challenge F2)
- [ ] Error handler invocation is bounded by a configurable timeout (`error_handler_timeout_seconds`, default 5s); on timeout, a WARNING is logged
- [ ] Error handlers run in a separate task from the original callback's dispatch task
- [ ] All existing tests pass with no behavior changes

## Dependencies and Assumptions

- Depends on `ExecutionResult` being extended to carry the original exception object (currently only stores stringified error info)
- Assumes the `CommandExecutor._execute()` method's exception contract remains stable
- Related to #571 (per-execution correlation IDs) — error context objects are designed to accept an execution ID field in the future but do not include one in this iteration

## Architecture

### Error Context Objects

Two frozen dataclasses in new files:

**`src/hassette/bus/error_context.py`** — `BusErrorContext`:
- `exception: BaseException` — the raised exception
- `traceback: str` — formatted traceback string, always populated from `"".join(traceback.format_exception(ctx.exception))`. Unlike the framework's own `log_error` which suppresses tracebacks for known error types (`DependencyError`, `HassetteError`), the user-facing context object always includes the full traceback — users debugging their automations need it regardless of exception type. The framework's suppression policy serves a different audience (reducing log noise).
- `topic: str` — the event topic that triggered the listener
- `listener_name: str` — human-readable listener identity (from `Listener.__repr__`)
- `event: Event[Any]` — the event payload that was being processed (imported from `hassette.events.base`). Note: typed as `Event[Any]` — payload type safety from the original handler is not preserved. To access specific payload fields, cast explicitly: `cast(StateChangedEvent, ctx.event)`. A generic `BusErrorContext[T]` would require the handler type alias to also be generic, which is deferred to a future improvement.

**`src/hassette/scheduler/error_context.py`** — `SchedulerErrorContext`:
- `exception: BaseException` — the raised exception
- `traceback: str` — formatted traceback string (always populated)
- `job_name: str` — human-readable job identity
- `job_group: str | None` — the job's group name if any
- `args: tuple[Any, ...]` — the job's registration-time positional arguments from `job.args` (typically empty for parameterless automation jobs; populated when using `run_every(func, minutes=5, args=(sensor_id,))`)
- `kwargs: dict[str, Any]` — the job's registration-time keyword arguments from `job.kwargs`

### ExecutionResult Change

Add `exc: BaseException | None = None` field to `ExecutionResult` in `src/hassette/utils/execution.py`. In `track_execution()`, assign `result.exc = exc` **before** the `raise` statement in both the `except Exception as exc:` and `except TimeoutError as exc:` branches. Do not populate for `CancelledError` (which has no `as exc` binding). This must happen before re-raise because `_execute()` swallows the re-raised exception at line 231 — after that point, the exception object is only available via `result.exc`. Error handlers are invoked when `(result.is_error or result.is_timed_out) and result.exc is not None`.

### Error Handler Types

Add domain-specific handler type aliases to `src/hassette/types/types.py`:
```python
BusErrorHandlerType: TypeAlias = (
    Callable[[BusErrorContext], Awaitable[None]] | Callable[[BusErrorContext], None]
)
SchedulerErrorHandlerType: TypeAlias = (
    Callable[[SchedulerErrorContext], Awaitable[None]] | Callable[[SchedulerErrorContext], None]
)
```
Each handler accepts a single typed positional argument. The union of `Callable[[T], Awaitable[None]]` and `Callable[[T], None]` correctly models sync/async duality — unlike `Callable[..., Awaitable[None] | None]`, which is a union return type that accepts any signature. Domain-specific variants catch arity and argument-type errors at static analysis time, consistent with how `HandlerType`, `SyncHandler`, and `AsyncHandlerType` are defined in the same file.

### Handler Storage

**On `Listener`** (`src/hassette/bus/listeners.py`): `Listener` is `@dataclass(slots=True)`. Add `error_handler: BusErrorHandlerType | None = None` field to the class body (required for slot generation). Thread the parameter through `Listener.create()` at line 267 — add it to the factory's parameter list and pass it in the explicit `cls(...)` constructor call. Existing callers of `Listener.create()` are unaffected since the parameter has a default. Populated from the `on_error=` Options value if provided at registration time.

**On `ScheduledJob`** (`src/hassette/scheduler/classes.py`): `ScheduledJob` is `@dataclass(order=True)`. Add `error_handler: SchedulerErrorHandlerType | None = field(default=None, compare=False)` — `compare=False` is required because `Callable | None` is not orderable and would corrupt the scheduler's priority-queue heap ordering. Also add `error_handler` to `matches()` (using `self.error_handler is other.error_handler` on the raw callable) and `diff_fields()` to prevent `if_exists="skip"` from silently discarding error handlers on re-registration.

**Normalization timing**: Error handlers are stored as-is (raw callable) on `Listener` and `ScheduledJob` for reliable identity comparison in `matches()`. Normalization via `make_async_adapter` happens at invocation time in `_execute_handler`/`_execute_job`, mirroring the existing `orig_handler` / `_async_handler` split on `Listener`. This avoids the problem where registration-time normalization produces wrapper objects that break identity comparison on reload.

### Registration API

**`Bus`** (`src/hassette/bus/bus.py`):
- `on_error(handler)` method — stores `_error_handler` on the Bus instance. Reset in `on_initialize()`.
- Add `on_error: BusErrorHandlerType | None = None` to three locations: (1) the `Options` TypedDict (`bus.py:109`) so it flows through `**opts: Unpack[Options]` to all 14 convenience wrappers with no wrapper changes, (2) `Bus.on()`'s explicit keyword-only parameter list (`bus.py:212`) since `on()` names every parameter explicitly and does not accept `**kwargs`, and (3) `Listener.create()`'s parameter list and constructor call. This matches the existing pattern — all other Options keys (`once`, `debounce`, `throttle`, `timeout`, `name`) are also explicit parameters on `on()` and `Listener.create()`.
- **Per-registration handler** (captured at registration time): if `on_error=` is provided via Options, it is stored on the `Listener` at `Listener.create()` time.
- **App-level fallback** (resolved at dispatch time): when no per-registration handler exists, `BusService._dispatch()` reads `Bus._error_handler` at the moment the command is built and carries it on `InvokeHandler.app_level_error_handler`. This satisfies FR11 — the app-level handler reflects the Bus's current state at dispatch time, not at listener registration time.

**`Scheduler`** (`src/hassette/scheduler/scheduler.py`):
- `on_error(handler)` method — stores `_error_handler` on the Scheduler instance. Reset in `on_initialize()`.
- `schedule()` and all convenience methods (`run_in`, `run_once`, `run_every`, `run_daily`, `run_cron`, `run_hourly`, `run_minutely`) gain `on_error: SchedulerErrorHandlerType | None = None` parameter. Passed through to `ScheduledJob` construction.
- Same invocation-time resolution logic as Bus: per-registration `on_error=` wins; if absent, Scheduler's `_error_handler` is resolved at dispatch time.

### Invocation in CommandExecutor

**`_execute_handler`** (`src/hassette/core/command_executor.py`):
Change from `await self._execute(...)` to `result = await self._execute(...)` to capture the returned `ExecutionResult`. After `_execute()` returns (framework logging already happened inside via `log_error`), check for a user error handler. Resolution order: `cmd.listener.error_handler` (per-registration) first; if `None`, use `cmd.app_level_error_handler` (app-level fallback, resolved at dispatch time by `BusService._dispatch()` where `Bus` is in scope — carried on the `InvokeHandler` command dataclass as `app_level_error_handler: BusErrorHandlerType | None`). If a handler is found and `result.is_error`:
1. Build `BusErrorContext` from `cmd` and `result`
2. Spawn a separate task via `task_bucket.spawn` to invoke the error handler — this keeps the original dispatch task's `_dispatch_pending` accounting clean
3. In the spawned task: normalize the handler via `make_async_adapter`, wrap invocation in `asyncio.timeout(error_handler_timeout_seconds)` and try/except — if the handler raises or times out, log at ERROR/WARNING and continue

User handler invocation lives in `_execute_handler` and `_execute_job` only — **not** inside `_execute()`. This preserves the abstraction boundary: `_execute()` remains free of `bus.error_context` and `scheduler.error_context` imports.

Note: when both the original callback and its error handler fail, the telemetry record captures only the original failure. The error handler failure is logged at ERROR but does not produce a separate telemetry record (intentional v1 scope). However, an `_error_handler_failures: int` counter on `CommandExecutor` is incremented on each error handler failure, following the existing `_dropped_*` counter family pattern. This counter is exposed via the counters API for observability tooling.

**`_execute_job`**: Same pattern with `SchedulerErrorContext`.

The key insight: the user handler runs *after* framework logging, not instead of it. This avoids the APScheduler v4 anti-pattern where user registration silences the framework.

### Handler Normalization

Error handlers are normalized to async at invocation time via `make_async_adapter` (from `hassette.utils.func_utils`). The raw callable is stored on `Listener`/`ScheduledJob` for reliable identity comparison in `matches()`. When the error handler is invoked in the spawned task, `make_async_adapter` wraps it if sync. `asyncio.iscoroutinefunction()` is not used because it fails for `functools.partial`, `@wraps`-decorated coroutines, and callable objects with `async def __call__`.

Note: sync error handlers wrapped via `make_async_adapter` run in the thread-pool executor (`asyncio.to_thread`). The `asyncio.timeout` cancels the awaiting coroutine but cannot interrupt the running thread — a slow sync handler occupies a pool slot for its full blocking duration. Error handlers that perform I/O (network calls, HA service calls) should be written as `async def`.

## Alternatives Considered

### App-level only (no per-registration)
Simpler, but forces users to dispatch on topic/job identity inside a single handler. Per-registration is the natural API given that hassette already passes configuration per-registration (`priority=`, `debounce=`, `throttle=`, `group=`).

### Suppress framework logging when user handler is registered
The prior art research found this was APScheduler v4's biggest regret — silent swallowing when users thought they had a handler but it was broken. Always logging is safer.

### Single `ErrorContext` type with a discriminator
Saves one type definition, but loses IDE autocompletion for domain-specific fields (`event` on bus, `job_group` on scheduler). Typed-per-domain is more Pythonic and consistent with hassette's existing patterns.

### Decorator-based error registration
```python
@self.bus.error_handler
async def on_error(ctx: BusErrorContext): ...
```
Viable but inconsistent with hassette's imperative registration pattern. All other bus/scheduler APIs use method calls, not decorators.

## Test Strategy

- **Unit tests**: `Listener` and `ScheduledJob` field propagation (error_handler stored correctly, precedence logic between per-registration and app-level)
- **Integration tests — HassetteHarness** (precedence and routing): Extend `HassetteHarness` bus and scheduler stubs to check `listener.error_handler` / `job.error_handler` after a failed invocation and invoke it, mirroring the real executor's dispatch logic. Tests: per-registration vs. app-level precedence, multiple listeners with different handlers, no handler registered (existing behavior unchanged).
- **Integration tests — CommandExecutor** (execution path correctness): Test error handler invocation through the real `CommandExecutor` with a mocked `TelemetryRepository`. Tests: handler raises and error handler called with correct context object fields, framework log still emitted, error handler itself raises (caught and logged), error handler timeout behavior.
- **Edge case tests**: CancelledError not routed to user handler; TimeoutError routed to user handler (challenge F2). App reload clears and re-registers handlers correctly.

## Documentation Updates

- `docs/pages/core-concepts/bus/handlers.md` — add section on error handling with examples
- `docs/pages/core-concepts/scheduler/` — add error handling section
- API reference for `BusErrorContext`, `SchedulerErrorContext`
- Migration guide note: new optional parameter on all registration methods (non-breaking)
- `on_error()` docstrings must note: "During app reload, the error handler is cleared before `on_initialize()` runs. Register your error handler as the first statement in `on_initialize()` to minimize the gap."

## Impact

**Files modified:**
- `src/hassette/utils/execution.py` — add `exc` field to `ExecutionResult`
- `src/hassette/bus/listeners.py` — add `error_handler` field to class body and `Listener.create()` parameters
- `src/hassette/scheduler/classes.py` — add `error_handler` field with `compare=False`, update `matches()` and `diff_fields()`
- `src/hassette/bus/bus.py` — add `on_error()` method, `on_error` to `Options` TypedDict and `Bus.on()` parameter list
- `src/hassette/scheduler/scheduler.py` — add `on_error()` method, `on_error=` parameter on all scheduling methods
- `src/hassette/core/command_executor.py` — invoke user error handlers in spawned tasks after framework logging, add `_error_handler_failures` counter
- `src/hassette/core/commands.py` — add `app_level_error_handler` field to `InvokeHandler` and scheduler equivalent
- `src/hassette/core/bus_service.py` — resolve `Bus._error_handler` at dispatch time, set on `InvokeHandler`
- `src/hassette/core/scheduler_service.py` — resolve `Scheduler._error_handler` at dispatch time, set on scheduler command
- `src/hassette/types/types.py` — add `BusErrorHandlerType`, `SchedulerErrorHandlerType`
- Config class — add `error_handler_timeout_seconds: float = 5.0`

**New files:**
- `src/hassette/bus/error_context.py`
- `src/hassette/scheduler/error_context.py`

**Blast radius:** The `CommandExecutor._execute()` method is the highest-risk change — it's the single execution choke point for all handler/job invocations. The `CancelledError` re-raise contract must be preserved. All other changes are additive (new optional parameters, new fields with defaults).

## Open Questions

None — all design decisions resolved through discovery, prior art research, and challenge review.
