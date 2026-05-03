---
topic: "Useful, actionable logging — content, levels, grouping, display"
date: 2026-05-02
status: Draft
---

# Prior Art: Useful, Actionable Logging

## The Problem

An automation framework's logs serve two audiences with different needs: **developers debugging** ("why did my automation not fire?") and **operators monitoring** ("is anything broken right now?"). Most frameworks start with global stdout logging and evolve toward structured, per-run, per-component log systems as users demand signal over noise. The challenge is getting the right content at the right level, correlated to the right run, and displayed in a way that surfaces problems without drowning in volume.

## How We Do It Today

Hassette uses Python's stdlib `logging` with `coloredlogs` for console output. Each app gets its own named logger (`hassette.{app_name}`), and per-service + per-app log levels are configurable via `hassette.toml`. A `LogCaptureHandler` collects log records into an in-memory bounded deque (2000 entries) tagged with `app_key`, sequence number, and exception traces. The web UI streams logs via WebSocket with level filtering, and a REST endpoint (`/api/logs/recent`) supports `app_key` and `level` query params. Noisy libraries (`aiohttp`, `urllib3`, etc.) are suppressed to WARNING. There are no correlation IDs, no structured logging library, no log persistence beyond the in-memory ring buffer, and no per-run log grouping.

## Patterns Found

### Pattern 1: Context-Variable-Based Per-Run Correlation

**Used by**: FastAPI (via `asgi-correlation-id`), structlog, Celery (`get_task_logger`), Prefect (binds flow run ID at dispatch)

**How it works**: At the start of a unit of work — an automation run, a handler invocation — a unique identifier (`run_id`, `app_name`, `invocation_id`) is stored in a `contextvars.ContextVar`. Because `asyncio.create_task()` automatically copies the current context to new tasks, any coroutine spawned during the run inherits the ID without explicit parameter passing. A structlog processor or stdlib `logging.Filter` reads the `ContextVar` and stamps every emitted record with the correlation fields.

Multiple IDs can be stacked: bind `app_name` at app startup, `handler_id` at dispatch, and `event_id` when processing a specific HA event. Each nested binding is additive. On exit, `clear_contextvars()` resets the state to avoid leakage between runs on the same event loop.

**Strengths**: Zero burden on user code — `logger.info("thing happened")` automatically carries full correlation context. Subtasks inherit context for free. Every log line is traceable to a specific run.

**Weaknesses**: Context does not propagate into `concurrent.futures` thread pools without manual `copy_context().run()`. Only process-local — doesn't cross service boundaries.

**Example**: https://www.structlog.org/en/stable/contextvars.html, https://github.com/snok/asgi-correlation-id

### Pattern 2: Structured JSON with Environment-Aware Rendering

**Used by**: FastAPI, structlog ecosystem, Prefect, most cloud-native Python services

**How it works**: Log records are always structured internally (dicts with typed fields), but the output renderer is swapped based on environment. Development gets colorized, human-readable console output with aligned fields. Production gets JSON, one record per line, consumable by log aggregators (Loki, Datadog, ELK). The structlog processor chain makes this trivial: shared processors for timestamp/level/context-merge, then `ConsoleRenderer()` in dev vs `JSONRenderer()` in prod.

For a monitoring UI that serves as its own log viewer (like Hassette's), JSON records are queryable and filterable by any field — `app_name`, `run_id`, `level` — without regex parsing.

**Strengths**: Single code path; rendering is a config concern, not a code concern. JSON output is indexable and filterable by any field. Human-readable dev output reduces friction.

**Weaknesses**: JSON is harder to read in a raw terminal during incident response. Requires an aggregation layer to be useful at scale — raw JSON files aren't themselves a UI.

**Example**: https://gist.github.com/nymous/f138c7f06062b7c43c060bf03759c29e

### Pattern 3: Per-Run Log Capture and Storage

**Used by**: Prefect (stores per-flow-run logs in backend), n8n (per-execution I/O), Airflow (per-task-instance logs)

**How it works**: The framework intercepts log records during a run and writes them to a storage backend (database, object store, or ring buffer) keyed by run ID. The monitoring UI queries by run ID to show per-run logs, rather than filtering a global stream. Implementation: temporarily attach a `logging.Handler` at run start, collect records, persist at completion. Prefect uses a dedicated log-shipping worker that batches and POSTs records keyed by flow/task run ID.

This enables per-run log replay, level filtering within a single run, side-by-side "logs and events" timeline views, and direct linking from an error to the run that produced it.

**Strengths**: Log records are first-class run artifacts — no external aggregation tool needed. Users see exactly what happened in one specific automation run. Works offline and in single-process deployments.

**Weaknesses**: Storage overhead — every run produces log artifacts that need retention policies. Capture handler is a global side effect on the logging system and must be carefully isolated per-run.

**Example**: https://docs.prefect.io/v3/how-to-guides/workflows/add-logging, https://prefect-284-docs.netlify.app/ui/flow-runs/

### Pattern 4: Per-Component Log Level Control with Runtime Override

**Used by**: Home Assistant (per-integration config + runtime service call), Celery (per-task logger hierarchy), Python stdlib logger hierarchy

**How it works**: Each component gets a named logger scoped to its module path: `hassette.apps.my_app`. The stdlib hierarchy means setting the level on `hassette.apps` affects all apps, while `hassette.apps.my_app` affects only that app. The distinguishing feature in automation frameworks is exposing this as a **runtime-adjustable user feature** — an API endpoint, UI toggle, or service call — so users can turn on DEBUG for a misbehaving app without restarting.

Home Assistant community discussion reveals this is a high-demand feature: users routinely need to investigate a single malfunctioning integration without being buried in debug output from all others.

**Strengths**: Users isolate debugging to one component. Framework internals stay at WARNING while one app runs at DEBUG. Logger hierarchy is free from stdlib.

**Weaknesses**: Requires communicating logger names to users. Runtime level changes are not persistent across restarts unless saved back to config.

**Example**: https://www.home-assistant.io/integrations/logger/, https://community.home-assistant.io/t/wth-isnt-it-easier-to-change-an-integrations-log-level/472949

### Pattern 5: Queue-Based Async Log Dispatch

**Used by**: Python stdlib (`QueueHandler` + `QueueListener`), recommended in asyncio logging guides

**How it works**: Instead of synchronous log writes, the logger enqueues the serialized record and returns immediately. A background thread drains the queue and performs actual I/O. From the event loop's perspective, logging is a non-blocking enqueue. Wired via `logging.handlers.QueueHandler` (emits) + `QueueListener` (drains in thread). structlog is compatible because its output stage calls stdlib `logging`.

**Strengths**: Event loop never stalled by log I/O. Enables batching for network destinations. Logging throughput decoupled from event loop throughput.

**Weaknesses**: Records may be lost on unclean shutdown if the queue isn't flushed. Queue saturation under extreme load requires explicit handling.

**Example**: https://superfastpython.com/asyncio-logging-best-practices/

### Pattern 6: Execution Replay UI with Inline Error Context

**Used by**: n8n (per-node I/O replay), Prefect (logs tab on flow run detail), Airflow (task instance logs), Temporal (event history timeline)

**How it works**: The monitoring UI doesn't show a scrolling global log tail. Instead, it shows execution as a structured artifact: logical steps (event received → handler invoked → service called → result returned) as a timeline or graph. Selecting a step reveals log records, input data, output data, and exceptions. Text logs from user code appear as annotations on the timeline, not the primary surface.

The minimal version: a run record with `start_time`, `end_time`, `status`, `error_message`, and `log_lines[]` in the database. The UI shows runs filtered by app, with click-through to log detail. This is the Prefect "Logs" tab model.

**Strengths**: Users understand what happened without parsing log syntax. Error context shown at the point of failure, not buried in a stream. Per-run history is queryable.

**Weaknesses**: Requires framework instrumentation — structured execution events, not just log passthrough. More implementation work than stdout + grep.

**Example**: https://docs.n8n.io/workflows/executions/single-workflow-executions/, https://prefect-284-docs.netlify.app/ui/flow-runs/

## Anti-Patterns

- **Everything is ERROR**: Treating every handled exception as ERROR causes alert fatigue — real errors become invisible. ERROR = "operation failed, requires investigation." WARNING = "unexpected but recovered." INFO = "expected state transition." ([logdy.dev](https://logdy.dev/blog/post/logging-series/logging-best-practices-series-logging-levels))

- **Synchronous log I/O on the event loop**: Writing to files or network synchronously from async code can stall the loop for milliseconds per record. Fix: `QueueHandler` + `QueueListener`. ([superfastpython.com](https://superfastpython.com/asyncio-logging-best-practices/))

- **Anonymous flat log streams**: Interleaved logs from concurrent runs without correlation IDs are unreadable. Both Celery's `task_id`-per-record and Prefect's per-run grouping exist because anonymous flat logs are insufficient for concurrent workloads. ([celery issue #9466](https://github.com/celery/celery/issues/9466))

- **Logging in hot paths**: Emitting a record for every state change event or attribute evaluation creates noise and degrades performance. Log at the start/end of significant operations; use DEBUG for per-item details. Sample repeated identical errors rather than silencing entirely. ([betterstack](https://betterstack.com/community/guides/logging/logging-best-practices/))

## Emerging Trends

- **OpenTelemetry as the correlation substrate**: Newer frameworks adopt OTel trace context (`trace_id`, `span_id`) as the universal correlation key, so logs, metrics, and traces share the same ID space. ([signoz.io](https://signoz.io/blog/deep-temporal-observability/))

- **Structured logging as default**: JSON-structured logging is the assumed default for new Python frameworks (2024+), not an add-on. The question is "which processor pipeline?" not "should I use structured logging?" ([structlog docs](https://www.structlog.org/en/stable/logging-best-practices.html))

## Relevance to Us

Hassette already has several pieces of the puzzle: per-app named loggers with configurable levels (Pattern 4), an in-memory log capture system with app attribution (a lightweight Pattern 3), and WebSocket-based log streaming to the UI. The main gaps are:

1. **No correlation IDs** (Pattern 1) — logs from concurrent handler invocations in the same app are interleaved without a run/invocation ID. Adding `ContextVar`-based correlation at the handler dispatch point would be low-effort and high-value.

2. **No structured logging** (Pattern 2) — all records are string-formatted. Moving to structlog with a dev/prod renderer swap would make the existing `LogCaptureHandler` records richer and more filterable without changing the architecture.

3. **No per-run log grouping** (Pattern 3) — the UI shows a global stream filtered by app, not grouped by invocation. Hassette already tracks invocations in the database; associating captured log records with invocation IDs would enable a Prefect-like "click a run, see its logs" view.

4. **No async log dispatch** (Pattern 5) — current logging is synchronous on the event loop. `QueueHandler` + `QueueListener` is a mechanical change with immediate performance benefit.

5. **Runtime log level toggle** (Pattern 4 extension) — Hassette has per-app log levels in config, but no runtime API endpoint or UI toggle to change them live. HA community feedback shows this is a strongly desired feature.

Pattern 6 (execution replay) is aspirational — it requires deeper framework instrumentation and is a larger scope effort, but the Prefect minimal model (run list + log detail click-through) aligns well with Hassette's existing invocation tracking.

## Recommendation

The highest-value, lowest-effort improvements are Patterns 1 and 5: **ContextVar-based correlation IDs** at handler dispatch and **QueueHandler-based async log dispatch**. Both are mechanical changes that improve every log line without requiring user-visible API changes.

Pattern 2 (structlog) is the natural next step — it makes correlation IDs trivial to bind and enables the dev/prod renderer split. The existing `LogCaptureHandler` would need minor adaptation to work with structlog's processor chain.

Pattern 3 (per-run log storage) builds on the correlation ID work and would enable the most impactful UI improvement: clicking an invocation row to see only that invocation's logs. Since Hassette already stores invocations in the database and captures logs in memory, the wiring is straightforward.

Pattern 4's runtime extension (API endpoint for live log level changes) is a quick win that users will appreciate immediately.

Pattern 6 is worth keeping in mind as a north star for the UI but is not a near-term priority.

## Sources

### Reference implementations
- https://github.com/snok/asgi-correlation-id — ASGI middleware for correlation ID propagation via ContextVar
- https://gist.github.com/nymous/f138c7f06062b7c43c060bf03759c29e — FastAPI + structlog production wiring (dev/prod renderer swap)

### Blog posts & writeups
- https://rednafi.com/python/log-context-propagation/ — Log context propagation in Python ASGI apps
- https://celery.school/custom-celery-task-logger — Celery per-task logger with auto-injected task_id
- https://betterstack.com/community/guides/logging/logging-best-practices/ — 12 concrete logging dos/don'ts
- https://last9.io/blog/logging-best-practices/ — Logging noise reduction, sampling strategies
- https://betterstack.com/community/guides/logging/log-levels-explained/ — Log level decision guide with examples
- https://superfastpython.com/asyncio-logging-best-practices/ — QueueHandler pattern for async Python
- https://medium.com/@ThinkingLoop/10-advanced-logging-correlation-trace-ids-in-python-50bff4024344 — Trace ID lifecycle in async Python
- https://logdy.dev/blog/post/logging-series/logging-best-practices-series-logging-levels — Log level misuse and alert fatigue
- https://signoz.io/blog/deep-temporal-observability/ — OpenTelemetry as correlation substrate

### Documentation & standards
- https://www.structlog.org/en/stable/logging-best-practices.html — structlog best practices
- https://www.structlog.org/en/stable/contextvars.html — structlog ContextVar binding
- https://peps.python.org/pep-0567/ — PEP 567: Context Variables
- https://docs.prefect.io/v3/how-to-guides/workflows/add-logging — Prefect per-run log capture
- https://prefect-284-docs.netlify.app/ui/flow-runs/ — Prefect flow run UI with logs tab
- https://docs.temporal.io/develop/python/observability — Temporal observability (external correlation)
- https://docs.n8n.io/workflows/executions/single-workflow-executions/ — n8n execution replay UI
- https://www.home-assistant.io/integrations/logger/ — HA per-component log level control

### Community discussions
- https://community.home-assistant.io/t/wth-isnt-it-easier-to-change-an-integrations-log-level/472949 — HA users on runtime log level changes
- https://github.com/celery/celery/issues/9466 — Celery missing per-task log storage
