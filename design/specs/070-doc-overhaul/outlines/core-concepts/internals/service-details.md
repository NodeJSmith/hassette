# System Internals — Per-Service Internals

**Status:** New page (content from current `internals.md` sections 4-9)
**Voice mode:** Concept — system-as-subject, no "you", contributor/deep-dive audience

## Outline

### H2: Bus Internals
Event dispatch pipeline: topic matching, listener filtering, handler invocation order. How debounce/throttle/once are implemented.

### H2: Scheduler Internals
Trigger evaluation loop, job heap, execution lifecycle. How `run_in`/`run_every`/`run_cron` translate to trigger objects.

### H2: Database Internals
SQLite schema, migration system, unified executions table, synchronous registration pattern (why `db_id` is available immediately).

### H2: Api Internals
REST and WebSocket interface to HA. Connection management, request routing, timeout handling.

### H2: StateManager and StateProxy
Proxy pattern: StateProxy wraps the WS state cache, StateManager provides the app-facing typed access. Domain routing, DomainStates collection.

### H2: Web/UI Layer
Endpoint registration, SSE streaming for live logs, static file serving, CORS configuration.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `internals_restart_spec.py` | Review | May move to Lifecycle page instead |

## Cross-Links

- **Links to:** Architecture & Data Flow, Lifecycle & Supervision, each concept overview (Bus, Scheduler, etc.)
- **Linked from:** Architecture & Data Flow
