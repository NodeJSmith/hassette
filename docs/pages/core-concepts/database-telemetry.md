# Database & Telemetry

Hassette stores operational telemetry in a local SQLite database. This data powers the Apps page stats strip, handler invocations, job executions, and app health metrics in the [web UI](../web-ui/index.md).

## What Is Collected

Hassette records two types of telemetry:

- **Handler invocations** — every time an event bus listener fires, the database records the start time, duration, success/failure, and any error details.
- **Job executions** — every time a scheduled job runs, the same metrics are recorded.

Telemetry is collected automatically. You do not need to enable it or write any code — it works out of the box.

### Source Tier

Framework-internal handlers (telemetry workers, WebSocket service, scheduler services) are included in Apps page stats strip counts alongside your app registrations. Framework errors appear in the unified **Error Spotlight** with a **Framework** badge and the component name (e.g. Service Watcher, App Handler), so you can distinguish them from your app errors at a glance. The **Handler health grid** shows only your apps — framework components do not appear there.

??? note "Internal detail"
    Internally, framework handlers are stored with `source_tier='framework'` and a component-specific `app_key` of the form `__hassette__.<component>` — for example `__hassette__.service_watcher`, `__hassette__.app_handler`, or `__hassette__.core`. This naming identifies which part of the framework produced an error and is used by the web UI to display the component name in the **Framework** badge. The Handler health grid filters out all framework keys, while the stats strip and Error Spotlight include all tiers by default.

## Execution Columns

Handler invocations and job executions are stored together in a single `executions` table. A `kind` column (`'handler'` or `'job'`) distinguishes the two. Handler rows carry a `listener_id` foreign key; job rows carry a `job_id` foreign key. Exactly one of the two is non-null per row.

The following columns are present on every row regardless of `kind`.

| Column | Type | Description |
|--------|------|-------------|
| `kind` | string | `'handler'` for bus listener invocations; `'job'` for scheduled job executions |
| `listener_id` | integer \| null | Foreign key into `listeners`. Set for handler rows; `null` for job rows. |
| `job_id` | integer \| null | Foreign key into `scheduled_jobs`. Set for job rows; `null` for handler rows. |
| `execution_start_ts` | float | Unix timestamp when execution started |
| `duration_ms` | float | Wall-clock time in milliseconds |
| `status` | string | Outcome: `success`, `error`, `cancelled`, or `timed_out` |
| `is_di_failure` | boolean | Whether the execution failed due to a dependency injection error (handler rows only; always `0` for job rows) |
| `source_tier` | string | `app` for user automations, `framework` for internal Hassette components |
| `error_type` | string \| null | Exception class name, if execution raised an error |
| `error_message` | string \| null | Exception message, if execution raised an error |
| `error_traceback` | string \| null | Full Python traceback, if execution raised an error |
| `execution_id` | string \| null | UUID tying this row to a specific trigger delivery or scheduler invocation. `null` for rows written before this feature was added. |
| `trigger_context_id` | string \| null | UUID identifying the event that triggered a handler. For HA events, this is `context.id` from the originating Home Assistant event and is stable across all handlers receiving the same event. For Hassette-internal events, unique per firing. `null` for job rows and for rows written before this feature was added. |
| `trigger_origin` | string \| null | Where the trigger originated: `LOCAL`, `REMOTE`, or `HASSETTE`. `null` for job rows and for rows written before this feature was added. |

### Pre-migration rows

The `execution_id`, `trigger_context_id`, and `trigger_origin` columns were added in a schema migration. Rows written before this migration have `null` in all three columns. The web UI renders `null` as "—" in the Trace ID, Trigger, and Origin columns.

## Configuration

All database settings are optional. The defaults work well out of the box.

```toml
--8<-- "pages/core-concepts/snippets/database-telemetry/db_config.toml"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | path or null | `null` | Location of the SQLite database file. When null (default), Hassette stores the database at `{data_dir}/hassette.db`. |
| `retention_days` | integer | `7` | How many days of handler invocation and job execution records to keep. Records older than this are automatically deleted. Minimum: 1 day. |
| `max_size_mb` | float | `500` | Maximum total database file size in megabytes. When exceeded, Hassette deletes the oldest execution records to reclaim space. Set to `0` to disable the size limit. |

### How Retention Works

Hassette runs two automatic maintenance routines:

1. **Time-based retention** — every hour, records older than `retention_days` are deleted from the `executions` table. Internal bookkeeping records (session tracking) are not affected by retention cleanup.
2. **Size-based failsafe** — every hour, if the total database size (including WAL files) exceeds `max_size_mb`, the oldest execution records are deleted in batches until the database is back under the limit.

Both routines run in the background and do not block normal operation.

## Monitoring Telemetry Health

### `/api/telemetry/status`

This endpoint checks whether the telemetry database is healthy and responding to queries.

| Response | Status Code | Meaning |
|----------|-------------|---------|
| `{"degraded": false}` | 200 | Database is healthy |
| `{"degraded": true}` | 503 | Database is unavailable |

Use this endpoint if you want to monitor specifically whether telemetry data collection is working. When degraded, the web UI continues to function but shows zeroed-out metrics.

### `/api/health`

This is the **system-level** health check for Hassette as a whole. It reports the overall status of the Hassette process — whether it is running, starting up, or shutting down. Use this endpoint for Docker health checks and uptime monitoring.

```yaml
--8<-- "pages/core-concepts/snippets/database-telemetry/healthcheck.yml"
```

!!! note "Choosing the right endpoint"
    Use `/api/health` for container orchestration and uptime monitoring. Use `/api/telemetry/status` if you specifically need to know whether the telemetry database is functional.

## Registration Persistence

Listener and job registrations are stored in the database and survive restarts. When Hassette starts, existing registrations are matched by their natural key (handler name, topic, and predicate signature — or the explicit `name=` value) and updated in place via upsert semantics. Registrations that no longer exist in the new session are marked with a `retired_at` timestamp rather than deleted.

This means the Apps page stats strip shows accurate handler and job counts even for registrations that predate the current startup. Historical registrations from prior startups remain visible in the web UI until they age out of the retention window.

## Degraded Mode

When the telemetry database becomes unavailable (disk full, permissions error, corruption), Hassette enters **degraded mode**:

- The web UI continues to work, but telemetry-backed panels (stats strip, Error Spotlight, handler/job metrics) show empty or zeroed-out data.
- The status bar shows a degraded indicator to alert you.
- Your automations continue to run normally — telemetry is an observability layer, not a dependency for app execution.
- All telemetry is unavailable — including [persisted registrations](#registration-persistence). Because registration data lives in the same SQLite file, handler and job counts will also show zero until the database recovers.

### Recovery

To resolve a degraded state:

1. **Check disk space** — in Docker: `docker compose exec hassette df -h /data`
2. **Check file permissions** — ensure the Hassette user can write to the database path
3. **Delete and restart** — if the database is corrupted, deleting it is safe. Only telemetry history is lost; your automations are unaffected:

    ```bash
    --8<-- "pages/core-concepts/snippets/database-telemetry/db_recovery.sh"
    ```

    Hassette will recreate the database on next startup.

## Related Resources

- [Global Configuration](configuration/global.md) — all configuration fields
- [App Cache](cache/index.md) — the disk cache for app data (separate from telemetry)
