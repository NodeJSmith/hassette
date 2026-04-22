---
topic: "Exception handler callbacks for event bus and scheduler"
date: 2026-04-21
status: Draft
---

# Prior Art: Exception Handler Callbacks for Event Bus and Scheduler

## The Problem

When a user's event handler or scheduled job raises an exception in an async framework, the framework must decide: who gets told, what context do they get, and can they act on it? The naive approach (catch, log, continue) ensures stability but creates a black hole — users have no visibility into or control over error handling. The design challenge is providing extensibility without introducing new failure modes (error handler loops, silent swallowing, GC-dependent timing).

## How We Do It Today

Hassette catches all handler/job exceptions in `CommandExecutor._execute()`, logs them at ERROR level with topic/job context, records them to telemetry (SQLite), and swallows them. Users have zero hooks into this path — they see errors only in logs or by querying telemetry after the fact. `CancelledError` is re-raised; `TimeoutError` is swallowed with a rate-limited warning. The framework also suppresses tracebacks for known error types (`DependencyError`, `HassetteError`).

## Patterns Found

### Pattern 1: Global Exception Handler with Context Dict

**Used by**: Python asyncio, Home Assistant core

**How it works**: A single handler registered via `set_exception_handler(handler)`. The handler receives a context dict with structured metadata: exception object, originating task/future, message, tracebacks. The dict is extensible — new keys don't break existing handlers. A `default_exception_handler` is always available as fallback; custom handlers can call it to layer behavior. Notification-only — cannot recover or retry.

**Strengths**: Simple setup (one call). Extensible context avoids breaking changes. Layering via "call default" pattern. Python 3.12+ propagates `contextvars.Context`.

**Weaknesses**: Cannot recover from errors. In asyncio, timing depends on Task GC — errors may be reported indefinitely late. Only one handler at a time (set, not add). No per-task granularity without done callbacks.

**Example**: https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.set_exception_handler

### Pattern 2: Event Listener with Typed Event Objects

**Used by**: APScheduler v3.x, Java EventBus libraries

**How it works**: Errors are treated as typed event objects (`JobExecutionEvent` with `job_id`, `exception`, `traceback`, `scheduled_run_time`). Registered via `add_listener(callback, EVENT_JOB_ERROR)` — multiple listeners, additive. Event type enum allows filtering at registration time. Unified API: same listener system for success, error, and lifecycle events.

**Strengths**: Multiple listeners (additive). Typed objects with IDE autocompletion. Unified API for all event types. Rich context without dict-key guessing.

**Weaknesses**: If the job catches its own exception, the error event never fires — documented gotcha. v4.x regressed by silently swallowing exceptions when no listener was registered (major user complaint). No recovery mechanism.

**Example**: https://apscheduler.readthedocs.io/en/3.x/modules/events.html

### Pattern 3: Three-Tier Error Handling

**Used by**: Celery

**How it works**: Three independent surfaces: (1) `on_failure()` method override on Task subclass (per-class), (2) `link_error` parameter at invocation time (per-call), (3) `task_failure` signal for global observation. Each tier serves a different audience: task authors, task callers, and operators. All three can fire for the same error.

**Strengths**: Maximum granularity. Clear audience per tier. Global signals are additive. Per-invocation errbacks are composable.

**Weaknesses**: Three surfaces to learn and coordinate. If errbacks themselves raise, behavior is undefined (known issue #4787). Race conditions between result backend updates and `on_failure` execution.

**Example**: https://docs.celeryq.dev/en/stable/userguide/tasks.html

### Pattern 4: Mandatory Error Event (Crash if Unhandled)

**Used by**: Node.js EventEmitter

**How it works**: The `'error'` event has special semantics — if emitted with no listener registered, the process crashes. Forces explicit error handling. Layered features: `errorMonitor` (observe without consuming), `captureRejections` (auto-route async handler rejections to error event), `Symbol.for('nodejs.rejection')` (per-emitter custom rejection handling).

**Strengths**: No silent failure — loudest possible default. `errorMonitor` cleanly separates observation from handling. `captureRejections` addresses async handler errors.

**Weaknesses**: Process crash is too aggressive for event buses where one handler shouldn't crash the system. `captureRejections` explicitly warns against async error handlers (infinite loop risk). Every emitter needs boilerplate error handler.

**Example**: https://nodejs.org/api/events.html#error-events

### Pattern 5: on_error Parameter (Per-Action)

**Used by**: Home Assistant automations (proposed in architecture discussion #845)

**How it works**: Each action/handler registration accepts an optional `on_error` parameter specifying what to do when that action fails. Error context passed as variables. Falls back to default behavior (log and continue) when not specified. Chosen by HA maintainers over try/catch blocks for simplicity.

**Strengths**: Per-action granularity without global config. Error context scoped to the action. Composes naturally with registration APIs. UI-friendly.

**Weaknesses**: Verbose when most handlers use the same error behavior. No built-in cascading (per-action → app-level → global fallback). Adds API surface to every registration call.

### Pattern 6: Error-as-Stream-Event (Observable on_error)

**Used by**: RxPY, RxJS, RxJava (ReactiveX family)

**How it works**: Errors delivered via `on_error(exception)` terminate the stream. Recovery requires explicit operators (`catch`, `retry`) or restructuring with `flat_map`. Per-subscription, no global handler.

**Strengths**: Errors cannot be silently ignored. Composable recovery operators.

**Weaknesses**: "Error terminates the stream" surprises users frequently (RxPY #224). Not suitable for event buses where independent handlers should continue after one fails.

**Example**: https://rxpy.readthedocs.io/en/latest/get_started.html

### Pattern 7: Supervisor-Based Error Isolation (Let It Crash)

**Used by**: Elixir/OTP, Akka

**How it works**: Processes crash and supervisors restart them per configured strategy. Error info flows through exit signals, not callbacks. Separation of concerns: business logic doesn't know about recovery.

**Strengths**: Complete error isolation. Automatic recovery. No error callback code needed.

**Weaknesses**: Requires fundamentally different architecture (process per handler). Not directly applicable to Python's single-process async model.

**Example**: https://hexdocs.pm/elixir/Supervisor.html

## Anti-Patterns

- **Silent swallowing**: APScheduler v4.x regressed from v3.x by not logging exceptions when no listener registered. Users reported development becoming extremely difficult. The worst default is silence. ([#652](https://github.com/agronholm/apscheduler/issues/652))

- **Async error handlers that loop**: Node.js warns against async `'error'` handlers — a rejection creates an infinite loop: error -> async handler -> rejection -> error. `captureRejections` deliberately omits catch handlers on error events to break this cycle. ([docs](https://nodejs.org/api/events.html))

- **GC-dependent error reporting**: asyncio reports task exceptions only on Task garbage collection. Holding any reference delays reporting indefinitely. Quantlane documented this as a production issue requiring `add_done_callback()` wrappers. ([blog](https://quantlane.com/blog/ensure-asyncio-task-exceptions-get-logged/))

- **Error handler that raises breaks everything**: In Celery, if an errback itself raises, the original task may not be properly marked as failed. Error handlers must be hardened against their own failures. ([celery#4787](https://github.com/celery/celery/issues/4787))

## Emerging Trends

- **Observation vs. handling separation**: Node.js `errorMonitor` lets metrics/logging observe all errors without counting as "having a handler." Monitoring presence shouldn't suppress crash-if-unhandled behavior.

- **Context-scoped handling**: Python 3.12 `contextvars.Context` propagation, FastAPI per-route error maps. Trend away from global handlers toward "error handling that knows where it came from."

- **Two-tier default (log + callback)**: Multiple frameworks converging on always-log (non-negotiable) + optional user callbacks. Avoids the silent-swallowing anti-pattern while giving users control. APScheduler's v3→v4 regression reinforced this.

## Relevance to Us

Hassette's current approach (catch, log, record, continue) is already better than the silent-swallowing anti-pattern — the framework logs at ERROR and records to telemetry. The gap is user extensibility: there's no way to hook into the error path for custom alerting, retry logic, or error-specific responses.

The framework's existing patterns suggest two natural fit points:

1. **App-level `on_error()`** on Bus and Scheduler (Pattern 1/2 hybrid) — aligns with hassette's per-app resource model. Each app gets its own Bus and Scheduler, so an app-level handler is already scoped correctly.

2. **Per-registration `on_error=` parameter** (Pattern 5) — aligns with how HA automations are heading. But this adds API surface to every `bus.on()` and `scheduler.schedule()` call.

Key constraints from our architecture:
- `CommandExecutor._execute()` is the single choke point — changes here affect all handler/job execution
- The `CancelledError` re-raise contract must be preserved
- `track_execution()` captures `ExecutionResult` but may not carry the exception object itself (needs verification)
- Handlers run as tasks spawned by `task_bucket`, so timing is immediate (no GC dependency — we dodge asyncio's worst footgun)

The two-tier log+callback trend matches hassette's philosophy: framework handles the safe default, user layers on top.

## Recommendation

**Adopt a two-tier model: always-log + app-level `on_error()` callback.**

Key design choices informed by the research:

1. **Always log, even with a custom handler** — APScheduler's v4 regression proves silent swallowing is the cardinal sin. The user handler supplements framework logging, it doesn't replace it. If users truly want to suppress framework logs, they can configure Python logging (filter the logger), but the framework should never be the one to go silent.

2. **App-level granularity first, per-registration later** — Celery's three-tier model is powerful but complex. Start with Pattern 1 (app-level `on_error()`) since hassette's per-app resource model already scopes it correctly. Per-listener/per-job `on_error=` parameter (Pattern 5) can be a follow-up if users request it.

3. **Typed context object, not bare exception** — APScheduler's `JobExecutionEvent` and asyncio's context dict both prove that the exception alone isn't enough. Users need to know *which* handler failed and *what* topic/job triggered it. A frozen dataclass is better than a dict (IDE support, static analysis).

4. **Guard against error-handler-throws-error** — Node.js and Celery both document this footgun. The framework must wrap user handler invocation in try/except, log any handler exception at ERROR, and continue. Never await an async error handler inside the error path without this guard.

5. **Don't suppress framework logging** — This contradicts the original plan's "suppress framework ERROR log when custom handler is registered." The APScheduler anti-pattern and the two-tier trend both argue against suppression. Let the user control their logging config if they want less noise.

6. **Skip the Rx model** — "Error terminates the stream" is wrong for an event bus where handlers are independent.

7. **Skip the Node.js "crash if unhandled" model** — Too aggressive for home automation. One bad handler shouldn't crash all automations.

Open question worth discussing: should the handler receive `BusErrorContext`/`SchedulerErrorContext` (typed per-domain), or a single `ErrorContext` with a discriminator? Typed is more Pythonic and hassette-consistent, but means two types to learn.

## Sources

### Reference implementations
- https://docs.python.org/3/library/asyncio-eventloop.html — asyncio set_exception_handler
- https://apscheduler.readthedocs.io/en/3.x/modules/events.html — APScheduler event listeners
- https://docs.celeryq.dev/en/stable/userguide/tasks.html — Celery task error handling
- https://nodejs.org/api/events.html — Node.js EventEmitter error events
- https://rxpy.readthedocs.io/en/latest/get_started.html — RxPY observer error handling
- https://hexdocs.pm/elixir/Supervisor.html — Elixir/OTP supervisors

### Blog posts & writeups
- https://quantlane.com/blog/ensure-asyncio-task-exceptions-get-logged/ — asyncio task exception timing
- https://superfastpython.com/asyncio-event-loop-exception-handler/ — asyncio exception handler tutorial
- https://www.roguelynn.com/words/asyncio-exception-handling/ — asyncio exception handling guide
- https://dev.to/ivan-borovets/contextual-error-handling-for-fastapi-per-route-with-openapi-schema-generation-4p9a — FastAPI per-route error handling

### Design discussions & issue reports
- https://github.com/home-assistant/architecture/discussions/845 — HA automation error handling
- https://github.com/agronholm/apscheduler/issues/652 — APScheduler v4 silent swallowing
- https://github.com/ReactiveX/RxPY/issues/224 — RxPY error-terminates-stream confusion
- https://github.com/celery/celery/issues/4787 — Celery errback-raises issue

### Books
- https://www.cosmicpython.com/book/chapter_08_events_and_message_bus.html — message bus error isolation
