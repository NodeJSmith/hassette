# Database & Telemetry

**Status:** Exists (127 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: What Is Collected
Four data categories: listener invocations, scheduler executions, registration events (listeners + jobs), and log records. Also tracks dropped event counters (overflow, exhausted, shutdown). Brief — the reader needs to know *what* is tracked, not the column schema.

### H2: Configuration
Telemetry settings in hassette.toml (`database.*`). Retention policy.
#### H3: How Retention Works

### H2: Monitoring Telemetry Health
Pair each API endpoint with its CLI equivalent so the reader knows both paths.

#### H3: `/api/telemetry/status` and `hassette telemetry`
Checking the telemetry pipeline.
#### H3: `/api/health` and `hassette status`
General health endpoint.
#### H3: `hassette log`, `hassette execution`
Querying logs and execution history from the CLI.

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
