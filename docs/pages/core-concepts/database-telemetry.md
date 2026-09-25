# Database & Telemetry

Hassette stores operational telemetry in a local SQLite database: every [bus](bus/index.md) handler invocation, every [scheduled job](scheduler/index.md) execution, and app health metrics. The [web UI](../web-ui/index.md) reads this data for its panels — the stats strip on the Apps page, the Error Spotlight, and the handler health grid all draw from it.

## What Is Collected

Hassette records four types of data automatically, with no configuration required.

**Handler invocations.** Every app-tier bus listener firing produces a row in the `executions` table. Each row captures the start time, wall-clock duration, and outcome (`success`, `error`, `cancelled`, or `timed_out`). Failed executions include full exception details. Framework-tier handler invocations are filtered by default — errors and slow executions are always recorded, while routine successes are sampled at a configurable rate (see `framework_record_errors`, `framework_record_slow_ms`, and `framework_record_sample_rate` below).

**Job executions.** Every app-tier scheduled job run produces a row in the same `executions` table. A `kind` column distinguishes handler rows from job rows. Jobs support one additional outcome: `skipped`, recorded when a [`where=` predicate](scheduler/index.md#conditional-execution) returns `False` at dispatch time. Skipped executions have zero duration. Framework-tier jobs follow the same filtering rules as handler invocations.

**Listener registrations.** Every registered bus listener is stored by name and topic in the `listeners` table. Counts appear in the Apps page stats strip.

**Job registrations.** Every scheduled job is stored in the `scheduled_jobs` table. Counts appear alongside listener counts in the stats strip.

### Source Tier

Framework-internal handlers (telemetry workers, WebSocket service, scheduler services) are counted in the stats strip alongside app registrations. Framework errors appear in the unified Error Spotlight with a **Framework** badge and the component name, for example Service Watcher or App Handler. The Handler health grid shows only app-registered handlers. Framework components are excluded.

??? note "Internal detail"
    Framework handlers are stored with `source_tier='framework'` and an `app_key` of the form `__hassette__.<ClassName>`, built from the component's Python class name, for example `__hassette__.ServiceWatcher` or `__hassette__.Hassette`. The web UI reads this value to display the component name in the Framework badge. The Handler health grid filters out all framework keys; the stats strip and Error Spotlight include all tiers.

## Configuration

All database settings are optional and live in `hassette.toml` (see [Configuration](configuration/index.md)). The defaults work well for most setups.

```toml
--8<-- "pages/core-concepts/snippets/database-telemetry/db_config.toml"
```

| Field | Type | Default | Description |
|---|---|---|---|
| `path` | path or null | `null` | Location of the SQLite database file. When null, Hassette stores the database at `{data_dir}/hassette.db` (`~/.local/share/hassette/v0/hassette.db` on Linux). |
| `retention_days` | integer | `7` | Days of app-tier execution records to retain. Records older than this value are deleted automatically. Minimum: 1. |
| `framework_retention_days` | integer | `1` | Days of framework-tier execution records to retain. Framework-internal handlers (telemetry workers, WebSocket service, scheduler services) run far more often than app handlers, so they get a shorter window. Must be `<= retention_days`. |
| `max_size_mb` | float | `500` | Maximum database size in megabytes. When exceeded, the oldest records are deleted in batches, highest-volume tier first: framework executions, then blocking events, then app executions. Log records are never deleted by this failsafe — only by `logging.log_retention_days`. A value of `0` disables the size limit. |
| `framework_record_errors` | bool | `true` | Always persist framework-tier executions with any non-success status (errors, timeouts, cancellations, skips). When `false`, framework errors are sampled at the same rate as routine successes. |
| `framework_record_slow_ms` | float or null | `100.0` | Persist framework-tier executions whose duration exceeds this threshold (in milliseconds), regardless of status. `null` disables duration-based persistence. |
| `framework_record_sample_rate` | float | `0.0` | Fraction of routine (successful, fast) framework-tier executions to persist. `0.0` drops all routine framework executions; `1.0` persists everything. Values between 0 and 1 sample randomly. |

??? note "Advanced: queue, interval, and failsafe tuning"
    The remaining `[hassette.database]` fields tune internals. They rarely need changing; the symptoms below name the cases that do.

    **Write queues.** `write_queue_max` (default 2000) bounds the pending write queue; when full, some telemetry writes are silently dropped — automations are not affected. `telemetry_write_queue_max` (default 1000) bounds the telemetry record queue the same way. `max_flush_interval_seconds` (default 5.0) forces a batch flush even when the batch-size threshold has not been reached. Raise the queue bounds when sustained event bursts log dropped-record warnings and memory headroom exists.

    `write_submit_timeout_seconds` (default 60.0) caps how long an awaited write waits in the queue before it starts. A long retention or size-failsafe pass holds the queue, and writes queued behind it would otherwise wait for the whole pass. On expiry, Hassette withdraws the write without running it. Telemetry batches retry later; listener and job registrations raise `TimeoutError`. A write that has already started always runs to completion. Raise the timeout when registrations time out on slow storage during maintenance passes.

    As the telemetry write queue fills, Hassette logs a rate-limited capacity WARNING before it hits `write_queue_full`/drops. Two `[hassette.lifecycle]` fields tune it: `command_executor_capacity_warn_threshold` (default `0.75`) is the fraction of `telemetry_write_queue_max` that must be filled before the WARNING fires, and `command_executor_capacity_warn_rate_limit_seconds` (default `30.0`) is the minimum seconds between repeated WARNINGs. These are independent from the sync-handler pool's saturation WARNING (see [Sync-handler pool](../operating/index.md#sync-handler-pool)) — the two govern different subsystems and can be tuned separately.

    **Health and reads.** `heartbeat_interval_seconds` (default 300) is the gap between database health checks; `max_consecutive_heartbeat_failures` (default 3) failures put the service in [degraded mode](#degraded-mode). `read_timeout_seconds` (default 10.0) caps telemetry read queries before `TimeoutError`. `migration_timeout_seconds` (default 120) caps schema migrations at startup — raise it on slow storage with a large database.

    **Retention cadence.** `retention_interval_seconds` (default 3600) and `size_failsafe_interval_seconds` (default 3600) set how often the two maintenance routines run. Retention deletes `retention_delete_batch` rows per batch (default 1000), up to `retention_max_batches_per_target` batches per table per run (default 100); the next run picks up any remainder. The size failsafe deletes `size_failsafe_delete_batch` rows per batch (default 1000), up to `size_failsafe_max_iterations` batches per run (default 10), then vacuums `size_failsafe_vacuum_pages` pages (default 100). Lower the intervals when the database overshoots `max_size_mb` between runs.

### How Retention Works

Two maintenance routines run every hour in the background.

Time-based retention deletes from four targets independently: framework-tier execution records older than `framework_retention_days` (default: 1), app-tier execution records older than `retention_days` (default: 7), [blocking-event](blocking-io-detection.md) records older than `retention_days`, and log records older than `logging.log_retention_days` (default: 3). Each target commits in its own batches, so a failure or a large backlog on one target does not block the others. Internal bookkeeping records (session tracking) are not affected.

Retired listener and job registrations are cleaned up separately, after every one of the four targets above has fully cleared its own cutoff window for the current cycle. If any target fails or leaves a backlog past the per-cycle batch cap, the registration cleanup is skipped for that cycle and retried on the next one — this prevents deleting a registration whose child execution records have not actually been fully removed yet.

Size-based retention runs after time-based retention. When the total database size (including WAL files) exceeds `max_size_mb`, the oldest records are deleted in priority order: framework executions first, then blocking events, then app executions.

Log records are exempt from this failsafe entirely — they are only ever deleted by the time-based pass, on `logging.log_retention_days`. The table is a rounding error next to executions, so deleting it reclaims almost no space while destroying the records most needed to work out what filled the database in the first place.

A tier fully drains before the next tier starts — as long as its deletes succeed. If a tier hits its per-cycle iteration cap with records still remaining, the run stops there for this cycle instead of touching lower-priority tiers; the next hourly run retries the capped tier first. A DELETE, commit, or vacuum failure marks that one tier incomplete instead and moves on to the next tier, so a transient error on one tier doesn't block the whole cycle — the failed tier retries next hour. This means a higher-priority backlog can be left behind while lower-priority data is deleted, but only when that tier's own processing failed; a tier that hits the iteration cap never yields to a lower-priority one. Deletion continues until the database is back under the limit or every tier has drained, capped, or been skipped.

Both routines are non-blocking and do not interrupt automations or telemetry collection.

## Registration Persistence

Listener and job registrations survive restarts. On startup, Hassette matches existing registrations against the database by natural key. A listener's natural key combines the app key, instance index, `name=` value, and topic. A job's natural key combines the app key, instance index, and `name=` value, since jobs have no topic. Predicate configuration is stored as display metadata and does not affect matching. Matched registrations are updated in place via upsert semantics. Registrations absent from the new session receive a `retired_at` timestamp rather than deletion.

The Apps page stats strip shows accurate counts even after a restart because of this persistence. Historical registrations from prior sessions remain visible in the web UI until they age out of the retention window. During development, renaming a handler or changing its topic leaves the old registration visible until it ages out (default 7 days).

## Checking Telemetry Health

Three commands and their API equivalents cover telemetry and system health.

**Telemetry pipeline health.** `hassette telemetry` queries `/api/telemetry/status` and reports whether the database is reachable.

| Response | HTTP status | Meaning |
|---|---|---|
| `{"degraded": false}` | 200 | Database is healthy |
| `{"degraded": true}` | 503 | Database is unavailable |

**System-level health.** `hassette status` queries `/api/health`, which reports the overall status of the Hassette process. The endpoint returns HTTP 200 in all states while the process can serve. It never returns 503 from the handler itself:

| `status` body field | HTTP | Meaning |
|---|---|---|
| `ok` | 200 | WebSocket currently connected (per-service health is in the `services` field) |
| `degraded` | 200 | Was connected at least once; currently disconnected (e.g. HA restarting) |
| `starting` | 200 | Has not finished the initial connection yet |

A fatal crash (a PERMANENT service exhausting its restart budget, or a startup failure) records a `failure` status to the current telemetry session before Hassette exits with a non-zero exit code. A clean operator shutdown (SIGTERM / `docker stop`) exits 0.

For container restart automation, use `/api/health/live` or rely on the non-zero exit and a restart policy. Use `/api/health` for the human-readable aggregate view and use `/api/health/ready` for load-balancer routing. See [Configure Health Checks](../web-ui/health-endpoints.md) for the full reference.

!!! note "Choosing the right endpoint"
    Use `/api/health/live` (or the non-zero exit + restart policy) for restart automation. Use `/api/health/ready` for traffic routing. Use `/api/health` for the aggregate human view. Use `/api/telemetry/status` to monitor specifically whether the telemetry database is functional.

**Execution history.** `hassette log --app <key>` shows recent log entries for an app. `hassette execution <uuid>` shows the log lines emitted during a specific invocation. Execution metadata (trigger origin, error traceback) appears in `hassette listener <id>` and `hassette job <id>` output. The UUID comes from the `Execution ID` column of `hassette listener <id>` or `hassette job <id>` output.

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
