# Database & Telemetry

Hassette stores operational telemetry in a local SQLite database: every [bus](bus/index.md) handler invocation, every [scheduled job](scheduler/index.md) execution, and app health metrics. The [web UI](../web-ui/index.md) reads this data for its panels — the stats strip on the Apps page, the Error Spotlight, and the handler health grid all draw from it.

## What Is Collected

Hassette records five types of data automatically, with no configuration required.

**Handler invocations.** Every app-tier bus listener firing produces a row in the `executions` table. Each row captures the start time, wall-clock duration, and outcome (`success`, `error`, `cancelled`, or `timed_out`). Failed executions include full exception details. Framework-tier handler invocations are filtered by default — errors and slow executions are always recorded, while routine successes are sampled at a configurable rate (see `framework_record_errors`, `framework_record_slow_ms`, and `framework_record_sample_rate` below).

Each handler row also records what fired it: the event's topic (such as `hass.event.state_changed`), the entity, and the old and new value. It also records the event's context id, parent context id, and origin. The values are the entity's state, or the tracked attribute for an [`on_attribute_change`](bus/methods.md) listener. They're stored for reading, not parsing: a string as Home Assistant reports it, anything else as compact JSON. Either form is cut to 255 characters with a trailing `…`.

Values are stored without redaction. A listener on an entity that holds private data, such as a person's location or an `input_text`, keeps those values in the database for as long as the row lives. `retention_days` (below) sets how long that is; lower it to keep them for less time.

A duration or debounced listener's row describes the event that started the hold or debounce. It doesn't describe the state when the handler ran. An `immediate=True` run has no old value and has origin `HASSETTE_SYNTHETIC`. It carries the context of the change that set the current state. A `where=` or hold predicate can raise while checking the current state, on an immediate fire or when a duration listener's hold ends. Its error row has the same old value, context, and origin. Rows written before this field was added have only the context id and origin.

**Job executions.** Every app-tier scheduled job run produces a row in the same `executions` table. A `kind` column distinguishes handler rows from job rows. Jobs support one additional outcome: `skipped`, recorded when a [`where=` predicate](scheduler/index.md#conditional-execution) returns `False` at dispatch time. Skipped executions have zero duration. Framework-tier jobs follow the same filtering rules as handler invocations.

**API writes.** Every write an app sends to Home Assistant through `self.api` produces a row in the `api_writes` table: `call_service` (including `turn_on`, `turn_off`, `toggle`, `notify` and the counter helpers), `fire_event`, `set_state`, `delete_entity`, and helper `create`, `update` and `delete`. That includes the action methods of an entity fetched with `self.api.get_entity`, such as `unlock`. The row is written when the call is sent, so a call still in flight already shows, and updated once Hassette learns how it ended. `hassette execution <id>` lists the writes a handler or job run made.

Each row records the app and instance, the run that made it (none for a write from `on_initialize`), the kind and operation (`light.turn_on`, the event type, or the helper domain), the target, the rest of the data, and the outcome. The target holds what Home Assistant acts on, whichever way the call passed it: `target={"entity_id": "light.porch"}` and `entity_id="light.porch"` both record `{"entity_id": ["light.porch"]}`. The data is a display string like the trigger values above, cut to 2,048 characters.

| Outcome | Meaning |
| --- | --- |
| `pending` | Sent, and no answer yet. |
| `success` | Home Assistant's handler returned. It doesn't mean the device changed state. |
| `rejected` | Home Assistant answered with an error. `error_code` holds its code, or the HTTP status for `set_state` and `delete_entity`. |
| `connection_lost` | Sent, then the connection ended (or the request was abandoned) before an answer. The call may or may not have applied. |
| `unresolved` | Sent, but how it ended wasn't recorded. This happens when Hassette restarts while the call is pending, or when more than 10,000 calls are waiting on an answer that no handler is still waiting for (fire-and-forget calls, or ones whose handler timed out) and this is the oldest. The call may or may not have applied. |
| `not_sent` | Never reached Home Assistant, for example because the connection was down. |

Recording is best-effort. If the database write queue is full when an outcome arrives, the outcome is dropped and counted, and the row stays `pending` until the next restart marks it `unresolved`.

A handler that times out or is cancelled doesn't stop Home Assistant from finishing the call, so its row keeps waiting for the answer. Writes made through the framework's own `Api` or through `RecordingApi` in tests aren't recorded, and neither are the internal transport methods.

When a handler run's trigger context matches a recorded write's context, the run's `trigger.caused_by` names the app, instance, run, kind and operation of that write. An `immediate=True` run carries the context of whatever last set the state, so its `caused_by` is the write that set that state, not what fired the run. Only a direct match counts: a write that sets off a Home Assistant automation isn't reported on the automation's downstream runs. Once the write's row ages out, the match is gone.

Like trigger values, write data is stored without redaction. Alarm and lock `code` values, password-mode helper values and tokens land in the database as passed. A value wrapped in `SecretStr` is stored masked, while Home Assistant still gets the real value. `hassette execution --json` output can therefore hold credentials, so check it before sharing it.

A typical write row takes about 460 bytes. An app making 1,000 writes a day keeps about 30,000 rows under the default 30-day `retention_days`, roughly 14 MB. Long `data` adds up to about 2 KB a row.

**Listener registrations.** Every registered bus listener is stored by name and topic in the `listeners` table. Counts appear in the Apps page stats strip.

**Job registrations.** Every scheduled job is stored in the `scheduled_jobs` table. Counts appear alongside listener counts in the stats strip.

### Source Tier

Framework-internal handlers (telemetry workers, WebSocket service, scheduler services) are counted in the stats strip alongside app registrations. Framework errors appear in the unified Error Spotlight with a **Framework** badge and the component name, for example Bus Service or App Handler. The Handler health grid shows only app-registered handlers. Framework components are excluded.

??? note "Internal detail"
    Framework handlers are stored with `source_tier='framework'` and an `app_key` of the form `__hassette__.<ClassName>`, built from the component's Python class name, for example `__hassette__.BusService` or `__hassette__.Hassette`. The web UI reads this value to display the component name in the Framework badge. The Handler health grid filters out all framework keys; the stats strip and Error Spotlight include all tiers.

## Configuration

All database settings are optional and live in `hassette.toml` (see [Configuration](configuration/index.md)). The defaults work well for most setups.

```toml
--8<-- "pages/core-concepts/snippets/database-telemetry/db_config.toml"
```

| Field | Type | Default | Description |
|---|---|---|---|
| `path` | path or null | `null` | Location of the SQLite database file. When null, Hassette stores the database at `{data_dir}/hassette.db` (`~/.local/share/hassette/v0/hassette.db` on Linux). |
| `shutdown_snapshot_path` | path or null | `null` | Where Hassette writes a single-file copy of the database on each clean shutdown, for backup setups that leave out the live database files. The copy is written under a temporary name and renamed into place, so the file is always complete. The Home Assistant add-on sets it so a backup taken while the add-on is stopped still holds the database. The add-on also restores this copy at start whenever the database file is missing, so deleting the database alone brings the copy back; delete both to start fresh. |
| `retention_days` | integer | `30` | Days of app-tier execution records to retain. Records older than this value are deleted automatically. Minimum: 1. Lowering it below 30 also requires lowering `framework_retention_days` and `logging.log_retention_days` to at most the new value. |
| `framework_retention_days` | integer | `30` | Days of framework-tier execution records to retain. Framework-internal handlers (telemetry workers, WebSocket service, scheduler services) are tracked separately from app handlers, so lowering this window trims framework history without touching app records. Must be `<= retention_days`. |
| `max_size_mb` | float | `500` | Maximum live data in megabytes: the in-use pages of the database, not the file on disk. Free pages and the WAL don't count, so the file can sit above this value until unused pages are reclaimed. When exceeded, the oldest records are deleted in batches, in this order: persisted DEBUG log lines, then framework executions, then blocking events, then API writes, then app executions. Log lines at INFO and above are never deleted by this failsafe — only by `logging.log_retention_days`. A value of `0` disables the size limit. |
| `framework_record_errors` | bool | `true` | Always persist framework-tier executions with any non-success status (errors, timeouts, cancellations, skips). When `false`, framework errors are sampled at the same rate as routine successes. |
| `framework_record_slow_ms` | float or null | `100.0` | Persist framework-tier executions whose duration exceeds this threshold (in milliseconds), regardless of status. `null` disables duration-based persistence. |
| `framework_record_sample_rate` | float | `0.0` | Fraction of routine (successful, fast) framework-tier executions to persist. `0.0` drops all routine framework executions; `1.0` persists everything. Values between 0 and 1 sample randomly. |

??? note "Advanced: queue, interval, and failsafe tuning"
    The remaining `[hassette.database]` fields tune internals. They rarely need changing; the symptoms below name the cases that do.

    **Write queues.** `write_queue_max` (default 2000) bounds the pending write queue; when full, some telemetry writes are silently dropped — automations are not affected. `telemetry_write_queue_max` (default 1000) bounds the telemetry record queue the same way. `max_flush_interval_seconds` (default 5.0) forces a batch flush even when the batch-size threshold has not been reached. Raise the queue bounds when sustained event bursts log dropped-record warnings and memory headroom exists.

    `write_submit_timeout_seconds` (default 60.0) caps how long an awaited write waits in the queue before it starts. A long retention or size-failsafe pass holds the queue, and writes queued behind it would otherwise wait for the whole pass. On expiry, Hassette withdraws the write without running it. Telemetry batches retry later; listener and job registrations raise `TimeoutError`. A write that has already started always runs to completion. A higher value tolerates slower storage during maintenance passes without registrations timing out.

    As the telemetry write queue fills, Hassette logs a rate-limited capacity WARNING before it hits `write_queue_full`/drops. Two `[hassette.lifecycle]` fields tune it: `command_executor_capacity_warn_threshold` (default `0.75`) is the fraction of `telemetry_write_queue_max` that must be filled before the WARNING fires, and `command_executor_capacity_warn_rate_limit_seconds` (default `30.0`) is the minimum seconds between repeated WARNINGs. These are independent from the sync-handler pool's saturation WARNING (see [Sync-handler pool](../operating/index.md#sync-handler-pool)) — the two govern different subsystems and can be tuned separately.

    **Health and reads.** `heartbeat_interval_seconds` (default 30) is the gap between database health checks. A failed check counts toward `max_consecutive_heartbeat_failures` (default 3) only when no database write completed since the previous check. That many counted failures put the service in [degraded mode](#degraded-mode). A long retention pass that keeps committing batches therefore never trips the limit. `read_timeout_seconds` (default 10.0) caps telemetry read queries before `TimeoutError`. `migration_timeout_seconds` (default 120) caps schema migrations at startup — raise it on slow storage with a large database.

    **Retention cadence.** `retention_interval_seconds` (default 3600) and `size_failsafe_interval_seconds` (default 3600) set how often the two maintenance routines run. Retention deletes `retention_delete_batch` rows per batch (default 1000), up to `retention_max_batches_per_target` batches per retention target per run (default 100); the next run picks up any remainder. The size failsafe deletes `size_failsafe_delete_batch` rows per batch (default 1000), up to `size_failsafe_max_iterations` batches per run (default 10). Shorter intervals keep the database closer to `max_size_mb` between runs.

### How Retention Works

Two maintenance routines run every hour in the background.

Time-based retention deletes from five targets independently: framework-tier execution records older than `framework_retention_days` (default: 30), app-tier execution records older than `retention_days` (default: 30), [blocking-event](blocking-io-detection.md) records and API writes older than `retention_days`, and log records older than `logging.log_retention_days` (default: 30). Each target commits in its own batches, so a failure or a large backlog on one target does not block the others. After those deletes succeed, the same pass removes session records (one per Hassette start, including crash details) that ended more than `retention_days` ago and no longer have any execution, blocking-event or API write records pointing at them. The current session is never removed.

Retired listener and job registrations are cleaned up separately, after every one of the five targets above has fully cleared its own cutoff window for the current cycle. If any target fails or leaves a backlog past the per-cycle batch cap, the registration cleanup is skipped for that cycle and retried on the next one — this prevents deleting a registration whose child execution records have not actually been fully removed yet.

Registration cleanup also clears out apps removed from config, so it runs only on the same cycles. Once a removed app is no longer running, the next cycle retires its listener and job registrations. The app is dropped after everything it left behind has aged out: those registrations, its executions, its log records, its blocking events, and its API writes. The sidebar stops listing a removed app as soon as it leaves config. The Apps page does too, unless one of the app's instances is flagged as needing a Hassette restart. Its history stays in the database until it ages out: its detail page still opens from a direct link, and an app added back to config picks up whatever of its history has not aged out yet.

Hassette decides which apps were removed from its own config and running apps, so a database belongs to one running Hassette process. Don't point two instances at the same `path` or `data_dir`.

In the hourly cycle, size-based retention runs after time-based retention; the one-time catch-up at startup runs it first. When live data (the database's in-use pages, excluding free pages and the WAL) exceeds `max_size_mb`, the oldest records are deleted in priority order: DEBUG log lines first, then framework executions, then blocking events, then API writes, then app executions.

DEBUG log lines are stored whenever a logger runs at `DEBUG`: a `logging.*` field, an app's `log_level` or `framework_log_level`, or [debug capture](../operating/log-levels.md#debug-capture-for-one-app). They can outgrow everything else in the database, so they go first. Log lines at INFO and above are exempt from this failsafe entirely: only the time-based pass deletes them, on `logging.log_retention_days`. Without DEBUG lines the table stays small next to executions, so deleting from it would reclaim little space while destroying the records most needed to work out what filled the database in the first place.

Keeping DEBUG lines is best-effort against `max_size_mb`. On a database near the limit, a DEBUG line may last only about one failsafe interval. Each run deletes at most `size_failsafe_max_iterations` × `size_failsafe_delete_batch` rows (10 × 1,000 by default), so the database stays over the limit while DEBUG lines arrive faster than that, or while more DEBUG lines are stored than one run can delete. That second case happens once after upgrading a database that already held many DEBUG lines: they drain at one run's worth per failsafe interval even with capture off. Until they do, executions are not trimmed: the run stops at the DEBUG tier rather than moving on to them. Raise either setting to delete faster.

Session records are never deleted by the failsafe either. They're tiny next to the size limit, and the time-based pass removes them once nothing references them.

A tier fully drains before the next tier starts — as long as its deletes succeed. If a tier hits its per-cycle iteration cap with records still remaining, the run stops there for this cycle instead of touching lower-priority tiers; the next hourly run retries the capped tier first. A DELETE failure marks that one tier incomplete instead and moves on to the next tier, so a transient error on one tier doesn't block the whole cycle — the failed tier retries next hour. This means a higher-priority backlog can be left behind while lower-priority data is deleted, but only when that tier's own processing failed; a tier that hits the iteration cap never yields to a lower-priority one. Deletion continues until live data is back under the limit or every tier has drained, capped, or been skipped. After a run that deleted rows, the failsafe makes a best-effort attempt to return the freed pages to the filesystem and truncate the WAL; this never changes what gets deleted. Reclaiming pages shrinks the file only on databases using `auto_vacuum = INCREMENTAL`, which every database created by current Hassette is; older files keep their free pages on disk, which is fine because the limit applies to live data.

Both routines are non-blocking and do not interrupt automations or telemetry collection.

## Registration Persistence

Listener and job registrations survive restarts. On startup, Hassette matches existing registrations against the database by natural key. A listener's natural key combines the app key, instance name, `name=` value, and topic. A job's natural key combines the app key, instance name, and `name=` value, since jobs have no topic. Predicate configuration is stored as display metadata and does not affect matching. Matched registrations are updated in place via upsert semantics. Registrations absent from the new session that have execution history receive a `retired_at` timestamp rather than deletion. Absent registrations with no execution history are deleted outright. `once=True` listeners that are no longer live are deleted once they have no execution in the current session. If the session ID isn't available at startup, their cleanup waits for a later restart.

The Apps page stats strip shows accurate counts even after a restart because of this persistence. Historical registrations from prior sessions remain visible in the web UI until they age out of the retention window. During development, renaming a handler or changing its topic leaves the old registration visible until it ages out (default 30 days), as long as the old one had run at least once.

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
| `ok` | 200 | WebSocket currently connected and app bootstrap released (per-service health is in the `services` field) |
| `degraded` | 200 | Connected at least once, but not fully healthy: either disconnected now (e.g. HA restarting), or connected with app bootstrap not yet released. Check the [`websocket_connected` and `bootstrap_released` fields](../web-ui/health-endpoints.md#aggregate-status-apihealth) to tell which |
| `starting` | 200 | Has not finished the initial connection yet |

A fatal crash (a required service failing after startup, or a startup failure) records a `failure` status to the current telemetry session before Hassette exits with a non-zero exit code. A clean operator shutdown (SIGTERM / `docker stop`) exits 0.

For container restart automation, use `/api/health/live` or rely on the non-zero exit and a restart policy. Use `/api/health` for the human-readable aggregate view and use `/api/health/ready` for load-balancer routing. See [Configure Health Checks](../web-ui/health-endpoints.md) for the full reference.

!!! note "Choosing the right endpoint"
    Use `/api/health/live` (or the non-zero exit + restart policy) for restart automation. Use `/api/health/ready` for traffic routing. Use `/api/health` for the aggregate human view. Use `/api/telemetry/status` to monitor specifically whether the telemetry database is functional.

**Execution history.** `hassette log --app <key>` shows recent log entries for an app. `hassette execution <uuid>` shows a specific invocation's outcome, what triggered it, and the log lines it emitted. Error tracebacks appear in `hassette listener <id>` and `hassette job <id>` output. The UUID comes from the `Execution ID` column of `hassette listener <id>` or `hassette job <id>` output.
With no argument, `hassette listener` and `hassette job` list every listener or job with its ID. [Command Reference](../cli/commands.md) covers each command, and [Workflows](../cli/workflows.md) walks through the full drill-down.

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
3. **Delete and restart.** If the database is corrupted, deleting it is safe. Only telemetry history is lost; automations and configuration are unaffected. If `shutdown_snapshot_path` is set (the Home Assistant add-on sets it), delete that copy too, or the add-on restores it at the next start.

```bash
--8<-- "pages/core-concepts/snippets/database-telemetry/db_recovery.sh"
```

Hassette recreates the database on next startup.

`hassette telemetry` confirms the recovery: `degraded` reads `False`, and `/api/telemetry/status` returns HTTP 200. The degraded indicator also disappears from the status bar.

## Related Resources

- [Global Configuration](configuration/index.md), all configuration fields
- [App Cache](cache/index.md), the disk cache for app data (separate from telemetry)
- [Command Reference](../cli/commands.md), every CLI command for querying telemetry
