# Database & Telemetry

Hassette stores operational telemetry in a local SQLite database. This data powers the Dashboard KPIs, app health metrics, error feeds, and session history in the [web UI](../web-ui/index.md).

## What Is Collected

Hassette records three types of telemetry:

- **Handler invocations** — every time an event bus listener fires, the database records the start time, duration, success/failure, and any error details.
- **Job executions** — every time a scheduled job runs, the same metrics are recorded.
- **Sessions** — each Hassette startup creates a session row that tracks uptime, heartbeats, and exit status. See [Sessions](../web-ui/sessions.md) for details.

Telemetry is collected automatically. You do not need to enable it or write any code — it works out of the box.

### Source Tier

Framework-internal handlers (telemetry workers, WebSocket service, scheduler services) are recorded with `source_tier='framework'` and excluded from Dashboard KPIs. The **Handlers** and **Jobs** counts on the Dashboard reflect only your app registrations — not Hassette's own housekeeping listeners.

## Configuration

All database settings are optional. The defaults work well for most installations.

```toml
--8<-- "pages/core-concepts/snippets/database-telemetry/db_config.toml"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `db_path` | path or null | `null` | Location of the SQLite database file. When null (default), Hassette stores the database at `{data_dir}/hassette.db`. |
| `db_retention_days` | integer | `7` | How many days of handler invocation and job execution records to keep. Records older than this are automatically deleted. Minimum: 1 day. |
| `db_max_size_mb` | float | `500` | Maximum total database file size in megabytes. When exceeded, Hassette deletes the oldest execution records to reclaim space. Set to `0` to disable the size limit. |

### How Retention Works

Hassette runs two automatic maintenance routines:

1. **Time-based retention** — every hour, records older than `db_retention_days` are deleted from the handler invocations and job executions tables. Session records are not affected by retention cleanup.
2. **Size-based failsafe** — every hour, if the total database size (including WAL files) exceeds `db_max_size_mb`, the oldest execution records are deleted in batches until the database is back under the limit.

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

This means the Dashboard shows accurate handler and job counts even for registrations that predate the current session. Historical registrations from prior sessions remain visible in the web UI until they age out of the retention window.

## Degraded Mode

When the telemetry database becomes unavailable (disk full, permissions error, corruption), Hassette enters **degraded mode**:

- The web UI continues to work, but telemetry-backed panels (KPIs, error rates, handler/job metrics) show empty or zeroed-out data.
- The Dashboard displays a degraded indicator to alert you.
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

- [Sessions](../web-ui/sessions.md) — session history in the web UI
- [Global Configuration](configuration/global.md) — all configuration fields
- [App Cache](cache/index.md) — the disk cache for app data (separate from telemetry)
