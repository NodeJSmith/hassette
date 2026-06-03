# Database & Telemetry

Hassette stores operational telemetry in a local SQLite database. The [web UI](../web-ui/index.md) reads this data to display handler invocations, job executions, app health metrics, and the Apps page stats strip.

## What Is Collected

Hassette records four types of data automatically, with no configuration required.

**Handler invocations.** Every bus listener firing produces a row in the `executions` table. Each row captures the start time, wall-clock duration, and outcome (`success`, `error`, `cancelled`, or `timed_out`). Failed executions include full exception details.

**Job executions.** Every scheduled job run produces an equivalent row. The same columns apply; a `kind` column distinguishes handler rows from job rows.

**Listener registrations.** Every registered bus listener is stored by name and topic in the `listeners` table. Counts appear in the Apps page stats strip.

**Job registrations.** Every scheduled job is stored in the `scheduled_jobs` table. Counts appear alongside listener counts in the stats strip.

### Source Tier

Framework-internal handlers (telemetry workers, WebSocket service, scheduler services) are counted in the stats strip alongside app registrations. Framework errors appear in the unified Error Spotlight with a **Framework** badge and the component name, for example Service Watcher or App Handler. The Handler health grid shows only app-registered handlers. Framework components are excluded.

??? note "Internal detail"
    Framework handlers are stored with `source_tier='framework'` and an `app_key` of the form `__hassette__.<component>`, for example `__hassette__.service_watcher` or `__hassette__.core`. The web UI reads this value to display the component name in the Framework badge. The Handler health grid filters out all framework keys; the stats strip and Error Spotlight include all tiers.

## Configuration

All database settings are optional. The defaults work well for most setups.

```toml
--8<-- "pages/core-concepts/snippets/database-telemetry/db_config.toml"
```

| Field | Type | Default | Description |
|---|---|---|---|
| `path` | path or null | `null` | Location of the SQLite database file. When null, Hassette stores the database at `{data_dir}/hassette.db`. |
| `retention_days` | integer | `7` | Days of execution records to retain. Records older than this value are deleted automatically. Minimum: 1. |
| `max_size_mb` | float | `500` | Maximum database size in megabytes. When exceeded, the oldest execution records are deleted in batches. A value of `0` disables the size limit. |

### How Retention Works

Two maintenance routines run every hour in the background.

Time-based retention deletes execution records older than `retention_days` from the `executions` table. Internal bookkeeping records (session tracking) are not affected.

Size-based retention runs after time-based retention. When the total database size (including WAL files) exceeds `max_size_mb`, the oldest execution records are deleted in batches. Deletion continues until the database is back under the limit.

Both routines are non-blocking and do not interrupt automations or telemetry collection.

## Registration Persistence

Listener and job registrations survive restarts. On startup, Hassette matches existing registrations against the database by natural key. The natural key is the explicit `name=` value, or a key derived from handler name, topic, and predicate signature. Matched registrations are updated in place via upsert semantics. Registrations absent from the new session receive a `retired_at` timestamp rather than deletion.

The Apps page stats strip shows accurate counts even after a restart because of this persistence. Historical registrations from prior sessions remain visible in the web UI until they age out of the retention window.

## Checking Telemetry Health

Three commands and their API equivalents cover telemetry and system health.

**Telemetry pipeline health.** `hassette telemetry` queries `/api/telemetry/status` and reports whether the database is reachable.

| Response | HTTP status | Meaning |
|---|---|---|
| `{"degraded": false}` | 200 | Database is healthy |
| `{"degraded": true}` | 503 | Database is unavailable |

**System-level health.** `hassette status` queries `/api/health`, which reports the overall status of the Hassette process. The endpoint returns HTTP 200 in all states while the process can serve — it never returns 503 from the handler itself:

| `status` body field | HTTP | Meaning |
|---|---|---|
| `ok` | 200 | WebSocket currently connected (per-service health is in the `services` field) |
| `degraded` | 200 | Was connected at least once; currently disconnected (e.g. HA restarting) |
| `starting` | 200 | Has not finished the initial connection yet |

A fatal crash (a PERMANENT service exhausting its restart budget, or a startup failure) records a `failure` status to the current telemetry session before Hassette exits with a non-zero exit code. A clean operator shutdown (SIGTERM / `docker stop`) exits 0.

For container restart automation, use `/api/health/live` or rely on the non-zero exit and a restart policy. Use `/api/health` for the human-readable aggregate view and use `/api/health/ready` for load-balancer routing. See [Health Endpoints](../web-ui/health-endpoints.md) for the full reference.

!!! note "Choosing the right endpoint"
    Use `/api/health/live` (or the non-zero exit + restart policy) for restart automation. Use `/api/health/ready` for traffic routing. Use `/api/health` for the aggregate human view. Use `/api/telemetry/status` to monitor specifically whether the telemetry database is functional.

**Execution history.** `hassette log --app <key>` shows recent log entries for an app. `hassette execution` shows per-execution detail for a specific invocation: trace ID, trigger origin, and error traceback.

## Degraded Mode

When the database becomes unavailable (disk exhaustion, a permissions error, or corruption), Hassette enters degraded mode. Automations continue to run normally. The telemetry pipeline is an observability layer, not a dependency for app execution.

In degraded mode:

- Telemetry-backed panels (stats strip, Error Spotlight, handler and job metrics) show empty or zeroed-out data.
- The status bar displays a degraded indicator.
- [Registration persistence](#registration-persistence) is also unavailable. Handler and job counts show zero until the database recovers, because registration data lives in the same SQLite file.

### Recovery

Three steps resolve most degraded states.

1. **Disk space.** In Docker: `docker compose exec hassette df -h /data`.
2. **File permissions.** The Hassette process must be able to write to the database path.
3. **Delete and restart.** If the database is corrupted, deleting it is safe. Only telemetry history is lost; automations and configuration are unaffected.

```bash
--8<-- "pages/core-concepts/snippets/database-telemetry/db_recovery.sh"
```

Hassette recreates the database on next startup.

## Related Resources

- [Global Configuration](configuration/index.md), all configuration fields
- [App Cache](cache/index.md), the disk cache for app data (separate from telemetry)
