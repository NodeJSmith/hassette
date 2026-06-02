# System Internals — Resource Lifecycle & Supervision

**Status:** New page (content from current `internals.md` section 10)
**Voice mode:** Concept — system-as-subject, no "you", contributor/deep-dive audience
**Page type:** Concept (deep-dive)
**Reader's job:** Understand how services start, fail, restart, and die — so they can diagnose service issues or write custom services.

## What was cut (and where it goes)

Nothing cut — this page is new, assembled from the lifecycle section of the monolithic
internals.md. The ordering is redesigned: the current page leads with the state machine
diagram (implementation artifact), but the reader's first question is "what happens
when my service fails?" Start with the supervision story, then show the state machine
as supporting detail.

The `RestartSpec` field reference table stays but moves after the conceptual
explanation, not before it.

## Outline

### H2: What Happens When a Service Fails
Opening: a service that raises an exception transitions to FAILED. `ServiceWatcher`
reads the service's `RestartSpec` and decides what to do next: restart with backoff,
enter a cooldown period, or give up. This is the hook — the reader now knows the
stakes and the actors.

### H2: Restart Types
Three types, each explained by its exhaustion behavior (the only way they differ):
- `PERMANENT` — system shuts down. Used for structural services (BusService, SchedulerService).
- `TRANSIENT` — enters cooldown, then retries. Used for services with intermittent failures (WebsocketService).
- `TEMPORARY` — stops permanently. Used for optional services (FileWatcherService).

Table of per-service restart specs (the existing table from internals.md).

### H2: Restart Budget
Sliding-window model: intensity (max restarts) within a period (window size). Budget
resets on successful recovery. Brief — the reader needs to know the concept, not the
implementation.

### H2: Error Routing
Three-layer routing, simplest to most severe:
1. Normal errors — restart with backoff
2. `non_retryable_error_names` — skip restart, go to exhaustion
3. `fatal_error_names` / `FatalError` subclass — immediate shutdown

### H2: RestartSpec Reference
The full field table (existing content from internals.md). Code example snippet.

### H2: Resource State Machine
State transition diagram (existing Mermaid). Explanation of each state. This comes
last because it is the reference diagram, not the entry point.

### H2: Readiness vs Running
`mark_ready()` vs `handle_running()` table. Why they are separate. Brief.

### H2: Wave Startup and Shutdown
How dependency graph drives startup waves. Shutdown in reverse. Link back to
Architecture & Data Flow for the full dependency graph diagram.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `internals_restart_spec.py` | Keep | `RestartSpec` example, stays on this page |

## Cross-Links

- **Links to:** Architecture & Data Flow (dependency graph), Per-Service Internals, Operating/overview (runtime behavior)
- **Linked from:** Architecture & Data Flow, Operating overview
