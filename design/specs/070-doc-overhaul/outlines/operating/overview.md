# Operating Hassette — Overview

**Status:** Stub (3 lines), new page
**Voice mode:** Concept/procedural hybrid — system-as-subject for behavior descriptions, "you" for actions

## Outline

### H2: (Opening)
What this section covers: how Hassette behaves at runtime and how to operate it in production.

### H2: Runtime Behavior

#### H3: WebSocket Reconnection
**Content from KI-01.** Full reconnection sequence: initial retries (5x, 1s→32s backoff), ServiceWatcher RestartSpec (5 restarts / 300s window, 2s→60s backoff), EXHAUSTED_COOLING (300s cooldown), bus events (`websocket_disconnected`, `websocket_connected`), app behavior during reconnection (API raises `ResourceNotReadyError`, handlers resume automatically). Include log signatures.

#### H3: Handler Exception Behavior
**Content from KI-02.** Exceptions caught and swallowed, logged at ERROR, recorded in telemetry with `status='error'`. Include log signature. Matches scheduler behavior.

#### H3: Database Degraded Mode
Brief: what happens when the DB is unavailable. Links to Database & Telemetry page for full details.

### H2: See Also
→ Log Level Tuning, → Upgrading, → Troubleshooting

## Snippet Inventory

No code snippets — log signatures are inline code blocks.

## Cross-Links

- **Links to:** Log Level Tuning, Upgrading, Troubleshooting, Database & Telemetry, Configuration/Global (WebSocket resilience settings)
- **Linked from:** Architecture, Troubleshooting (cross-reference)
