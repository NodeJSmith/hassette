# System Internals — Per-Service Internals

**Status:** New page (content from current `internals.md` sections 4-9)
**Voice mode:** Concept — system-as-subject, no "you", contributor/deep-dive audience
**Page type:** Reference (deep-dive)
**Reader's job:** Look up how a specific internal service works — its data structures, dispatch logic, and failure behavior.

## What was cut (and where it goes)

Nothing cut — this page collects the per-service detail sections from the monolithic
internals.md. The ordering is redesigned: the original followed source-code module
order. The new order follows the event pipeline (the path data takes through the
system), which matches how a reader would trace a problem.

## Outline

### H2: Bus Internals
Event dispatch pipeline: topic matching (exact then glob), listener filtering
(predicate check), handler invocation via `CommandExecutor`. How debounce/throttle/once
are implemented. Topic expansion rule (three topics per state_changed event). Existing
Mermaid diagram.

Listener behavior options table (debounce, throttle, duration, once, priority).

### H2: Scheduler Internals
Trigger evaluation loop, min-heap by `next_run`, execution lifecycle. How convenience
methods (`run_in`, `run_every`, `run_cron`) translate to trigger objects (`After`,
`Every`, `Cron`). `Daily` uses cron internally for DST safety. Jitter, job groups,
named jobs. Existing Mermaid diagram.

### H2: StateManager and StateProxy
Proxy pattern: `StateProxy` maintains in-memory cache (populated by bus subscription
at priority 100 + periodic poll), `StateManager` provides typed per-app access.
Domain routing, `DomainStates` collection, `context_id` caching. Lock-free reads,
disconnect/reconnect behavior. Existing Mermaid diagram.

### H2: Api Internals
Per-app `Api` delegates to shared `ApiResource` (REST) and `WebsocketService` (WS).
Transport routing table (which method uses which transport). Auth mechanism. Existing
Mermaid diagram.

### H2: Database Internals
SQLite schema, `PRAGMA user_version` migration system, unified `executions` table with
`kind` discriminator. Synchronous registration pattern (why `db_id` is available
immediately). Schema version mismatch handling (`SchemaVersionError`). Auto-vacuum
setup on fresh databases.

### H2: Web/UI Layer
`WebApiService` starts uvicorn/FastAPI. Two data source services:
`RuntimeQueryService` (live state, event buffer, WS broadcast) and
`TelemetryQueryService` (SQLite queries). SPA catch-all for client-side routing.
`config.run_web_api=False` behavior. Existing Mermaid diagram.

## Snippet Inventory

No dedicated snippets — diagrams are inline Mermaid.

## Cross-Links

- **Links to:** Architecture & Data Flow, Lifecycle & Supervision, Bus overview, Scheduler overview, States overview, API overview
- **Linked from:** Architecture & Data Flow
