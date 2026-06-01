# Database & Telemetry

**Status:** Exists (127 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: What Is Collected
Listener invocations, scheduler executions, registration events. Source tier explanation.

### H2: Execution Columns
Table of fields in the unified executions table.

### H2: Configuration
Telemetry settings in hassette.toml. Retention policy.
#### H3: How Retention Works

### H2: Monitoring Telemetry Health
#### H3: `/api/telemetry/status` — endpoint for checking telemetry pipeline
#### H3: `/api/health` — general health endpoint

### H2: Registration Persistence
How listener and job registrations are stored.

### H2: Degraded Mode
What happens when the database fails. Graceful degradation.
#### H3: Recovery

## Snippet Inventory

No dedicated snippets — this page is prose + tables + endpoint examples.

## Cross-Links

- **Links to:** Web UI/Logs (viewing telemetry data), Configuration/Global (db settings), Operating (degraded mode)
- **Linked from:** Architecture, System Internals
