---
proposal: "Make the SQLite telemetry DB the source of truth for the web UI and CLI: a one-way projection (process memory -> DB -> UI/CLI), so read routes never consult runtime objects and a seeded DB can be served as-is."
date: 2026-10-16
status: Draft
flexibility: Leaning
motivation: "The in-memory/DB split is complexity not worth keeping, and it blocks serving a seeded DB to the UI without a stub Hassette (also unblocks #855 and #1600)."
constraints: "Pre-v1, clean breaks, no compat shims. Solo dev, ~3 users; argue on design merit. Frontend/WS rework acceptable. Lifecycle history events ship with the projector (no timeline UI committed). Snapshot serve mode is dev-only tooling."
non-goals: "None stated beyond the constraints."
depth: deep
---

# Research Brief: DB as the source of truth for the web UI and CLI

**Initiated by**: "Make the telemetry DB the truth for the UI and CLI, strictly if reasonable; check prior art (HA first) before committing."

## Bottom line

"Strictly everything in the DB" is reasonable for everything the UI shows as **state of the automations**: app and instance status, service status, registrations, next-run times, config snapshots, and even per-listener counters (as periodic snapshots). It is **not** reasonable for a small set of values that describe **the process or the DB pipeline itself**:

- the liveness and readiness probes
- the drop counters and DB health that diagnose the write path
- action routes and auth

None of the prior-art systems routes those through its own DB either.

The line is: **DB for state, process for "am I alive and is my DB pipeline working."** That set is four routes and can be named as one seam.

The write-reliability risk the user flagged is real, but narrower than it looks:

- Every status-like write the DB has today (listener and job registrations, `schedule_status`, manifests) already goes through the awaited, non-dropping `submit()` path. Only append-only telemetry (executions, logs, blocking events) is droppable.
- What's missing is that app, instance and service status are **not persisted at all**.

Every DB-as-truth system surveyed (Airflow, Prefect, Dagster, Temporal) uses the same recipe for status:
- awaited, idempotent current-state writes
- liveness derived from heartbeat age
- notify-after-commit

Hassette can adopt it, plus a periodic **full reconciliation snapshot** so any lost write self-heals within one interval.

Recommendation: **Option A**. It is strict, with that one named live seam, delivered as roughly 9 independently landable issues ending in a `serve-seed` workflow. Spec 087 deliberately rejected persisting status, so the initiative has to reverse that decision explicitly. The brief argues why 087's reasons don't hold up.

## Context

### What prompted this

There are two motivations:
- **Complexity.** The split costs code: `overlay_runtime_state()`, the frontend `appStatus`/`serviceStatus` overlay stores, and the stale-overlay bugs tracked in #1893, #1894, #1895 and #1609.
- **Seeding.** A seeded DB can't drive the UI. `tools/generate_client_compat_fixtures.py:261-281` `build_app()` wraps a real FastAPI app and a real read-only `TelemetryQueryService` around a `MagicMock` Hassette (`tests/support/web_mocks.py:80-295`). That mock fakes:
  - the bootstrap coordinator
  - registry snapshots, `only_apps` and failed instances
  - scheduler jobs
  - `live_execution_counts`
  - drop counters
  - `children`
  - live manifests

  Every one of those is something not in the DB.

### This is the second half of a decision already made once

- **The original stance was DB-only.** The telemetry design `design/research/2026-02-16-sqlite-command-pattern/prereq-04-frontend-query-requirements.md:23` states "Single source of truth: DB only, no parallel in-memory aggregates", and `prereq-06` repeats it.
- **The ADR left room for in-memory pushes.** `design/adrs/0001-sqlite-command-executor-for-telemetry.md:43` adds: "Live WebSocket push can still use in-memory signals."
- **Spec 087 moved part of the way.** `design/specs/087-db-manifest-union` (#1464) moved the app spine and static metadata into `app_manifests`, and named "a seeded DB serves a working dashboard" as a goal.
- **Spec 087 rejected persisting status.** Its Alternative B (`design.md:329`) gives two reasons: "60+ writes during normal boot for 20 apps with 2 instances, or accepting staleness." Status stayed in `AppRegistry`, overlaid at read time.
- **The overlay is what still blocks seeding.** Seeded apps render as `STOPPED` with zero instances, which is why #1600 can't produce DEGRADED from a seed.

### Current state

**Read routes are already mostly DB.** Of about 25 GET endpoints, 11 are pure DB (`TelemetryDep` only). The rest are "DB spine + memory overlay." The CLI reads nothing but the HTTP API: no `sqlite` or `core` imports outside `cli/commands/run.py`. It also reads local config and token files to resolve its target. So the CLI needs no changes of its own. It follows whatever the API returns.

**Inventory of in-memory reads.** Class (a) means already DB-backed, (b) persistable as status rows or events, and (c) high-churn or inherently live.

| # | In-memory source | Read by (route / WS) | UI surface | Class | Replacement DB shape |
|---|---|---|---|---|---|
| 1 | `AppRegistry` status, instances, block reason, errors, `in_current_config`, `enabled`. Read via `overlay_runtime_state` (`core/app_registry.py:391`) and `RuntimeQueryService.overlay_manifest_rows` (`runtime_query_service.py:280`) | `GET /apps`, `GET /apps/{key}`, `GET /telemetry/app-grid` | Apps grid, sidebar, palette, app detail, failed-app banner | b | New `app_instances` current-status table, plus derived status columns on `app_manifests`. Write the **computed** view (output of `build_manifest_info`), not raw inputs |
| 2 | STOPPED placeholder instances synthesized from the config instance count (`app_registry.py:339-352`) | same | same | b | Reconciliation writes a row for every configured instance, including unstarted ones |
| 3 | `registry.only_apps` (`runtime_query_service.py:290`) | `GET /apps` `only_apps` | `--app` filter banner | b | `sessions.only_apps_json` (process-constant) |
| 4 | `app_handler.get_status_snapshot().total_count` | `/health` `app_count`, WS `connected` | Diagnostics | b | `COUNT(*)` over `app_instances` |
| 5 | `collect_boot_issues()` from registry plus bootstrap latch (`runtime_query_service.py:377`) | `/health` `boot_issues` | Diagnostics | b | Derived from `app_instances` plus a `sessions.bootstrap_released_at` column |
| 6 | `hassette.children` status, `_ready_reason`, `_retry_at` (`:336-345`); WS `service_status` | `/health` `services[]`, WS `service_status` | Diagnostics services panel (`mergeServices`) | b | New `service_status` current table (resource_name, role, status, ready, ready_phase, retry_at, exception, session_id, updated_at) |
| 7 | `AppBootstrapCoordinator.is_released()` | `/health` `status`, `bootstrap_released` | Diagnostics | b | `sessions.bootstrap_released_at` |
| 8 | `websocket_service.is_connected` / `has_ever_connected` | `/health` `status`, `websocket_connected`; WS `connectivity` | Diagnostics; `connectivity` triggers a `/health` refetch | b (rare transitions) | `sessions.ha_connected` plus `ha_connected_changed_at`, written on transition |
| 9 | `_start_time` (RQS init) | `/health` `uptime_seconds`, WS `connected` | **`use-scoped-query.ts:71-82` gates and keys every since-restart query on it**; "up Xh" label | b | `sessions.started_at` (exists) |
| 10 | `SchedulerService._jobs_by_id` via `enrich_jobs_with_live` (`web/utils.py:15-58`): `next_run`, `fire_at`, `jitter` | `GET /telemetry/app/{key}/jobs`, `GET /scheduler/jobs` | Handlers page next-run column, job detail | b (per fire for recurring jobs) | `scheduled_jobs.next_run`, `fire_at`, `jitter`. `schedule_status` is already persisted (migration 012) |
| 11 | Job guard `suppressed`/`dropped` (same enrich path) | same | job detail | c | Counter columns on `scheduled_jobs`, snapshotted on the reconcile cadence |
| 12 | `bus_service.live_execution_counts()` (`bus_service.py:258`): guard suppressed, dropped, backpressure_dropped | `GET /bus/listeners`, `GET /telemetry/app/{key}/listeners` | Handlers page, listener detail | c | Counter columns on `listeners`, snapshotted |
| 13 | `bus_service.pending_wait_for_count` | `/health` | Diagnostics | c | `sessions` gauge column, snapshotted |
| 14 | `len(state_proxy.states)` | `/health` and WS `connected` `entity_count` | **No consumer found** in `frontend/src` beyond the store type | c | **Delete the field** |
| 15 | `hassette.config` dump plus `HassetteConfig.model_json_schema()` (`routes/config.py:29-30`) | `GET /config` | Config page, `hassette config` | b (process-constant) | `config_snapshots(session_id, config_json_masked, schema_json)`, written at startup |
| 16 | App config, loaded class's `app_config_cls` schema and masking (`config_view.py:303-307`) | `GET /apps/{key}/config` | Config tab | b | `app_manifests.app_config_json` (masked at write) plus `config_schema_json`, captured at class load |
| 17 | `manifest.full_path` and a disk read (`apps.py:547-587`) | `GET /apps/{key}/source` | Code tab | filesystem, not memory | Persist `full_path`/`app_dir` on `app_manifests`. Snapshot mode returns 404 if the file is absent |
| 18 | `config.logging.log_retention_days` (`routes/executions.py:83`) | `GET /executions/{id}` empty-log hint | Execution drawer | b | Read from `config_snapshots` |
| 19 | Drop counters: `get_drop_counters()`, `get_filtered_count()`, `get_error_handler_failures()` (`command_executor.py:263-278`) | `GET /telemetry/status` | Telemetry health poll, "dropped events" indicator | **c, live seam** | Stays live. Also snapshot into `sessions.dropped_*` on the reconcile cadence (fixes the crash-loss bug in §Write reliability) |
| 20 | `get_log_queue_drops`, `get_db_write_queue_drops`, `is_log_persistence_active` | `/health` | Diagnostics | **c, live seam** | Move to `/telemetry/status`, keep live, snapshot to `sessions` |
| 21 | `ws.is_connected` and bootstrap for `/health/ready`; `/health/live` | probes | Container health check, CLI | **c, live seam** | Stays live. A probe answered from a DB row says "ok" while the process is wedged |
| 22 | WS `app_status_changed` payload (bus event, not persisted) | WS | `store.updateAppStatus`, overlaid in about 10 files | b | Becomes a post-commit invalidation signal |
| 23 | WS `execution_completed` (built from `ExecutionRecord` **after** commit, `execution_pipeline.py:280-281`) | WS | `useQueryInvalidator` trigger, filtered by app_key/listener_id/job_id | a | Keep as is |
| 24 | WS `log_hint` (emitted at `LogCaptureHandler.emit`, `logging_.py:140-166`, before the batched DB write) | WS | `use-log-data.ts` refetch, with a 5s fallback poll | a for data, b for timing | Keep as is: the hint-before-commit race is documented and bounded by `use-log-data.ts`'s `PERIODIC_RESYNC_MS` (5s) refetch. Status notifications, unlike logs, go post-commit |

**Action routes are inherently live** and out of scope for "never read memory": app and instance start/stop/reload with their registry pre-flight checks (`apps.py:112-206`), `POST /scheduler/jobs/{id}/trigger`, `PUT /logs/level`, `POST /auth/session`. In snapshot mode they should return a problem response (409 or 503).

**Existing tables** (`src/hassette/migrations_sql/001-013.sql`, `PRAGMA user_version` runner):
- `sessions`
- `listeners`
- `scheduled_jobs`
- `executions` (unified handler and job)
- `log_records`
- `blocking_events`
- `app_manifests` (identity only: no status, config or instance count)
- the `active_*` views

### Key constraints from the rules

- **`web-api.md`:**
  - `TelemetryDep` is for DB reads and `RuntimeDep` for live state.
  - A required DB read propagates `TelemetryUnavailableError` as a 503 `telemetry_unavailable` problem.
  - Only `/health/ready` and `/telemetry/status` may answer 503 with a status body.
  - Every route needs a typed `HassetteClient` method, and wire changes are `feat!:` with a client-compat ignore.
- **`core-startup.md`:**
  - The DB is ready before any registration.
  - Web serves even when HA is unreachable.
  - `get_system_status()` semantics ("starting", "ok", "degraded") come from three in-memory flags. Those flags become `sessions` columns under this proposal.
- **`tools/check_module_boundaries.py` `web-no-core`.** The web layer must not runtime-import `core`. A web layer that reads only the DB satisfies this naturally. That is what makes a Hassette-less serve mode possible.

## Feasibility analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|---|---|---|---|
| Schema: `app_instances`, `service_status`, `config_snapshots`, new columns on `sessions`, `app_manifests`, `scheduled_jobs`, `listeners` | `migrations_sql/014.sql` (one or two migrations), `core/telemetry/repository.py`, `insert_params.py` | Med | Schema is forward-only. Rollback is fatal by design (`2026-06-16-telemetry-db-rollback-safety`) |
| Status projector (new Resource): bus subscriber, per-key coalescing, awaited batch upsert, reconcile snapshot, post-commit signal | new `core/status_projector.py`, `core/core.py` wiring, `session_manager.py` | Med | New Resource must follow `mark_ready` and `depends_on` rules (`MARK_READY_HOOKS`) |
| Read routes switch to DB | `web/routes/apps.py`, `telemetry.py`, `health.py`, `bus.py`, `scheduler.py`, `config.py`, `web/utils.py`, `mappers.py`, `config_view.py`, `core/telemetry/*` queries; delete `overlay_runtime_state`, `overlay_manifest_rows`, `enrich_jobs_with_live`, most of `RuntimeQueryService` | High (breadth) | `apps.py` and `mappers.py` also carry #2555, so sequence the two |
| Wire contract | `wire/src/hassette_wire/` (`SystemStatusResponse`, WS models), `openapi.json`, client | Med | `feat!:`, compat ignore, `client_compat` CI |
| Frontend | `hooks/use-websocket.ts`, `state/store.ts`, `utils/app-data.ts`, `use-scoped-query.ts`, about 8 overlay consumers, `pages/diagnostics.tsx`, a snapshot banner. About 12-15 production files, 15-20 test files (of 116) | Med | The since-restart preset coupling to `uptime_seconds` |
| Serve-DB mode and seed tooling | `web/app.py` factory without Hassette, `scripts/seed_db.py`, `scripts/seed_scenarios/base.py`, new `scripts/serve_seed.py` plus a mise task, `tools/generate_client_compat_fixtures.py`, `tests/support/web_mocks.py`, e2e stubs | Med | e2e and compat fixtures currently depend on the stub |

### What already supports this

- **Status-like writes already avoid the droppable path.** Listener and job registration upserts, `mark_job_status`, `mark_job_removed` and manifest upserts all use awaited `DatabaseService.submit()`, which blocks with a 60s deadline and raises rather than silently drops (`database_write_queue.py`).
- **Write-then-notify already exists.** `persist_batch` awaits the commit, then `emit_completion_events` fires (`execution_pipeline.py:280-281`, docstring "Emit bus topic events for persisted execution records"). That is the template for status.
- **Notify-then-fetch already exists.** `log_hint` (spec 114, #2411), `apps_changed`, `connectivity`, and `execution_completed` → `useQueryInvalidator` are already signal-only. Only `app_status_changed` and `service_status` still patch payloads into a store.
- **Retention already protects current-state rows.** The size failsafe can only delete from `executions`, `blocking_events` and `log_records` (`retention_targets.py:76-81`). It can never evict `sessions`, `listeners`, `scheduled_jobs`, `app_manifests`, or any new status tables. Age retention only deletes rows of removed apps once nothing references them.
- **The CLI is HTTP-only.** The Standalone CLI initiative is moving it further that way.
- **Startup is fail-closed on the DB already** (`core.py:~390-415`). So "UI depends on the DB" adds no new startup failure mode.

### What works against this

- **Spec 087's explicit rejection of persisted status.** Its reasons don't hold up under coalescing:
  - "60+ writes during boot" becomes a handful of batched transactions. SQLite handles thousands of upserts per second.
  - "Staleness" is bounded by the reconcile interval and scoped by `session_id`.

  The reversal still needs to be recorded in the new spec.
- **The heartbeat is too coarse for liveness.** `database.heartbeat_interval_seconds=300` (`config/models.py:86`). Session staleness detection at 2.5× that is 12.5 minutes.
- **Config and source pages are a different kind of read.** They need class-load-time capture (`resolve_app_config_cls` refuses to import app code on the unauthenticated API), not a status projection.
- **The two service lists disagree on filtering.** `/health` lists all children, while WS `service_status` filters `IS_NOT_APP_ROLE` (#2938). The table has to pick one definition.

## Write reliability

### Is the risk real today?

It is real for appended telemetry. It does not exist for status, because no status is persisted.

The two queues are:
- **Layer A**, `DatabaseService`: 2000 slots, single writer.
  - `submit()` is awaited and raises `TimeoutError` after 60s.
  - `enqueue()` is fire-and-forget and drops the newest item when the queue is full.
- **Layer B**, `CommandExecutor`: a 1000-slot telemetry queue, batched every 5s, 100 items per drain. It retries 3 times with 1s × attempt backoff.

| Drop path | What it drops | Counted / surfaced |
|---|---|---|
| Telemetry queue full, retry exhaustion, FK fallback, shutdown flush | execution rows | `_dropped_overflow`/`_exhausted`/`_shutdown`; `/telemetry/status`, Diagnostics |
| Non-retryable error (`DataError`/`ProgrammingError`/other), no session at drain, `drain_and_persist` raising (`execution_pipeline.py:268-309`, `command_executor.py:249-260`) | execution rows | **Not counted anywhere** |
| Layer A `enqueue` full or detached | blocking events, log batches | Log batches → `db_write_queue_drops`; **blocking events uncounted** |
| Shutdown drain timeout (about 1.25s budget at the default 10s shutdown) | anything still queued | WARNING log only |
| `persist_manifests` failure (`app_lifecycle_config.py:~51-75`) | manifest upsert | WARNING only ("dashboard metadata may be stale"); #1463 |
| `mark_job_status` failure | `schedule_status` | Stale until the next transition |

Two more bugs matter here:
- **`sessions.dropped_*` is written once, in `before_shutdown`.** It is lost on a crash. `before_shutdown` also runs *before* child shutdown and `CommandExecutor.flush_queue`, so `dropped_shutdown` is structurally always captured as 0. This last point is inferred from call order and not run.
- **C2 miscounts.** A re-enqueue overflow lands in `_dropped_exhausted` (`execution_pipeline.py:375`) instead of `_dropped_overflow`.

### Options for status writes

| Option | Self-heals a lost write? | Cost | Verdict |
|---|---|---|---|
| Append-only event log only (#1446's shape); current status = latest event | No. A lost event is a wrong status forever | Every read is a "latest per key" query | Reject as the *source* of current state |
| Idempotent current-status upsert via awaited `submit()` | Only on the next transition for that key | Small | Necessary, not sufficient |
| + **Periodic reconciliation snapshot**: rewrite all current rows from the registry and children every N seconds and at bootstrap completion | **Yes**, within N | About 40-60 rows per tick, one transaction | **Recommend** |
| Priority or non-droppable lane in Layer A | Prevents lag, not loss. `submit()` already doesn't drop | Queue rework; named as a gap in `2026-09-17-sqlite-write-queue-patterns` | Defer until lag is measured; reconcile bounds it anyway |
| Write-then-broadcast | n/a, it's for ordering | Trivial | **Recommend** (mirror `emit_completion_events`) |

**Recommended design (revised after challenge): a single-writer, level-triggered `StatusProjector`.** This is the Kubernetes controller pattern: the work queue holds *keys*, not events; the reconcile function receives only a key and re-reads current state; the periodic resync re-enqueues every key into the same path; duplicate enqueues collapse ([controller-runtime `reconcile.go`](https://opensource.netapp.com/OTV/10.3/golang/sigs.k8s.io/controller-runtime@v0.19.0/pkg/reconcile/reconcile.go), [reconcile loop explained](https://www.golinuxcloud.com/kubernetes-reconcile-loop-explained/), [Chainguard: the principle of reconciliation](https://www.chainguard.dev/fr-FR/unchained/the-principle-of-reconciliation)). The first draft's event-path upserts plus a separate full reconcile was a second writer for the same fact; the challenge (Findings 1-7) traced six defects to that shape.

1. **Triggers mark keys dirty; they carry no data.** `app_state_changed`, `service_status`, block/unblock, `APP_LOAD_COMPLETED` and config reload each mark a key (`app_key[index]`, a service name) or "all" dirty. Inputs that don't emit a bus event today (block/unblock at `app_registry.py:126-134`) get a dirty-mark call.
2. **One projector task does every write.** After a short debounce (~250ms), it runs one write job through awaited `submit()`. The snapshot is read from the registry and children **inside the write job**, at execution time, never before queue admission, so a write can never carry state older than one already committed.
3. **Diff against the last committed snapshot.** Changed keys get their current-status row upserted (the computed view: `build_manifest_info` output, `ServiceInfo`), tagged with `session_id` and `updated_at`. Each changed status also appends an `app_status_events` row in the same transaction.
4. **Then broadcast a payload-free invalidation, post-commit.** `apps_changed` moves here too, so a refetch after a reload always reads projected state.
5. **Resync every 30s re-marks everything dirty** and goes through the same path. It is not a separate code path and not the heartbeat.
6. **No reconcile mid-reload.** The projector defers while a reload is in progress. "App removed" comes only from an explicit removal (manifest gone after `APP_LOAD_COMPLETED`), never from an entry missing in a registry read; Kubernetes controllers likewise read from a consistent cache and treat deletion as an explicit event.

**The heartbeat stays separate and cheap.** Kubernetes moved kubelet heartbeats out of the heavy Node status write into a tiny Lease object for exactly this reason: a liveness signal that carries a heavy write becomes fragile ([KEP-589](https://www.k8s.dev/resources/keps/589/), [Leases](https://kubernetes.io/docs/concepts/architecture/leases/)). Hassette's heartbeat stays `DatabaseService`'s single-row `last_heartbeat_at` update, moved to a 30s default; the projector's resync is an independent 30s loop. The heartbeat write timeout and failure-escalation constants (`database_service.py:37-45`, currently sized against 300s) are re-derived for the 30s interval.

Failure-mode reasoning:
- **A failed write job** (timeout, `OperationalError`) leaves its keys dirty; the next run (or at worst the next resync) rewrites them from current state. The worst case is ≤30s of wrong status, logged at WARNING.
- **A missed trigger** (listener backpressure, a projector crash and restart) is corrected by the resync, because every run reads in-process truth, not an event stream.
- **A process crash** leaves rows tagged with a dead `session_id`. The UI and orphan marking treat them as last-known (see Staleness), never as live.
- **Lifecycle latency is never coupled to the DB.** The projector runs off the bus, not inline in `AppLifecycleService`, so a slow DB delays the UI rather than app start.
- **Writing the computed view keeps one derivation** of the status priority in Python (`disabled > blocked > degraded > running > failed > stopped`). SQL is then a plain read, and seeds write the same columns directly.

**Lifecycle history (settled: ships with the projector):** `app_status_events` rows come from the diff in step 3, so history and current state are written by the same writer in the same transaction and can't disagree. The accepted cost, the same one Kubernetes accepts for level-triggered status: two transitions inside one debounce window record as one. A crash loop is still captured, since restarts take seconds. No timeline UI is committed; the table exists so history accumulates from day one.

**Not covered by the projector:** `schedule_status`, listener/job registrations and manifest persistence keep their own awaited writes (`scheduler_dispatch.py`, `repository.py`). A failed one of those does not self-heal at the next resync; "self-heals within 30s" is a claim about projected status only.

### When the DB itself is failing

- **Reads fail.** Routes already 503 with `telemetry_unavailable`, and enrichment parts go `null`. With no memory fallback, the Apps page shows an error state rather than live status. This matches Airflow and Dagster, where the UI is DB-down when the DB is down. The existing `TelemetryDegradedBanner` plus the `/telemetry/status` probe already cover the messaging.
- **Writes fail but reads work** (disk full, a wedged writer). This is the dangerous case: the UI shows confident, stale status. Mitigation: the projector records `last_reconcile_ok_at` and consecutive failures in memory. `/telemetry/status` (the live seam) exposes them as `projection_lag_seconds`, and the UI banners when the lag exceeds 2 reconcile intervals. **This is why the pipeline-health surface must stay live:** a DB-sourced "the DB is fine" signal dies with the thing it diagnoses.

## Staleness

- **Live mode (the normal case).** The web server runs inside the Hassette process. If the API answers, the process is alive, so heartbeat age adds little. Status freshness is bounded by the reconcile interval. No new UI is needed beyond the projection-lag banner above.
- **Snapshot mode** (a seeded DB, or a copied production DB served without Hassette). The server reports `mode: "snapshot"` and `as_of` (the latest session's `stopped_at`, or `last_heartbeat_at` if null) on `/health`. The UI shows a persistent banner ("Snapshot: data as of …; actions disabled") and hides or disables action buttons.
  - A session with `stopped_at IS NULL` in snapshot mode is shown as "last heartbeat at X, process state unknown", which is Airflow's "scheduler does not appear to be running" pattern.
  - Status rows from older sessions render as last-known, not live.
- **Orphan marking.** `_do_mark_orphaned_sessions` (`session_manager.py:145-169`) backfills `stopped_at = last_heartbeat_at` and rewrites only status `running` to `unknown`. There is no heartbeat-age threshold and no cross-process guard. With a 30s heartbeat, the backfilled `stopped_at` becomes accurate to 30s instead of 5 minutes. The startup reconcile overwrites the current-status tables for the new session.
- **Seeds.** Anchor at seed time, not serve time.
  - **The bug.** `ts()` (`scripts/seed_scenarios/base.py:355-360`) adds offsets to `REFERENCE_INSTANT = 2026-01-15T12:00Z` (`:23`). UI presets compute `Date.now() - window` (`frontend/src/utils/time-window.ts`), and since-restart uses `uptime_seconds`. A seed is about 9 months outside every window, so it renders empty.
  - **The fix.** Add `seed_db.py --anchor now|<iso>` that replaces `REFERENCE_INSTANT`, keeping the fixed default so `client_compat` fixtures and tests stay deterministic. Since-restart then keys on the latest `sessions.started_at`, which the seed controls.
  - **Rejected alternative.** Shifting time at serve time would touch every query.
- **Current UI on disconnect, for reference.**
  - Backend WS down: `system-health.tsx` label, the overview tab dims (`overview-tab.tsx:90-98`), and the services panel shows a "stale" badge.
  - HA down: no dedicated chrome, only Diagnostics `boot_issues`; this is an explicit non-goal of spec 018, see `tests/e2e/test_dashboard_without_ha.py`.
  - There is no "last updated at" concept anywhere.

## Real-time updates

There are 7 WS message types today. Two carry state the client keeps (`app_status_changed`, `service_status`). One carries state the client depends on (`connected.uptime_seconds`). The rest are already signals or triggers.

| Message | Today | Proposed |
|---|---|---|
| `app_status_changed` | payload patched into `appStatus`, overlaid in about 10 files | Post-commit invalidation of `manifests`, `manifest(key)`, `appGrid`. Delete the `appStatus` store, `appLiveStatus`/`instanceLiveStatus`/`instanceLiveError` |
| `service_status` | payload patched into `serviceStatus`, merged into `/health` | Post-commit invalidation of `systemStatus`. Delete the store and `mergeServices` |
| `connected` | `uptime_seconds`, `version`, `entity_count`, `app_count` | Keep `version` (the bundle-mismatch reload prompt). Since-restart reads `session.started_at` from `/health`. Drop `entity_count` |
| `execution_completed` | post-commit batch, filtered by key | Keep. Already correct ordering, and the payload is what makes the filtering cheap |
| `log_hint` | emitted before the DB write; 5s fallback poll | Unchanged (race bounded by the 5s resync) |
| `apps_changed`, `connectivity` | signals | Keep (`connectivity` becomes redundant once item 8 projects HA connection) |

**Ordering.** The projector broadcasts only after `submit()` resolves. The reader is a separate WAL connection, so a refetch triggered by the signal sees the commit. This is the same guarantee `execution_completed` already has. The existing `useQueryInvalidator` debounce (500ms trailing, 1500ms max) absorbs boot storms.

**Frontend estimate:** about 12-15 production files and 15-20 test files. Most of it is deletion. This also resolves #1895, and likely #1894 and #1609.

## Prior art

| System | Source of truth for live UI status | Can status writes be dropped? | Dead or stale detection | Push to UI |
|---|---|---|---|---|
| **Home Assistant** | **In-memory state machine.** The frontend subscribes to live state over WS. History comes from the recorder DB | Recorder writes async on a `commit_interval` (default 5s). On backlog plus low RAM it **stops recording** (an ERROR log, then removes its listener) rather than dropping selectively. The live UI is unaffected because it doesn't read the DB | n/a, single process | Live **data**. `history/stream` merges a DB query with a live event stream, skipping live events older than the subscription start |
| **Airflow** | **Metadata DB.** The webserver/API server only reads the DB. Airflow 3 makes the API server the sole DB gateway | Status transitions are DB transactions by the scheduler and workers; no lossy queue. If the DB is down, scheduling stops (inferred from the architecture; not verified this session) | Heartbeats in the DB. Zombie = running in the DB with a stale heartbeat (threshold default 300s on Composer). UI banner: "The scheduler does not appear to be running. Last heartbeat was received X ago" | Polling or refetch |
| **Prefect** | **API/DB.** State transitions go through the orchestration API | Transitions are API calls that succeed or fail; heartbeats are events | Heartbeat events plus an automation that marks runs Crashed after 90s of silence. `MarkLateRuns` is a separate service for runs that never started | Events and refetch |
| **Dagster** | **Instance storage** (run storage plus event log) | Events are written to storage (inferred synchronous; source not confirmed this session) | Each daemon writes heartbeats to storage. UI shows daemon health from heartbeat age. Run monitoring fails runs stuck in STARTING or CANCELING after timeouts | Refetch or subscriptions |
| **Temporal** | **Event history** in persistence. Mutable state is a derived cache | History is persisted before the call is acknowledged | Activity and worker timeouts | UI reads from persistence |
| **Celery Flower** | **Its own in-memory event capture** | Events missed while Flower is down are gone. State is lost on restart unless `--persistent`/`--state-db`; logical-clock issues after restarts (flower#831) | Worker heartbeat events | Live data |

**Conclusion.** Two coherent designs exist:
- **HA's:** memory is truth for live, the DB is lossy history, and the UI reads both through separate channels.
- **Airflow, Prefect, Dagster and Temporal's:** the DB is truth, written synchronously and idempotently, with liveness from heartbeat age and the UI as a pure reader.

Flower is the cautionary middle: a UI fed from captured memory loses truth on restart.

Hassette today is a muddled hybrid. It has DB truth for registrations, memory truth for status, and the frontend overlaying one on the other. The seeding goal only works under the second design.

The DB-truth systems all keep three things out of "status in the DB":
1. **Liveness is never a stored flag.** It is derived from heartbeat age.
2. **Pipeline health is measured outside the pipeline.** Metrics or logs, not the status tables.
3. **Actions talk to the live component.**

That is exactly where the line falls for hassette. Strict DB truth is reasonable for state. The probes, pipeline-health counters and actions stay live.

One honest counterpoint from HA: its live UI never shows anything staler than memory. Hassette's will show up to one reconcile interval of lag on a dropped write, and normally it will be milliseconds behind (post-commit signal). For a monitoring UI of automations that's acceptable. It would not be for a control UI where a user flips a switch and expects instant feedback, but hassette's actions go to the live process anyway.

## Options evaluated

### Option A: DB as truth for all state, with one named live seam (recommended)

**How it works.** Add the status tables and a single-writer `StatusProjector` (triggers mark keys dirty, one debounced write path that snapshots at execution time and diffs, a 30s resync through the same path, post-commit invalidation signals; the heartbeat stays a separate cheap write). Persist:
- app, instance and service status
- `next_run`/`fire_at`/`jitter`
- HA connection and bootstrap timestamps on `sessions`
- a startup config snapshot
- class-load config schemas
- counters snapshotted on the reconcile cadence

Every GET route then reads only `TelemetryQueryService`, and `RuntimeQueryService` shrinks to WS fan-out. The **live seam** is explicitly four things:
- `/health/live`
- `/health/ready`
- `/telemetry/status` (drop counters, DB health check, projection lag)
- action routes and auth

A `create_fastapi_app(snapshot_db=...)` factory mounts the read routes over a read-only connection with no Hassette. In that mode the seam answers `mode: "snapshot"` (probes report snapshot, actions return a problem response).

**Pros:**
- Deletes `overlay_runtime_state`, `enrich_jobs_with_live`, the frontend overlay stores, and `create_hassette_stub` as a dependency of seed consumers.
- Serving a seed becomes "open the file."
- The web layer stops needing `RuntimeDep` for reads, which matches `web-no-core`.
- Fixes the crash-loss and always-zero bugs in `sessions.dropped_*` as a side effect.
- Seed scenarios gain the ability to express DEGRADED, blocked and failed status (#1600, #2890).

**Cons:**
- Reverses spec 087's documented decision.
- Adds a resource, about 3 tables plus columns, and a resync cadence.
- Up to 30s of wrong status after a lost write.
- Config-schema capture at class load is a new code path.
- Breaking wire changes across `SystemStatusResponse` and the WS models.

**Effort estimate:** Large. It is an initiative of about 9 issues, most of them medium.

**Dependencies:** none new.

### Option B: do less. Persist status only, keep everything else behind a live overlay seam

**How it works.** Same projector and status tables (app, instance, service, HA connection and bootstrap), so the Apps, Overview and Diagnostics status surfaces read the DB and seeds can express status. Counters, `next_run`, `config`, gauges and drop counters stay in memory, behind one `LiveOverlay` dependency used only by enrichment parts. In snapshot mode `LiveOverlay` returns nothing, and those parts render "—" (the existing null-part semantics from spec 125).

**Pros:**
- About half the work.
- No config-schema capture.
- No per-fire `next_run` writes.
- Still unblocks seed-to-UI, #855 and #1600.
- Keeps HA-style instant counters.

**Cons:**
- The split survives, now as a named seam rather than an overlay.
- Snapshot mode shows "—" for next-run, guard counters and config, so screenshots and docs from seeds are incomplete.
- The user's stated preference (strict) isn't met.
- A later move to A redoes the enrichment paths.

**Effort estimate:** Medium-Large (about 6 issues).

## Concerns

### Technical risks

- **Projector correctness under app reload races.** The registry clears mid-read during AppHandler teardown (`runtime_query_service.py:53-59` docstring). Reconcile must tolerate this exactly as RQS does today, or it will write transient empties.
- **The reconcile write competes with log batches in the shared FIFO.** Under a log storm it lags, though it doesn't drop. Measure before building a priority lane.
- **The `IS_NOT_APP_ROLE` filter mismatch** (#2938) must be settled when `service_status` becomes a table.
- **Schema rollback is fatal** (`SchemaVersionError`), and new migrations make downgrade harder (#1462).

### Complexity risks

- New concepts: projector, reconcile cadence, snapshot mode, `as_of`, projection lag.
- Each needs tests. The reconcile-heals-a-dropped-write test is the one that proves the design.

### Maintenance risks

- **Every new piece of UI-visible runtime state now needs a column and a projector line**, not just a getter. That's the price of strict, and it's the same discipline `design-completeness.md` already applies to telemetry fields.

## Open questions

- [x] **Lifecycle history:** ship `app_status_events` with the projector, or defer? **Answer: ship with the projector (issue 3).** Written in the same transaction as each transition upsert; no timeline UI committed.
- [x] **Reconcile and heartbeat cadence:** is 30s right? **Answer: yes, 30s for both.** `database.heartbeat_interval_seconds` defaults to 30, and the projector's resync also runs every 30s. Post-challenge refinement: they are two independent loops, not one fused cadence (see Write reliability, "The heartbeat stays separate and cheap").
- [x] **Snapshot-mode entry point:** public CLI subcommand or dev-only script? **Answer: dev-only script** (`scripts/serve_seed.py` plus a mise task). Not a public surface.
- [x] **`/apps/{key}/source` in snapshot mode:** persist source text, or 404? **Answer: 404.** User code is not stored in the telemetry DB; the UI shows the source as unavailable in a snapshot.
- [x] **Unknown, resolved:** can `log_hint` fire before its log batch commits? **Yes, by design.** `LogCaptureHandler.emit()` (`logging_.py`) schedules the hint immediately, before persistence. It is a documented race that `use-log-data.ts` bounds with `PERIODIC_RESYNC_MS` (5s) periodic refetch. Logs keep hint-then-fetch; only status notifications need the post-commit ordering this design adds.
- [ ] **Unknown:** whether Dagster's run status is written synchronously from the event log. Searches did not surface `handle_run_event`. This doesn't change the conclusion.

## Recommendation

**Option A**, with the reversal of spec 087's Alternative B recorded in the new spec. The evidence for it:
- Every DB-as-truth system surveyed writes status the way the projector would (Supported: Airflow, Prefect, Dagster and Temporal docs above).
- The write path hassette needs (awaited, non-dropping `submit()`) already carries every status-like write it persists today (Direct: `database_write_queue.py`, `bus_service.py:212`, `scheduler_dispatch.py:144`).
- The frontend is already mostly notify-then-fetch (Direct: `use-websocket.ts:106-191`).

The live seam is not a compromise of "strict." It is the same three exclusions every surveyed system makes.

If the initiative needs to be smaller to fit the roadmap, Option B is a clean prefix of A: issues 1-5 and 8-9 below. Do it first and promote the rest later.

### Proposed initiative

**Milestone: "DB as source of truth"**

**Done when:** `mise run seed:serve --scenario degraded` serves a seeded DB to the Vite UI and the CLI with no Hassette instance and no runtime stubs. Under the default time preset:
- the Apps grid, app detail, Handlers and Diagnostics pages render the scenario's apps, instance statuses (including DEGRADED), handlers, jobs (with next run) and services;
- a snapshot banner states the data's `as_of`;
- no GET route outside `/health/live`, `/health/ready` and `/telemetry/status` reads process memory;
- `tools/generate_client_compat_fixtures.py` no longer uses `create_hassette_stub` for read routes; its action and probe shapes come from a typed fake of the live seam, since snapshot mode answers actions with a problem response and would otherwise lose the success shapes the compat check pins.

**Ordered issues** (each independently landable, each with tests):

1. **Seed timestamp anchor.** `seed_db.py --anchor now|<iso>`; `ts()` reads the anchor; default unchanged. Files: `scripts/seed_db.py`, `scripts/seed_scenarios/base.py`, `tests/integration/test_seed_db.py`. *Done when a seed built with `--anchor now` shows rows under the 1h/24h presets against a live-pointed UI.*
2. **Session heartbeat and drop-counter snapshots.** 30s heartbeat, with its write timeout and failure-escalation constants re-derived for that interval. Snapshot `dropped_*`, `dropped_filtered`, log and DB-write drops and gauges into `sessions` on each heartbeat. Route every drop through one counting helper with one taxonomy, reporting intentional sampling separately from real loss. Fix the C2 miscount and count the uncounted drop paths (C6-C8, blocking-event enqueue). Fix `dropped_shutdown` (confirmed always 0: `finalize_session` runs in `before_shutdown` at `core.py:645-677`, before `flush_queue` increments it), which needs a final counter write after child services flush and before the DB stops accepting writes, not just a reorder. Files: `config/models.py`, `database_service.py`, `session_manager.py`, `execution_pipeline.py`, `command_executor.py`, a migration. *Done when a SIGKILLed session's row carries drop counts no more than one heartbeat old.*
3. **Status projection tables and `StatusProjector`.** Migration for `app_instances`, `service_status`, `app_status_events` (append-only, produced by the projector's diff in the same transaction as the current-row upserts), derived status columns (placement open: challenge Finding 8 argues for session-keyed tables instead of `app_manifests`, decided in the spec), and `sessions.ha_connected*`/`bootstrap_released_at`/`only_apps_json`. Single-writer projector per Write reliability: dirty-key triggers, one debounced write job that snapshots at execution time and diffs, 30s resync through the same path, a run at bootstrap, deferral during reload. Retention: the new tables join the retention rules, `app_status_events` gets an age limit, and session pruning never blocks on rows that reference a session. **This is #1446, rewritten.** Files: `migrations_sql/014.sql`, new `core/status_projector.py`, `core/core.py`, `core/telemetry/repository.py`, `core/app_registry.py`. *Done when a test that fails a projector write sees the row corrected by the next run, a resync started mid-reload writes no removals, and a crashed session's rows are never reported as current.*
4. **Apps reads from the DB.** `/apps`, `/apps/{key}`, app-grid, `boot_issues` and `app_count` read the projection. Delete `overlay_runtime_state`, `overlay_manifest_rows` and `get_registry_only_apps`. Files: `web/routes/apps.py`, `web/routes/telemetry.py`, `web/mappers.py`, `core/runtime_query_service.py`, `core/telemetry/*`. Sequence after #2555 or absorb it. *Done when no apps or telemetry GET route reads `app_handler.registry`.*
5. **System status from the DB, with the live seam carved out.** `/health` services, status, uptime and HA connection come from `sessions` and `service_status`. Drop counters, DB health and `projection_lag_seconds` move to the live `/telemetry/status`. `/health/live` and `/health/ready` stay live. Drop `entity_count`. Files: `routes/health.py`, `routes/telemetry.py`, `wire/` `SystemStatusResponse`, `runtime_query_service.py`. *Done when `/health` serves fully from a read-only DB connection.*
6. **Scheduler and bus live fields persisted.** `next_run`, `fire_at` and `jitter` are added to the existing awaited `persist_schedule_status` UPDATE that already runs after every job transition, including each recurring fire (`scheduler_dispatch.py:92-93, 131-144`, `repository.py:241-260`), so no extra writes and no dependency on the projector (this issue no longer needs issue 3). Listener and job guard counters are snapshotted on the heartbeat. Delete `enrich_jobs_with_live` and the `live_execution_counts` read path. Files: `scheduler_service.py`, `scheduler_dispatch.py`, `bus_service.py`, `web/utils.py`, `routes/scheduler.py`, `routes/bus.py`, `routes/telemetry.py`, a migration. *Done when the jobs and listeners routes read no scheduler or bus state.*
7. **Config snapshots.** Masked `HassetteConfig` plus schema at startup. Per-app masked config plus schema captured at class load. `full_path` on `app_manifests`. Files: `routes/config.py`, `web/config_view.py`, `app_lifecycle_config.py`, a migration. *Done when `/config` and `/apps/{key}/config` serve from a read-only DB.*
8. **WS invalidations and frontend overlay removal.** The projector emits payload-free `app_status_changed`/`service_status` after commit. Since-restart keys on `session.started_at`. Delete the `appStatus`/`serviceStatus` stores, the `app-data.ts` overlay helpers and `mergeServices`. Add the projection-lag banner. Files: `wire/src/hassette_wire/ws.py`, `frontend/src/hooks/use-websocket.ts`, `state/store.ts`, `utils/app-data.ts`, `hooks/use-scoped-query.ts`, about 8 consumers, plus screenshots. **Supersedes #1895, and likely #1894 and #1609.** *Done when the frontend holds no server state outside TanStack Query except the connection status and `version`.*
9. **Snapshot serve mode and seed-to-UI.** `create_fastapi_app` snapshot factory over a read-only connection: `/health` reports `mode: "snapshot"` and `as_of`, actions return a problem response, and `/apps/{key}/source` returns 404 (the UI shows source as unavailable). Add `scripts/serve_seed.py` plus a `mise run seed:serve` task that seeds with `--anchor now`, starts uvicorn and prints `VITE_PROXY_TARGET=...`. Add the UI snapshot banner. Switch `generate_client_compat_fixtures.build_app()` and, where possible, the e2e stubs to the snapshot factory. Files: `web/app.py`, `scripts/`, `mise.toml`, `frontend/vite.config.ts` (docs only), `tools/generate_client_compat_fixtures.py`, `tests/support/web_mocks.py`. *Done when the milestone Done-when holds.*

Issues 1 and 2 are independent and can land any time. Issue 6 needs only a migration, not the projector. Issue 3 gates 4, 5, 7 and 8. Issue 9 needs 4-8 for the full Done-when, but a status-only version works after 4-5, which is the Option B prefix.

### Existing issues

| Issue | Action | Why |
|---|---|---|
| #1446 Persist app instance lifecycle transitions | **Rewrite into issue 3** | Stale body: it references `app_classes`/`app_instances` tables that never shipped (only `app_manifests`, migration 011). It is also event-log-as-truth, which this brief rejects in favor of current rows plus reconcile, with an `app_status_events` history table alongside |
| #760 Frontend state QA tooling | **Rewrite:** fold Phase 3 (seed scenarios in dev) into issue 9; keep Phases 1-2 (MSW scenarios, dev panel) as a separate, smaller issue | Phase 3 *is* seed-to-UI. MSW covers transient states (reconnecting, loading) that a seed can't |
| #1600 multi-instance DEGRADED seed | **Keep, re-scope:** depends on issue 3; drop part 2 (the live failing example app) | Part 2 is the workaround that persisted status makes unnecessary |
| #2890 mixed-instance seed scenario | **Keep;** add "write `app_instances` rows" to its acceptance criteria; blocked by issue 3 | Ready otherwise |
| #855 CLI docs via Cog against a seeded instance | **Keep outside the milestone,** blocked by issue 9 (and benefits from Standalone CLI `--url`/`--target`) | The Done-when doesn't need it, so per the roadmap rule it stays out |
| #2806 Live issues registry | **Keep separate;** note in both that issues should be projected like status (a current `issues` table written by the projector) if it lands after issue 3 | Its open question "do issues survive a restart" is answered by this design |
| #1463 Manifest-persist failure signal | **Keep, blocked by #2806;** lower priority | Reconcile self-heals manifest drift, so the signal shrinks to "projection lag", which issue 5 already surfaces |
| #1601 Status vocabulary single source | **Keep separate** | Frontend vocabulary maps, unrelated to DB truth despite the title |
| #2555 apps routes/mappers cleanup | **Land before issue 4, or close as absorbed** if issue 4 rewrites those mappers | Same files |
| #1895 / #1894 / #1609 | **Close when issue 8 lands** | Their subject (the WS overlay and its cache invalidation) is deleted |

**Roadmap note.** The "Now" slot is HA add-on v0.1. Per `design/roadmap.md`, this goes in Later, or Next once the milestone, Done-when and issues exist. Issues 1 and 2 are bucket-sized and can be pulled between PRs.

### Suggested next steps

1. Write the spec via `/mine-sketch`. Cadence, history events, the snapshot entry point, snapshot source handling and the projector's single-writer model are settled (see Open questions and Write reliability). The spec must still record the explicit reversal of spec 087's Alternative B and decide the remaining challenge findings (see Challenge outcome).
2. Land issue 1 (seed anchor) now. It is independent and immediately useful for screenshots and demos against a live stack.
3. Prototype the reconcile-heals-a-dropped-write test before building the full projector. It is the load-bearing claim of the design.

## Challenge outcome

A three-critic challenge (systems architect, data integrity, structural minimalist) produced 21 findings, 9 HIGH, none likely invalid. Full findings, with evidence, are in `challenge-findings.md` next to this brief; the decisions they force are summarized here.

**Resolved in this brief:**
- Findings 1-7 (the projector's dual write path, stale-snapshot overwrites, heartbeat fusion, incomplete triggers and pre-commit `apps_changed`, coalescing vs history, mid-reload empty reads): adopted the single-writer level-triggered projector and a separate heartbeat (Write reliability).
- Finding 9 (shutdown order loses `dropped_shutdown` and the final status): folded into issue 2. The final projected status at clean shutdown still needs a spec decision (see below).
- Finding 11 (self-heal overclaim): scoped in Write reliability, "Not covered by the projector".
- Finding 12 (`next_run` via the projector): issue 6 now extends `persist_schedule_status` instead.
- Findings 15, 17, 18 (compat fixture keeps a typed live-seam fake; retention for the new tables; one drop taxonomy): applied to the Done-when and issues 2-3.

**Open for the spec (`/mine-sketch`):**
- **Finding 8 (HIGH): placement of runtime state.** Status columns on session-less `app_manifests` read as current after a crash or app removal, and share a row with `persist_manifest`. The alternative is session-keyed runtime tables, with live mode telling the read side the current session instead of the reader inferring it.
- **Finding 9 (HIGH, remainder): final status at clean shutdown.** Rows probably stay `RUNNING` after a clean stop unless a final projector run happens after apps stop and before the DB closes.
- **Finding 10 (HIGH): projection lag must be computed per request.** `/telemetry/status` reports zeros for a missing counter source (`routes/telemetry.py:101-103`), so a dead projector would look healthy.
- **Finding 13: system health placement.** Persist services, HA connection and bootstrap with one derivation, or keep them on the live seam with the probes.
- **Finding 14: the live seam needs a declared interface.** One app factory taking a context object (config, telemetry query service, optional live seam) instead of a second snapshot factory.
- **Finding 16: config snapshots (issue 7)** are the same kind of read as source; consider the same "unavailable in snapshot" treatment instead of persisting masked config.
- **Finding 19 (TENSION): change cost per field** (migration, projector line, wire change, seed change); a JSON gauges column per session is a possible hedge.
- **Finding 20: reconcile payload size** on the single writer (audience assumption: larger installs than today's).
- **Finding 21 (TENSION): the A-vs-B framing** may hide a smaller design (~7 issues) that still meets the strict preference.

## Sources

- [controller-runtime `reconcile.go` (request carries only a key)](https://opensource.netapp.com/OTV/10.3/golang/sigs.k8s.io/controller-runtime@v0.19.0/pkg/reconcile/reconcile.go)
- [The Kubernetes reconcile loop explained (work queue holds keys, not events)](https://www.golinuxcloud.com/kubernetes-reconcile-loop-explained/)
- [Chainguard: the principle of reconciliation (resync as a trigger into the same path)](https://www.chainguard.dev/fr-FR/unchained/the-principle-of-reconciliation)
- [flynn reconcile package (key dedup semantics modeled on client-go)](https://pkg.go.dev/github.com/ionalpha/flynn@v0.1.3-rc.1/reconcile)
- [KEP-589: Efficient Node Heartbeat (heartbeat split from status)](https://www.k8s.dev/resources/keps/589/)
- [Kubernetes Leases](https://kubernetes.io/docs/concepts/architecture/leases/)

- [Home Assistant Recorder integration docs (`commit_interval`)](https://www.home-assistant.io/integrations/recorder)
- [HA core recorder source (`core.py`: backlog check, stop recording, commit interval)](https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/recorder/core.py)
- [HA history `websocket_api.py` (`HistoryLiveStream`, DB query plus live merge)](https://git.sudo.is/home-assistant/core/src/branch/dev/homeassistant/components/history/websocket_api.py)
- [HA community: recorder backlog queue reached maximum](https://community.home-assistant.io/t/recorder-backlog-queue/603328)
- [Airflow 3 upgrade guide: API server as sole DB gateway](https://airflow.apache.org/docs/apache-airflow/3.1.0/installation/upgrading_to_airflow3.html)
- [Astronomer forum: "Scheduler does not appear to be running. Last heartbeat…"](https://forum.astronomer.io/t/scheduler-does-not-appear-to-be-running-last-heartbeat/2829)
- [Qubole docs: Airflow zombie detection via heartbeats](https://docs.qubole.com/en/latest/user-guide/data-engineering/airflow/interoperability.html)
- [Prefect: detect zombie flows (heartbeats plus automation)](https://docs.prefect.io/v3/advanced/detect-zombie-flows)
- [Prefect: MarkLateRuns service](https://docs.prefect.io/api-ref/orion/services/late_runs/)
- [Dagster daemon (heartbeats to instance storage)](https://docs.dagster.io/deployment/dagster-daemon)
- [Dagster run monitoring](https://docs.dagster.io/deployment/run-monitoring)
- [Temporal architecture (history as source of truth)](https://docs.temporal.io/encyclopedia/architecture/temporal-architecture)
- [Temporal ARCHITECTURE.md (persist before ack)](https://github.com/temporalio/temporal/blob/915883fcb2e0f74382dabc897963e15283b80ce1/ARCHITECTURE.md)
- [Flower events persistence (third-party mirror)](https://tessl.io/registry/tessl/pypi-flower/2.0.0/files/docs/events.md)
- [Flower PR #831: event state after restarts](https://github-redirect.dependabot.com/mher/flower/pull/831)
