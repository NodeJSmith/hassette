# Database & Telemetry

**Status:** Exists (127 lines), solid content, needs JTBD reorder
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Understand what Hassette tracks automatically and how to check whether telemetry is working — so they can trust the numbers in the web UI and CLI.

## What was cut (and where it goes)

The Execution Columns table (12 columns, pre-migration note) is reference detail that
serves contributors and debuggers, not the typical reader. It moves to a collapsible
section. The Source Tier internals note is already collapsible and stays that way.

The Registration Persistence section is reordered: the current page buries it below
Monitoring, but the reader needs to understand persistence before monitoring makes
sense (registration counts appearing in the UI after restart is surprising without
context).

## Outline

### H2: What Is Collected
Two categories: handler invocations and job executions. Collected automatically — no
code needed. Source Tier callout (framework vs app, how they appear in the web UI).
Keep collapsible "Internal detail" note about `source_tier` column and `__hassette__`
app keys.

### H2: Configuration
Telemetry settings in `hassette.toml` (`database.*`). Three-field table (path,
retention_days, max_size_mb). Defaults work out of the box.

#### H3: How Retention Works
Two routines: time-based (hourly, older than retention_days) and size-based failsafe
(hourly, exceeds max_size_mb). Background, non-blocking.

### H2: Registration Persistence
How listener and job registrations survive restarts. Upsert by natural key, `retired_at`
for removed registrations. Why stats strip shows accurate counts across restarts.

### H2: Checking Telemetry Health
Each check paired with both its API endpoint and CLI equivalent:
- `/api/telemetry/status` / `hassette telemetry` — telemetry pipeline health
- `/api/health` / `hassette status` — system-level health (Docker healthchecks)
- `hassette log` / `hassette execution` — querying logs and execution history

Admonition: choosing between `/api/health` (uptime monitoring) and `/api/telemetry/status` (telemetry-specific).

### H2: Degraded Mode
What happens when the database fails. UI continues, telemetry panels show zeros,
automations unaffected. Registration data also unavailable (same SQLite file).

#### H3: Recovery
Steps: check disk space, check permissions, delete and restart if corrupt.

??? note "Execution Columns"
Full column table for contributors and debuggers. Pre-migration note.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `database-telemetry/db_config.toml` | Keep | TOML config example |
| `database-telemetry/healthcheck.yml` | Keep | Docker healthcheck |
| `database-telemetry/db_recovery.sh` | Keep | Recovery commands |

## Cross-Links

- **Links to:** Configuration/Global (db settings), Web UI/Logs, CLI/Workflows, Operating overview
- **Linked from:** Architecture, System Internals
