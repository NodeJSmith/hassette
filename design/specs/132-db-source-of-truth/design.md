# Design: DB as the source of truth for the web UI and CLI

**Date:** 2026-10-16
**Status:** ratified
**Mode:** sketch
**Issues:** #1446 (rewritten as D19 issue 5); every other related issue is listed in D19

## Summary

The web UI and CLI read some state from the SQLite telemetry DB and some from in-memory runtime objects (`AppRegistry` via `hassette.app_handler.registry`, `RuntimeQueryService.overlay_manifest_rows`, `bus_service.live_execution_counts`, the scheduler's live job registry, `websocket_service`, `state_proxy`), and the frontend overlays WS-pushed status payloads onto REST data. This change makes the DB the source of truth for every piece of automation state the UI and CLI show, written by a single-writer `StatusProjector` that projects process memory into the DB. Only a small named **live seam** still reads the process; D10 enumerates what it carries. With that in place, a DB file can be served with no Hassette instance: a dev-only script seeds a scenario (`scripts/seed_db.py`, `scripts/seed_scenarios/`) anchored to now and serves it to the Vite UI, which is the motivating use case, and the client-compat fixture generator (`tools/generate_client_compat_fixtures.py`) stops stubbing Hassette for read routes.

This reverses spec 087's Alternative B (`design/specs/087-db-manifest-union/design.md:329`), which rejected persisting status because of "60+ writes during normal boot" or staleness. Both objections are answered by D1: writes are debounced and diffed, and staleness is bounded by the resync and made visible (D8).

Research and prior art: `design/research/2026-10-16-db-source-of-truth/research.md` (inventory of every in-memory read, write-reliability analysis, prior art from Home Assistant, Airflow, Prefect, Dagster, Temporal, Kubernetes) and its challenge findings in `challenge-findings.md` alongside.

In scope: the projector and its tables (D1, D2, D6, D7, D25); switching every automation-state GET route and WS message to the DB (D9, D13); the heartbeat and write-queue fixes (D3, D21), projector retry pacing (D22) and sizing (D18); persisted schedule timing (D17); diagnostics through #2806 (D12); the counter registry with its breaking wire change (D24) and the `entity_count` removal (D14); the live seam (D10); freshness and DB-unavailable signals (D8, D23); snapshot serve mode with the seed timestamp anchor (D4, D5, D15, D16); seed scenarios writing runtime state; frontend overlay removal; and the #2695 ordering (D20). The CLI reads only the HTTP API (research.md, "Current state"), so its only work is rendering the changed `/health` and `/telemetry/status` models, including `CliFormat` handling for D24's `counters` list.

Out of scope: lifecycle-history UI (D2 persists history only); MSW browser scenarios and a frontend dev panel (#760 Phases 1-2, to be filed separately); CLI docs via Cog (#855, kept outside the milestone and unblocked by this change); a priority lane in the write queue (D8).

Delivery and the disposition of every related issue (pulled in, closed, or linked) are in D19.

## Decisions

### D1: How does the projector write current state?

**Deciding factor:** one writer per fact, so a dropped or reordered write can't leave the DB disagreeing with itself.

| | A: single writer, level-triggered (Kubernetes controller pattern) | B: event-path upserts plus a separate periodic full reconcile |
|---|---|---|
| Writers of current state | One | Two |
| Stale snapshot overwriting a newer write | Impossible: snapshot is read inside the write job | Possible: a reconcile built before queue admission can clobber a newer transition (`database_write_queue.py:199-258`) |
| Inputs with no bus event (block/unblock, reload) | Covered by dirty-mark calls | Silently missed (`app_registry.py:126-134`) |
| History consistency | History rows come from the same diff | History from events, current state from both: can disagree |
| Mid-reload empty registry | Projector defers during reload | Reconcile can write removals |
| Prior art | Kubernetes controllers: queue of keys, reconcile re-reads state, resync uses the same path | None of the surveyed systems |

**Recommendation:** A. Behavior the build must pin:
1. Triggers (`app_state_changed`, `service_status`, block/unblock, `APP_LOAD_COMPLETED`, config reload) only mark a key (`app_key[index]`, a service name) or "all" dirty. Inputs without a bus event get an explicit dirty-mark call.
2. One projector task performs every write. After a debounce of about 250ms it runs one write job through the awaited `submit()` path, and reads the snapshot from the registry and children inside that job, at execution time.
3. The job diffs against the last committed snapshot and upserts changed rows (the computed view: `build_manifest_info` output, `ServiceInfo`), appending history rows for changed statuses (D2) in the same transaction. The baseline is advanced by the write job itself, immediately after its commit, never by the projector task from the result of its await. Jobs serialize on the single writer, so the next job always diffs against what actually committed, and an attempt that timed out (D8.7) but committed needs no reconciliation and appends no duplicate history.
4. After the commit it broadcasts the status messages (payload-free invalidations per D13 from D19 issue 8; today's message shapes until then). The `apps_changed` broadcast moves here, so a refetch after a reload reads projected state.
5. The projector runs once at bootstrap and on a resync (`database.projector_resync_interval_seconds`, whose default D3 sets) that marks everything dirty and goes through the same path.
6. While a reload is in progress the projector defers. "App removed" comes only from an explicit removal (manifest gone after `APP_LOAD_COMPLETED`), never from an entry missing in a registry read. The same rule removes an instance: after `APP_LOAD_COMPLETED`, rows of the current session whose `instance_index` is beyond the app's configured instance count are deleted.
7. A failed write job leaves its keys dirty; a retry (paced by D22), or at latest the next resync, rewrites them.
8. The projector runs on its own task, never inline in bus handlers or `AppLifecycleService`, so a slow DB delays the UI, not app start.

**Pick B instead if** never: it recreates the in-memory/DB split inside the projector.
**Reversibility:** hard (the projector's shape is what every route and the seed format build on)
**Ratified:** Chose the single-writer level-triggered projector over event upserts plus reconcile, to have one writer per fact, no stale overwrites, and a baseline that always matches what committed, accepting that transitions inside one debounce window collapse. (Re-ratified after the ledger challenge added the job-owned baseline, Finding 8.)

### D2: Does lifecycle history ship with the projector?

**Deciding factor:** history that starts accumulating now costs almost nothing in the same transaction; history not recorded is gone.

**Recommendation:** ship an append-only `app_status_events` table written by D1's diff, one row per observed status change, in the same transaction as the current-row upserts. The resync never backfills events. Two changes inside one debounce window record as one. No timeline UI is committed.
**Pick deferring instead if** the table had a real write or retention cost; writes are one row per observed change (D18) and retention ages it out (D25).
**Reversibility:** easy
**Ratified:** Chose shipping `app_status_events` with the projector over deferring it, to start accumulating history now, accepting a table with no UI yet. (Ratified in conversation.)

### D3: What cadence do the heartbeat and the resync use, and are they one loop?

**Deciding factor:** liveness and self-heal bounds of about 30s without making the liveness signal carry a heavy write.

| | A: 30s heartbeat and 30s resync as independent loops; a strike counts only without writer progress | A1: independent loops; count-based strikes with re-derived constants | A2: independent loops; strikes measured in wall-clock time | B: one fused 30s loop |
|---|---|---|---|---|
| Heartbeat fragility | Heartbeat stays a one-row `last_heartbeat_at` update | Same | Same | Heartbeat carries the projection write; three failures already take `DatabaseService` down (`database_service.py:278-322`) |
| False restarts while retention or the size failsafe holds the writer | None: each batch commit counts as progress | Likely on large DBs: three strikes at 30s tolerate about 90s of occupancy, and a retention pass is one job looping up to `retention_max_batches_per_target` batches per target (`database_retention.py:119-160`) | Reduced to today's ~15 minutes of tolerance | Same as A1 |
| Detects a wedged worker | In about three intervals | Fast | After ~15 minutes | Fast |
| New state | A write-progress counter | None | Timestamp of first failure | None |
| Prior art | Kubernetes KEP-589 split the heartbeat (Lease) from status | Same | Same | Pre-KEP-589 shape |

**Recommendation:** A. `database.heartbeat_interval_seconds` defaults to 30 (from 300, `config/models.py:86`), and its write timeout (`database_service.py:37-45`, sized for 300s) is re-derived to stay under the 30s interval. The write queue keeps a monotonic write-progress counter, bumped by the worker on each job that returned without raising and by the batched maintenance loops (retention, size failsafe) after each successful batch commit. A job that raised is not progress, so a responsive worker whose every write fails (a full disk, a broken connection) still accumulates strikes. A failed heartbeat counts as a strike toward `max_consecutive_heartbeat_failures` only when that counter has not moved since the previous heartbeat attempt; a failed heartbeat with progress resets nothing and adds no strike. A test pins that a long batched retention pass outlasting three heartbeat timeouts does not restart `DatabaseService`, and that a worker making no progress still does. The projector's resync (D1.5) is its own loop.
**Pick A2 instead if** the worker and maintenance loops should stay untouched and slower wedge detection is acceptable. **Pick A1 instead if** retention passes are reliably short at real deployment sizes. **Pick B instead if** never.
**Reversibility:** easy
**Ratified:** Chose a 30s heartbeat and a 30s resync as independent loops, with a strike counted only when the writer made no progress, over count-based or wall-clock strikes or one fused loop, to keep liveness cheap, bound self-heal at about 30s, and never restart the DB service for legitimate occupancy, accepting two timers and a write-progress counter in the worker and maintenance loops. (Strike rule added by the ledger challenge, Finding 15.)

### D4: How is snapshot serve mode launched?

**Deciding factor:** keep it out of the public CLI surface.

**Recommendation:** a dev-only script, `scripts/serve_seed.py`, plus a `mise run seed:serve` task. Nothing in the docs or code suggests making it public.
**Pick a public `hassette serve-db` command instead if** a real need comes up on its own; this ledger doesn't anticipate one.
**Reversibility:** easy
**Ratified:** Chose a dev-only script over a public CLI command, to keep snapshot mode out of the public surface, accepting that users can't inspect a copied DB without the repo. (Ratified in conversation.)

### D5: What does `/apps/{key}/source` do in snapshot mode?

**Deciding factor:** user code stays out of the telemetry DB.

**Recommendation:** returns 404, and the UI shows source as unavailable in a snapshot. Live mode keeps reading the file from disk through the live seam (D10).
**Pick persisting source text instead if** snapshots had to be complete for source; they don't.
**Reversibility:** easy
**Ratified:** Chose a 404 in snapshot mode over persisting source text, to keep user code out of the telemetry DB, accepting an unavailable Code tab in snapshots. (Ratified in conversation.)

### D6: Where does projected runtime state live?

**Deciding factor:** "not in the current session" means stopped or removed by construction, not by a convention every reader must remember.

| | A: session-scoped runtime tables; live mode is told the session | B: status columns on the identity tables, plus `seen_at` or replace semantics |
|---|---|---|
| App removed from config | Absent from the current session's rows by construction | Needs a delete rule or a `seen_at` filter in every read; otherwise "running" persists forever |
| Instance count drops (3 to 2) | The old index has no row in the current session | Stale row remains unless deleted |
| After restart or crash | Old session's rows never join as current | Previous session's status sits on identity rows until overwritten |
| Identity tables (`app_manifests`, `listeners`, `scheduled_jobs`) | Unchanged; spec 087's identity model intact | Gain mutable status columns and a second writer |
| Read complexity | Join on the current session | `seen_at`/session filter in every read |
| Seed authoring | Write runtime rows for the seed's session | Write status onto identity rows |
| Per-process counters | Attributed to their session | Reset to 0 at restart with no attribution |

**Recommendation:** A. Runtime state goes in tables keyed by `session_id` (for example `app_runtime(session_id, app_key, …)`, `app_instances(session_id, app_key, instance_index, …)`, and per-session counter tables for listeners and jobs). `app_manifests`, `listeners` and `scheduled_jobs` stay identity-only, with the exception of the `scheduled_jobs` timing columns in D17. In live mode the read side is told the current `session_id` by the process; only snapshot mode falls back to "latest session" (defined in D8, which also defines how rows of non-current sessions read). Between session creation and the projector's first run, reads return the manifest spine with status `unknown`, never the previous session's status.
**Pick B instead if** per-session duplication of rows proved too costly for retention or seed authoring, and a `seen_at` filter in every read were acceptable.
**Reversibility:** hard (schema and every read query)
**Ratified:** Chose session-scoped runtime tables over status columns on identity tables, to make staleness and removal structural, accepting per-session row duplication and a join in reads.

### D7: How does a cleanly stopping session record its final state?

**Deciding factor:** a cleanly stopped session's final rows say what actually happened, and a failure to write them is visible.

Context: shutdown runs dependents first, dependencies last (`core.py:503-505`); `before_shutdown` removes every bus listener before children stop (`core.py:663-665`), so shutdown transitions mark nothing dirty; the final wave's budget is about `CHILDREN_FLOOR_SECONDS` (`resources/shutdown_budget.py`); `_do_finalize_session` catches and logs every exception (`session_manager.py:282-324`).

| | A: projector is a `Resource` child ordered by `depends_on`; final run is mark-all within its wave; failure recorded outside the DB | A1: final write via a new hook between child shutdown and DB detach | B: `DatabaseService.on_shutdown` calls into the projector before detaching | C: no final write; reads derive "stopped" from the session row |
|---|---|---|---|---|
| Final status correct | Yes (stored) | Yes (stored) | Yes (stored) | Rendered as "stopped, last known" by a read rule |
| `dropped_shutdown` captured | Yes (runs after the executor's flush) | Yes | Yes | Never; it is always 0 today because `finalize_session` runs in `before_shutdown` (`core.py:645-677`), before `flush_queue` increments it |
| Ordering mechanism | Existing waves, with one edge that exists for shutdown order | A new hook | Upward call from the DB service (dependency inversion) | None |
| Dirty set | Explicit mark-all | Unspecified | Unspecified | n/a |
| Failure observable after exit | Yes: stderr plus a marker the next session surfaces | No (logs through a detaching queue) | No | n/a |

**Recommendation:** A.
1. The projector is a `Resource` child whose `depends_on` is `[DatabaseService, BusService]` (it subscribes to the D1.1 triggers, like `RuntimeQueryService`). `CommandExecutor` adds the projector to its `depends_on`, so on shutdown the executor stops and flushes first, then the projector's wave runs, then `BusService` and `DatabaseService`. The edge also makes the executor wait for the projector's readiness at startup; `BusService` does not list `CommandExecutor` in its `depends_on`, so no cycle forms (startup validation rejects one). A comment on the edge states it exists for shutdown order.
2. The projector's `on_shutdown` runs the final run as an unconditional mark-all, not from dirty marks, and ignores D1.6's reload deferral. It writes each app's terminal status from the registry as `AppHandler` left it (`AppHandler` stops in an earlier wave); an app missing from the registry at that point keeps its last projected row, since D1.6 forbids inferring removal. The same transaction writes the final counters (D24), including the shutdown-drop counter from the executor's flush, and session finalization (`stopped_at`, and `finalized_at`, which only this final run writes), which moves out of `Hassette.before_shutdown`.
3. The final run takes its wave's budget and nothing more. If it cannot start or commit within it, it is abandoned; graceful shutdown never waits past the budget for it.
4. A failed or abandoned final write does not swallow: it writes one line to stderr and a marker file in the data directory. The next session's projector reads the marker in `on_initialize`, logs it at WARNING, and deletes it (D19 issue 5); raising it as an issue is #2806's (D12). The session it describes reads as a crash (D8.5), which is accurate.
5. Graceful shutdown with a healthy DB leaves the shutdown-drop counter equal to the records actually dropped.

**Pick A1 instead if** the wave mechanism can't place the projector between the executor and the DB. **Pick B instead if** a shutdown-ordering `depends_on` edge on `CommandExecutor` is too surprising for its readers. **Pick C instead if** never: `dropped_shutdown` stays 0.
**Reversibility:** easy
**Ratified:** Chose a `depends_on`-ordered projector child whose final mark-all run follows the executor's flush, within its wave's budget, with failure recorded outside the DB, over a new shutdown hook, a call from `DatabaseService`, or read-time derivation, to place the final write with the existing wave mechanism and make its failure visible after exit, accepting a shutdown-ordering `depends_on` edge on `CommandExecutor` and a marker file. (Revised by the ledger challenge, Finding 10.)

### D8: How does the UI learn that the projector is stuck or the write path is failing?

**Deciding factor:** a stuck or missing projector produces a visible degraded signal within a bounded time, so the UI never shows confident stale status.

| | A: persisted `projected_at`, applied at the session join; `/health` `status` downgraded in-band | A0: in-memory request-time lag on `/telemetry/status` only (first ratified version) | A2: persisted `projected_at`, `status` left as stored | B: reserved write-queue lane for status writes |
|---|---|---|---|---|
| Detects a wedged or dead projector | Yes | Yes, web UI only | Yes, for consumers that read the new field | No |
| hass-hassette, `hassette status`, released clients see staleness | Yes: they already parse `status` | No | No: released clients ignore unknown fields | No |
| Crashed session's rows | "Last known as of `projected_at`" | Read as current | "Last known as of `projected_at`" | Read as current |
| Snapshot `as_of` | `projected_at` | Heartbeat (written independently of the projector) | `projected_at` | Heartbeat |
| `status` as a pure stored value (D9) | One read-time rule on top | Yes | Yes | Yes |
| False alarms | A slow but working write path can show `degraded` temporarily | None | None | None |
| New machinery | A persisted timestamp, a read rule, a timeout | A timestamp and a timeout | A persisted timestamp and a timeout | A second queue discipline, need unmeasured |

**Recommendation:** A.
1. The projector writes `sessions.projected_at` in the same transaction as every successful run, including no-op runs, so an idle healthy system doesn't read as stale.
2. Freshness is applied in one place: the shared query that joins runtime rows to their session (D6). That query also defines "latest session" for snapshot mode: highest `started_at`, ties broken by id.
3. Live mode: lag is now minus `projected_at`, reported on `/telemetry/status` (field per D24.4), computed by its health query from `sessions.projected_at` (`None` before the first run) and alongside a defaulted `projected_at` field on `/health`. When lag exceeds two resync intervals, `/health` reports `status: degraded` in the response body with HTTP 200 (never 503, so probes and hass-hassette don't flap over a display lag), and the UI shows a banner.
4. A session that has never projected reports degraded once a startup grace period of two resync intervals has passed. Counters are read per D24, which deletes `/telemetry/status`'s zero fallback.
5. Rows of a non-current session read as that session's final state only when `sessions.finalized_at` is set (written by D7's final run in the same transaction as the final rows). Otherwise (a crash, an abandoned final write, or a session whose `stopped_at` was backfilled at the next startup by `SessionManager._do_mark_orphaned_sessions`) they read as "last known as of `projected_at`", never as current. `stopped_at` and `status` can't make this distinction: the orphan backfill sets `stopped_at`, and `failure` also covers a cleanly finalized session that recorded a framework-service crash.
6. Snapshot mode applies the same rule per D15.
7. Each projector write attempt has its own timeout of half the resync interval. Documentation states the real bound ("within one resync interval when the write path is healthy"), not an unconditional 30s.

**Pick A2 instead if** `status` must stay a pure stored derivation and only updated consumers need to see staleness. **Pick B instead if** measured lag under realistic log storms routinely exceeds the banner threshold even with the per-attempt timeout.
**Reversibility:** easy
**Ratified:** Chose a persisted `projected_at` applied at the session join, with an in-band `/health` `status` downgrade, over the in-memory live-seam-only lag, a non-downgrading variant, or a reserved lane, so every consumer, including released clients and snapshots, is told when data is stale, accepting one read-time rule on top of stored status and possible temporary `degraded` during long writer jobs. (Revised from the first ratification after the ledger challenge, Finding 1.)

### D9: Where do system health facts live (framework service status, HA connection, bootstrap state, `/health` status)?

**Deciding factor:** one derivation with no lossy inputs, at a cost proportional to what snapshot mode actually needs.

| | A: persist, with status computed once in the process | B: keep on the live seam | C: persist inputs, derive status at read time |
|---|---|---|---|
| Seeded Diagnostics shows services and status | Yes | No ("unavailable" in snapshot mode) | Yes |
| Derivations | One (in process, written as columns) | One (live) | Two (Python for apps, SQL for health) |
| `has_ever_connected` | Written column | n/a | Lost after restart (inferred from a timestamp) |
| New schema | `service_status` per session plus written status columns on `sessions` | None | `service_status` plus inputs |
| Live-mode freshness | Lags up to one projector run | Exact | Lags up to one projector run |
| `IS_NOT_APP_ROLE` mismatch (#2938) | Must be settled | Disappears | Must be settled |
| User's strict preference | Met | Relaxed: treated as process state, like the probes | Met |

**Recommendation:** A. The projector writes per-session service rows and `sessions` columns for HA connection state, `has_ever_connected`, bootstrap release, and the computed `system_status` (`starting`/`ok`/`degraded`, the logic in `runtime_query_service.py:328-358`, written by D19 issue 5 with today's inputs and extended by #2806 to derive from services and issues together per D12). `/health` becomes a read plus D8's freshness rule. Seeds can express degraded and starting states directly.
**Pick B instead if** seeded Diagnostics doesn't need services or status (screenshots of it can come from the demo stack), which deletes the `service_status` table and the #2938 reconciliation. **Pick C instead if** never: it keeps a lossy input.
**Reversibility:** easy (B's routes stay; moving a field between the seam and the DB is local)
**Ratified:** Chose persisting system health with status computed once in the process over keeping it live or deriving at read time, to let seeds express degraded/starting states with one derivation, accepting a per-session `service_status` table, a lag of up to one projector run in live mode, and settling #2938.

### D10: What does the web layer depend on, so live and snapshot modes can't drift?

**Deciding factor:** one factory and one place where the modes differ.

| | A: one factory over `WebContext(config, telemetry, live: LiveSeam \| None)` | B: `LiveSeam` protocol with live and snapshot implementations, two factories |
|---|---|---|
| Factories to keep in sync | One | Two |
| Where mode branching lives | One `LiveDep` that raises the snapshot problem response when `live is None` | Inside the snapshot implementation |
| No-core-imports in `web/` | True by construction | By convention |
| Compat-fixture generator | Same factory with a fake `LiveSeam` | Snapshot factory plus a separate fake |
| Sequencing | The context lands before the route switches | Fits with the system-status switch |

**Recommendation:** A. `create_fastapi_app(ctx: WebContext)` replaces `request.app.state.hassette`. `WebContext` carries config (CORS, auth, trusted proxies, retention values), the telemetry query service, and an optional `LiveSeam`, the single enumerated home of everything that still reads the process: liveness/readiness probes; `DatabaseService` state for `/telemetry/status` (D23, D24.4; the lag itself comes from the DB per D8.3); action routes; config reads (D11); app source file reads (D5); WS broadcast; and the current `session_id` (D6). Auth is `WebContext` config, enforced the same way in both modes. Other decisions cite this list instead of extending it. Snapshot mode passes `live=None`. Live mode's `LiveSeam` is a typed interface; the compat-fixture generator passes a fake implementation so it still pins action and probe response shapes.
**Pick B instead if** replacing `app.state.hassette` before the route switches collides with #2555 or the apps/mappers rewrite.
**Reversibility:** hard (every route's dependencies)
**Ratified:** Chose one `create_fastapi_app(WebContext)` factory with an optional `LiveSeam` over two factories, so live and snapshot modes cannot drift, accepting that the context must land before the route switches.

### D11: Who builds config persistence, given the #2767 config-override work?

**Deciding factor:** reach the persisted end state for config without building the config read model twice.

Context: the #2767 tracker (#2768 persists user-set app config overrides in a store hassette owns, layered over the file before validation, with per-field provenance; #2769 redefines the config read as per-field value, source, editability, default and per-instance values; #2853-#2855 extend that read with defaults) already plans config persistence. Under this ledger's model, overrides are desired state written by the API write path (a different fact from projected status, so not a second writer), and effective config plus provenance is observed state computed at app creation, which per D6 belongs in a session-keyed table. Secret fields are excluded, not masked: #2768 already says they are never exposed.

| | A: config stays on the live seam here; #2768/#2769 own persistence with a stated requirement | B: this initiative persists effective config per session now |
|---|---|---|
| Config read model built | Once, by #2769, in its final per-field shape | Twice: today's shape now, reshaped by #2769 |
| Config pages in snapshots | Unavailable until #2769 lands | Available now |
| Coupling | None: #2768 owns the app-creation merge point | This initiative must find the merge point #2768 is about to change |
| End state | DB-sourced config with provenance | Same |
| Global `HassetteConfig` | Read-only exposure is #539; same requirement applies there | Snapshot at session start |

**Recommendation:** A. In this initiative, `/config`, `/apps/{key}/config` and their schemas keep reading process memory through the live seam; in snapshot mode they return the snapshot problem response and the UI shows config as unavailable. The `log_retention_days` hint in the execution drawer reads from `WebContext` config. D19's Done-when is worded accordingly. #2768 and #2769 are amended to require: override storage lives in the DB as desired state; effective config plus per-field provenance is written per session at app creation (secrets excluded); and #2769's config read is served from the DB, so config then works in snapshot mode too.
**Pick B instead if** config in seeded snapshots is needed before #2767 is scheduled.
**Reversibility:** easy
**Ratified:** Chose to keep config on the live seam here and amend #2768/#2769 to make their read model DB-sourced, over persisting today's config shape now, to build the config read model once in its final shape, accepting that snapshots show config as unavailable until #2769 lands.

### D12: How do diagnostic signals fit with #2806's issues registry?

**Deciding factor:** rewrite `SystemStatusResponse` once, and make a new diagnostic signal cost no schema, wire or UI change.

Context: #2806 replaces `SystemStatusResponse`'s bespoke condition fields (`log_persistence_active`, `pending_wait_for_count`, `boot_issues`) with a generic issues registry modeled on Home Assistant's repairs registry: framework code raises an issue and clears it when it resolves; component state stays in `services`; the aggregate `status` is derived in one place from services and issues. Its open questions include whether issues survive a restart. Those fields are exactly the display-only diagnostics that would otherwise need their own columns or a JSON gauges column. #2806's body also lists `log_queue_drops` and `db_write_queue_drops`; those are counters, owned by D24 and deleted by D19 issue 7, and #2806 is amended to drop them.

| | A: no gauges column; diagnostics go through #2806's registry, which lands before the system-status switch | B: fold #2806 into this milestone | C: a JSON gauges column now, replaced by #2806 later |
|---|---|---|---|
| `SystemStatusResponse` rewritten | Once | Once | Twice |
| Cost of a new signal | Raise an issue | Same | A JSON key now, an issue later |
| Milestone scope | Unchanged; #2806 is a forced ordering | Grows by a large item with its own open questions | Unchanged |
| #2806's own sketch | Still needed; inherits this ledger's persistence rules | Absorbed here | Unaffected |

**Recommendation:** A. There is no JSON gauges column. Display-only diagnostics become #2806 issues; numeric accounting (drop counts) goes through D24's counter registry, since the issue is the condition and the counts are the numbers behind it. #2806 lands after D19 issue 5 (the projector writes its issues) and before issue 7 (the system-status switch), as a dependency inside the milestone (D19). It also raises D7.4's final-write marker as an issue. #2806's sketch adopts these rules from this ledger: the registry lives in the process; the projector (D1) writes the current issues per session (D6), so a previous session's issues are last-known, never current; the aggregate status is computed once in the process from services and issues and written per D9; and pipeline-health problems (projector lag, failing DB writes) surface through the live seam per D8, never only through persisted issues, because a DB-sourced "the DB is failing" issue dies with the DB.
**Pick B instead if** one sketch should settle #2806's open questions (issue shape, severity mapping) together with this one. **Pick C instead if** never: it rewrites the response twice.
**Reversibility:** easy
**Ratified:** Chose routing diagnostics through #2806's issues registry, landing before the system-status switch and adopting this ledger's persistence rules, over a JSON gauges column or folding #2806 in, to rewrite `SystemStatusResponse` once and make new signals schema-free, accepting a forced ordering on #2806.

### D13: What do the status WS messages carry, and what does "since restart" key on?

**Deciding factor:** the frontend holds no server state outside TanStack Query, and works the same against a snapshot.

| | A: payload-free post-commit invalidations; since-restart keys on `sessions.started_at` | B: keep payload messages alongside DB reads |
|---|---|---|
| Frontend overlay stores (`appStatus`, `serviceStatus`, `app-data.ts` helpers, `mergeServices`) | Deleted | Kept; split-brain remains in the browser |
| Works in snapshot mode | Yes | Since-restart depends on WS `uptime_seconds` (`use-scoped-query.ts:71-82`), absent in snapshots |
| Ordering | Broadcast after commit, same as `execution_completed` | Payload can race the DB |

**Recommendation:** A. `app_status_changed` and `service_status` become keyed, state-free invalidations emitted by the projector after commit: `app_status_changed` carries `app_key` and `instance_index` (no status), `service_status` carries the service name, so the frontend invalidates only the queries for that key. The `connected` message keeps `version` and drops `uptime_seconds` and `entity_count`. `/health` gains `session_started_at` (the current session's `started_at` in live mode, the latest session's in snapshot mode), and since-restart keys on it. `/health` keeps `uptime_seconds`, now derived from the session row in both modes (live: now minus `started_at`; snapshot: per D15), so the CLI's uptime rendering is unchanged and it needs no live seam. The frontend reads `connected.version` before strict validation of the rest of the message, so a tab running an old bundle after a server upgrade still shows the "server updated, reload" prompt whatever else changed in `connected`. `execution_completed` keeps its payload (it filters by key), and `log_hint` is unchanged (its pre-commit race is bounded by `use-log-data.ts`'s `PERIODIC_RESYNC_MS` refetch).
**Pick B instead if** never: it keeps the split this change removes.
**Reversibility:** easy
**Ratified:** Chose payload-free post-commit invalidations with since-restart keyed on `sessions.started_at` over keeping payload messages, to remove the frontend overlay and work in snapshot mode, accepting a refetch per status change.

### D14: What happens to `entity_count`?

**Deciding factor:** don't persist a field nothing uses.

**Recommendation:** remove `entity_count` from `/health` (D19 issue 7) and the WS `connected` message (issue 8), with no deprecation step, in the milestone's release. No frontend consumer reads it beyond the store type (research.md inventory row 14). It is a required field, so released clients reject a `/health` response without it: the removal ships with a `feat!:` title and `BREAKING CHANGE:` footer, `tools/wire_compat_ignore.txt` entries, and a deliberate-break allowlist added to the client-compat check (like `wire_compat_ignore.txt`, so the PR that removes it can pass `client_compat`), and hass-hassette bumps its pinned `hassette-client` in a release coordinated with it. No two-step deprecation: no release is cut mid-milestone (D19), so a defaulted interim field would buy nothing.
**Pick persisting it as a `sessions` column instead if** a consumer turns up during the build.
**Reversibility:** easy
**Ratified:** Chose removing `entity_count` over persisting it, to avoid storing a field with no consumer, accepting a breaking wire change.

### D15: How does snapshot mode present itself and answer live-only routes?

**Deciding factor:** a snapshot can never be mistaken for a live system by the people who open one, and it shows what the seed wrote.

**Recommendation:** `/health` reports `mode` (`"live"` or `"snapshot"`) and, in snapshot mode, `as_of`, which is the latest session's `projected_at` (`null` if it never projected) (D8; "latest session" is defined there), never a heartbeat. In snapshot mode `/health` serves the stored values as they are (status, services, HA connection), so a seeded `starting`, `ok` or `degraded` state renders as written; `mode` and `as_of` are the snapshot signal, and the UI renders stored values as last known under the banner. Snapshot mode is reached only through the dev-only `seed:serve` (D4), so no released client or hass-hassette install is pointed at one. Seed scenarios write `projected_at`, `stopped_at` and `finalized_at` explicitly. The UI shows a persistent banner ("Snapshot: data as of …; actions disabled") and disables action buttons. A session without `finalized_at` is labeled "process state unknown" (D8.5). `uptime_seconds` (required on `/health`) reports the latest session's span, `(stopped_at or projected_at or started_at) - started_at`. The frontend doesn't poll `/telemetry/status` when `mode` is `"snapshot"`, so its 409 never reads as a DB outage (D23). Every live-seam route (actions, config per D11, pipeline health) returns a 409 problem response with a `snapshot_mode` type; source returns 404 per D5. The DB is opened read-only. `/api/ws` is not mounted in snapshot mode (404). The frontend opens no socket when `/health.mode` is `"snapshot"`, and connection-dependent UI (overview dimming in `overview-tab.tsx`, the connection dot and unreachable hint in `system-health.tsx`) derives its state as `mode === "snapshot" ? "snapshot" : wsState`, never from socket absence alone. `snapshot_mode` is documented as non-retryable on its `ProblemCode` docstring.
**Pick forcing `status: degraded` and `websocket_connected: false` in snapshot mode instead if** snapshot mode ever becomes reachable by released clients (a public command, against D4); it hides seeded status. **Pick 503 instead of 409 if** clients should treat it as retryable; they shouldn't, since a snapshot never becomes live.
**Reversibility:** easy
**Ratified:** Chose `mode`/`as_of` on `/health` with stored values served as-is, a persistent banner, disabled actions, no WS in snapshot mode with mode-driven connection UI, and non-retryable 409 `snapshot_mode` problems over a retryable 503, so a snapshot can't be mistaken for a live system and shows what the seed wrote, accepting that clients must handle a new problem type and that only `mode` marks a snapshot on `/health`. (Re-ratified after the ledger challenge, Findings 1, 18 and 19; the forced `degraded` status dropped at the ledger comb, since snapshot mode is dev-only per D4.)

### D16: How do seeds line up with the UI's time windows?

**Deciding factor:** seeds render under the default presets without breaking deterministic fixtures.

**Recommendation:** `seed_db.py --anchor now|<ISO instant>` replaces `REFERENCE_INSTANT` (`scripts/seed_scenarios/base.py:23`) for that run; `ts()` (`:355-360`) reads the anchor. The default stays the fixed 2026-01-15 instant so `client_compat` fixtures and seed determinism tests are unchanged. `serve_seed.py` always seeds with `--anchor now`.
**Pick shifting time at serve time instead if** seeds had to be served unmodified; that would touch every query.
**Reversibility:** easy
**Ratified:** Chose a `--anchor now|<iso>` seed-time option with the fixed default kept over shifting time at serve time, to make seeds render under the default presets without touching queries or deterministic fixtures, accepting that a served seed must be regenerated to re-anchor.

### D17: Where do `next_run`, `fire_at` and `jitter` get persisted?

**Deciding factor:** no extra writes and no dependency on the projector.

**Recommendation:** write them in the two places a job's schedule is set: the `register_job` upsert (`repository.py:114`, called from `scheduler_service.py:233`), so a job that has not fired yet has timing, and the existing awaited UPDATE, `mark_job_status` (`repository.py:241-260`, called through the scheduler-side wrapper `persist_schedule_status`), which runs after every dispatch and reschedule including each recurring fire (`scheduler_dispatch.py:88-93`). A terminal transition (completed, cancelled) clears them; a reschedule overwrites them. Because registration rewrites them each session, a re-registered job never shows a previous session's `next_run`; after `APP_LOAD_COMPLETED`, jobs not registered in the current session have their timing cleared (the D1.6 removal point), so a removed app's job shows none. This is the one exception to D6's identity-only rule, because these columns describe the job's schedule, not a process counter, and they are overwritten on every fire. `enrich_jobs_with_live` and `enrich_jobs_with_live_data` (`web/utils.py`) and the `live_execution_counts` read path are deleted by D19 issue 6, once reads switch; listener and job guard counters go to the per-session tables of D6.
**Pick routing them through the projector instead if** jobs need timing changes recorded without a transition; none do today.
**Reversibility:** easy
**Ratified:** Chose writing timing in `register_job` and widening `mark_job_status` over routing timing through the projector, to persist schedule timing (at registration and on every transition) with no extra writes or projector dependency, accepting timing columns on the `scheduled_jobs` identity table.

### D18: What does projector run size cost, and what catches the pathological case?

**Deciding factor:** state the real costs and an automatic backstop, not a revisit threshold nobody is told about.

Context: D1.3 writes only changed rows, so run size scales with listeners and jobs whose per-session counters (D6) changed since the last run, plus the `session_counters` rows that changed (D24); idle entities cost nothing. Measured during the ledger challenge with a throwaway upsert benchmark (not committed) on a desktop NVMe (WAL, `synchronous=normal`, one transaction of counter-row upserts): 1,000 rows ~1 ms and ~0.06 MB of WAL; 10,000 rows ~11 ms and ~0.5 MB; 100,000 rows ~130 ms and ~4.7 MB. SD-card hardware is unmeasured and assumed 10-50x slower.

| | A: per-run metrics and chunked transactions now | B: per-run metrics and a WARNING past ~1,000 rows; chunk when seen | C: the first-ratified ~1,000-row revisit threshold | D: record measured costs; D8 is the automatic backstop; write volume named as the scaling cost |
|---|---|---|---|---|
| Writer hold at plausible sizes | Bounded | Tens to hundreds of ms | Same as B | Same as B |
| Pathological run detected automatically | Yes | Only by someone reading logs | No | Yes, via D8's lag degrade |
| Same-transaction history (D2) | Split across chunks | Kept | Kept | Kept |
| Reduces write volume | No | No | No | No; names the cadence as its lever |
| New machinery | Chunking and metrics | A metric and a log line | None | None |

**Recommendation:** D. One projector run is one transaction. At plausible sizes it holds the single writer for milliseconds to (on slow flash) hundreds of milliseconds, and other writers simply wait. A run long enough to exceed D8.7's per-attempt timeout (on the order of a million changed rows) reports itself: projection lag passes two resync intervals and `/health` degrades, with no log reading needed. The cost that does scale is write volume: about 1,000 active rows per resync at the default interval is roughly 200 MB/day of WAL writes, relevant to flash wear on SD-card installs. Chunking doesn't reduce it; the lever, if it ever matters, is the cadence at which per-entity counter rows are written.
**Pick A instead if** deployments with hundreds of thousands of changed rows per run become plausible. **Pick B or C instead if** never: their trigger depends on someone noticing a log line.
**Reversibility:** easy
**Ratified:** Chose recording measured costs with D8's lag degrade as the automatic backstop and write volume named as the scaling cost, over chunking now, a log-based trigger, or an unobservable revisit threshold, to state what actually happens at every size without a signal nobody sees, accepting that write volume is named but not bounded. (Revised by the ledger challenge, Finding 20.)

### D19: How is this delivered?

**Deciding factor:** each step lands green and independently reviewable.

| | A: a milestone of issues built against this ledger | B: one build session, one PR |
|---|---|---|
| PR size | Medium PRs | One very large PR across backend, wire, frontend and seeds |
| Review | Per-step | All at once |
| Roadmap fit | Goes to Later as an initiative with a Done-when | Same, but blocks until done |
| Use of `/mine-sketch` build mode | Per issue, or none: each issue cites this ledger | Directly |

**Recommendation:** A. File a "DB as source of truth" milestone whose Done-when is: `mise run seed:serve --scenario degraded` serves a seeded DB to the Vite UI with no Hassette instance and no runtime stubs, rendering the scenario's apps, instance statuses including DEGRADED, handlers, jobs with next run, and services under the default time preset with a snapshot banner; no GET route that renders automation state reads process memory, except config (D11) and app source (D5), which stay on the live seam; and the compat-fixture generator uses the shared factory with a fake live seam.

New issues (eight new, plus #1446 rewritten as issue 5), each citing this ledger. Filed as 1 #2989, 2 #2990, 3 #2991, 4 #2992, 5 #1446, 6 #2993, 7 #2994, 8 #2995, 9 #2996; the MSW/dev-panel split of #760 is #2988.

| # | Issue | Depends on |
|---|---|---|
| 1 | Seed timestamp anchor (D16) | nothing |
| 2 | Heartbeat interval and progress-based strikes (D3); the `PipelineCounters` registry with every loss path routed through it and the per-component accessors deleted, with the accessors' current consumers (`/telemetry/status`, `/health`'s `log_queue_drops`/`db_write_queue_drops` via `runtime_query_service.py:371-372`, and session finalization's `sessions.dropped_*` write at `core.py:671`) reading the registry until issues 5 and 7 replace them (D24.1); `enqueue()` yielding to waiting `submit()` callers (D21) | nothing |
| 3 | `scheduled_jobs` timing columns, written at registration and on every transition (D17) | nothing |
| 4 | `WebContext` and the live seam (D10), switching every `create_fastapi_app` caller, including the compat-fixture generator with a fake `LiveSeam`; `LiveDep` is wired, but the `snapshot_mode` code itself lands in issue 9 with its client classification | #2695 |
| 5 | Runtime tables and the projector (D1, D2, D6, D7's ordering and final run, D8's `projected_at`, D9's writes, D22's retry backoff, D24.2's `session_counters` writes and the `sessions.dropped_*` drop migration, D25's retention), with seed scenarios writing runtime rows, counter rows, `projected_at`, `stopped_at` and `finalized_at`; WS message shapes unchanged (today's messages, sent post-commit): #1446 rewritten in place | 2, #2695, #2938 |
| 6 | Apps and telemetry reads from the DB through the shared session join (D6's `unknown` before the first run, D8.2's latest-session rule, D8.5's non-current-session reading), deleting `enrich_jobs_with_live` and the `live_execution_counts` read path (D17) | 3, 4, 5, #2555 (or absorbs it) |
| 7 | System status from the DB (D9), freshness on `/health` and `/telemetry/status` (D8), `session_started_at` (D13), `entity_count` removal with the client-compat break path (D14), the DB-unavailable UI state (D23), counters read from `session_counters` with the status-response counter fields replaced and `/telemetry/status` reduced to the probe (D24.3-4), and the CLI rendering of the changed models including `CliFormat` for `counters` | 4, 5, #2806 |
| 8 | Keyed WS invalidations, `connected` changes and version-first parsing, frontend overlay removal (D13) | 5, 7 |
| 9 | Snapshot mode and `seed:serve` (D4, D5, D15; config unavailable per D11), including classifying `snapshot_mode` in the client as a non-retryable class in `CODE_ERRORS` (`client/src/hassette_client/errors.py:339`), and compat coverage for it in `tools/client_compat_coverage.py` (an `EXCLUDED` entry with its reason, or a `live=None` generator variant) | 1, 4-8, #2890 |

**Release rule.** Breakage reaches users only through a release, so the milestone's consumer-visible changes ship together: no release is cut between the first of #2806 and issues 4-9 merging and the last. Each PR must pass CI on its own (tests, lint, schema freshness, `wire_compat`, `client_compat`); the orderings in the table are the ones CI forces (the compat generator calls the factory; `client_compat` coverage needs seed runtime rows once reads switch; frontend tests parse WS messages) plus the data each issue reads. Functional gaps between merges that CI doesn't catch are acceptable, since no release ships them. Each issue ships its own docs (`.claude/rules/design-completeness.md`), including D8.7's stated freshness bound with issue 7.

Existing issues, by how they relate:
- **Pulled into the milestone as work** (the Done-when fails without them, directly or as a prerequisite): #2695 (D20), #2806 (D12; depends on issue 5, gates issue 7, amended to drop the drop-count fields), #2555, #2938 (D9), #2890 (DEGRADED instance status from a seed), and #1446 (rewritten as issue 5).
- **Pulled in and closed by a milestone PR**, because what they describe is deleted or superseded: #1895, #1894 and #1609 (closed by issue 8); #2440 (closed by issue 6, which deletes live job enrichment per D17); #1600 (superseded by #2890 and issue 9); #2844 (the zero-fallback catches are deleted by issue 7, per D24.4); #760 (Phase 3 is issue 9; Phases 1-2, MSW browser scenarios and a dev panel, are refiled as a new linked issue).
- **Linked, outside the milestone** (same purpose, but the Done-when doesn't need them), via blocked-by relationships and body references: #855 (blocked by issue 9); #2767, #2768 and #2769 (amended per D11); #1463, #2285 and #2288 (blocked by #2806); #1601 (related to issue 8); #2545 (DB-stall latency, which matters more once every read goes to the DB); #2365 (sampling bias in framework-tier aggregates; D24's `sampled` kind makes sampling visible but doesn't correct the aggregates); and the new MSW/dev-panel issue.

**Pick B instead if** the work turned out much smaller than estimated.
**Reversibility:** easy
**Ratified:** Chose a milestone of eight new issues and #1446 rewritten, plus pulled-in prerequisites, superseded issues closed by milestone PRs, and the rest linked, over one build, to land the work in reviewable steps with every related issue accounted for, accepting a larger milestone than the eight new issues alone. (Re-ratified after the ledger challenge revised issue scopes, dependencies and the release rule, Findings 2, 7, 9, 10, 15-19.)

### D20: How does this sequence with #2695 (make the database a required core subsystem)?

**Deciding factor:** avoid renaming the same code twice, and build on the contract this design presupposes.

Context: #2695 renames `TelemetryQueryService`, `TelemetryRepository`, `hassette.core.telemetry`, `telemetry_unavailable` and `DatabaseConfig.telemetry_write_queue_max` by role, removes "DB optional" typing (`| None` service wiring) and degradation paths, and makes a DB that cannot open fail startup. Nearly every issue in D19 edits those modules, and "the DB is the source of truth with no in-memory fallback" presupposes a required DB.

| | A: #2695 inside the milestone, landing first and gating issues 4-9 | B: forced ordering, outside the milestone | C: no ordering |
|---|---|---|---|
| Rename churn | Once, before the new code exists | Once | Twice: new code written against old names, then renamed |
| Consistent with D19 (prerequisites pulled in) | Yes | No | No |
| Contract the design builds on | Required DB in place first | Same | Built on the optional-DB contract, revised later |
| Independent issues (seed anchor, heartbeat/drops, job timing columns) | Can still land before #2695 | Same | Same |

**Recommendation:** A. #2695 lands before D19's issues 4-9; issues 1-3 don't depend on it. The DB-failing behavior in this design (routes return the DB-unavailable problem, the lag banner per D8) uses #2695's renamed names and keeps only the degradation paths #2695 keeps as runtime resilience.
**Pick B instead if** the milestone should hold only work its Done-when names directly. **Pick C instead if** never: it doubles the rename work.
**Reversibility:** easy
**Ratified:** Chose #2695 inside the milestone, landing first and gating issues 4-9, over an outside forced ordering or none, to rename once and build on a required-DB contract, accepting that most of the milestone waits on a large prerequisite.

### D21: How do awaited writes avoid starvation by fire-and-forget producers?

**Deciding factor:** a log storm can't falsely degrade the UI, without the general write lane D8 rejected.

Context: `submit()` waits with `await queue.put(...)` (`database_write_queue.py:233`) and `enqueue()` uses `put_nowait` (`:277`) on the same bounded queue. When the worker frees a slot, asyncio wakes the waiting putter on a later loop tick; a `put_nowait` that runs first takes the slot. Under a sustained log storm every projector attempt (D8.7) and heartbeat (D3) can time out, so the UI goes degraded because of the storm alone. (D3's progress-based strikes already keep the storm from restarting `DatabaseService`, since the worker keeps completing jobs.)

| | A: one-slot priority path in the worker | B: `enqueue()` treats waiting `submit()` callers as "full" | C: keep D8; a log-storm ship-gate test sets the banner threshold |
|---|---|---|---|
| Removes starvation | Yes | Yes | No; measures it |
| Reopens D8's rejection of a second queue discipline | Partly (a narrow slot, not a lane) | No | No |
| New machinery | A pending-job slot checked before `queue.get()` | A waiting-submitter counter on the write queue, checked in `enqueue()` | One test |
| Drops during storms | Unchanged | More: every `enqueue()` producer (logs and execution records) drops while an awaited write waits | Unchanged |

**Recommendation:** B. The write queue counts its own waiting `submit()` callers (incremented before `queue.put`, decremented when it returns or raises; never asyncio's private `_putters`). While that count is above zero, `enqueue()` drops and counts the item the same way it does when the queue is full, so an awaited write always gets the next free slot. Those drops are counted through D24's registry under their own reason. A test pins that a sustained `enqueue()` storm cannot make a concurrent `submit()` time out while the worker is draining.
**Pick A instead if** dropping more telemetry during storms is unacceptable. **Pick C instead if** the starvation should be measured before anything changes.
**Reversibility:** easy
**Ratified:** Chose having `enqueue()` yield to waiting `submit()` callers over a worker-side priority slot or a measure-first test, to remove the starvation at its cause without a second queue discipline, accepting more fire-and-forget drops (logs and execution records) while an awaited write waits. (Added by the ledger challenge, Finding 7.)

### D22: How does the projector retry a failed write, and what does it log?

**Deciding factor:** a failing DB produces one clear signal, not a self-amplifying log and retry storm. Projector ERRORs are persisted through the same write queue (`logging_.py:313-325`), so per-attempt logging feeds the path that is failing.

| | A: exponential backoff, transition-only logging | B: no backoff; failed keys wait for the next resync, logs deduplicated | C: no pacing |
|---|---|---|---|
| Retry rate under sustained failure | Bounded, ramps to one per resync | One per resync | Unbounded (debounce cadence) |
| Log feedback into the queue | One ERROR per failure episode | One per resync unless deduped | One per attempt |
| Recovery latency after a transient failure | Fast (starts at the floor) | Up to one resync interval | Fast |
| New state | Backoff timer and failing flag | Failing flag | None |

**Recommendation:** A. After a failed write job the projector retries with exponential backoff from a floor of the debounce (D1.2) to a ceiling of the resync interval; new dirty marks during backoff don't trigger an earlier run. It logs one ERROR on entering the failing state and one INFO with the failure count on the first success after it, nothing per attempt. The first success resets the backoff. D8's lag banner is the steady-state signal while failing. Tests pin the bounded retry rate and the one-ERROR-per-episode logging.
**Pick B instead if** the simplest bounded behavior is worth up to one resync interval of extra staleness after a transient failure. **Pick C instead if** never: the feedback loop through log persistence is real.
**Reversibility:** easy
**Ratified:** Chose exponential backoff with transition-only logging over resync-only retries or unpaced retries, to bound retry rate and log feedback while recovering fast from one-off failures, accepting a backoff timer and failing flag in the projector. (Added by the ledger challenge, Finding 9.)

### D23: What does the UI show while the DB is unavailable?

**Deciding factor:** a DB outage shows one clear state in the UI and never gets the container killed for a UI-only failure.

Context: `DatabaseService` is TRANSIENT with a restart budget of 3 per 120s (`database_service.py:92-97`), and `read_db` raises until `on_initialize` reopens it (`:187-197`). Once every automation-state read goes to the DB, a restart fails `/health`, `/apps` and every refetch together, and budget exhaustion leaves the apps running behind a permanently failing UI. The live seam keeps answering: `/telemetry/status` returns 503 with `degraded: true` when its DB health query fails (`routes/telemetry.py:74-104`), and `/health/live` reads no DB (`routes/health.py:18`).

| | A: one live-seam-driven "database unavailable" UI state; liveness unaffected; reads keep their last cached data | B: per-route DB-unavailable problems only (D20), no unified UI state | C: unspecified |
|---|---|---|---|
| Operator sees a coherent state | Yes | Scattered errors | Undefined |
| Container killed over a UI failure | No (stated) | Unstated | Unstated |
| Budget exhaustion visible | Yes, via the live seam | Partly | No |
| Frontend work | One state | Per-route error handling | Unknown |

**Recommendation:** A. DB-backed routes keep returning the DB-unavailable problem response (D20). The UI derives one "database unavailable" state from `/telemetry/status` (live seam), shown as a single blocking banner that names restarting, cooling down (restart budget exhausted, next retry scheduled) and given up, read from `/telemetry/status`'s `database` field (D24.4), in place of per-route errors. Queries keep their last successful data under the banner (TanStack Query's default on a failed refetch) and resume when `/telemetry/status` reports the DB back. `/health/live` never fails because the DB is unavailable; readiness keeps its existing rules. Snapshot mode doesn't apply: its DB is a read-only file, and the frontend doesn't poll `/telemetry/status` there (D15). Tests pin the banner state for restarting, cooling and failed, and that liveness stays green during a DB restart.
**Pick B instead if** DB restarts are rare enough that per-route errors suffice. **Pick C instead if** never: budget exhaustion leaves a silent blank UI.
**Reversibility:** easy
**Ratified:** Chose one live-seam-driven "database unavailable" UI state with liveness unaffected and cached data kept, over per-route errors or leaving it unspecified, to give the operator one explained state during a DB outage, accepting one more UI state. (Added by the ledger challenge, Finding 16.)

### D24: How are process-wide counters modeled, stored and read?

**Deciding factor:** a new counter costs an enum member, not a migration plus a wire field plus a UI change, and every loss path is counted under one taxonomy.

Context: process-wide counters have accumulated one at a time, each with its own accessor and bespoke int field: execution `dropped_overflow`/`dropped_exhausted`/`dropped_shutdown`/`dropped_filtered` and `error_handler_failures` (`command_executor.py:263-287`, on `TelemetryStatusResponse`, `wire/src/hassette_wire/telemetry.py:378-386`), log drops (`logging_.py`), `log_queue_drops` and `db_write_queue_drops` (on `SystemStatusResponse`, `wire/src/hassette_wire/health.py:60-64`), and WS broadcast drops (`runtime_query_service.py:449`). Several loss paths are counted nowhere (research.md, "Is the risk real today?": non-retryable write errors, no-session drains, `drain_and_persist` raising, blocking-event `enqueue` drops), D21 adds another, sampling is not distinguished from loss (#2365), and `/telemetry/status` falls back to zeros through catches that can never fire in a running process, since `CommandExecutor` is wired in `Hassette.__init__` (`core.py:217`; #2844). D12 settles conditions (#2806 issues) but not the numbers behind them.

| | A: one counter registry, persisted as rows, read from the DB | A2: same registry; live seam serves live values, projector persists them | B: bespoke typed fields, naming fixed, uncounted paths added |
|---|---|---|---|
| Cost of a new counter | An enum member | An enum member | A migration, a wire field, a UI change |
| Read source | DB with D8 freshness, like all other state | Live seam in live mode, DB in snapshots: two readers of one fact | Live seam |
| Snapshot and crash | Seed rows; a crashed session keeps counts at most one projector run old | Same | Needs columns as well |
| Wire | Bespoke int fields replaced by a `counters` list (breaking) | Same | Additive only |
| Loss vs sampling (#2365) | By kind | By kind | Ad hoc |
| Live freshness | Lags up to one projector run | Exact | Exact |
| Prior art | Prometheus/OpenTelemetry: one counter with labels, not one metric per reason | Same | None |

**Recommendation:** A.
1. One in-process `PipelineCounters` registry keyed by a closed enum of `(stage, reason)`, each member tagged `loss`, `sampled` or `failure`. Every process-wide counter in the context above, and every loss path named there as uncounted, increments through it; the existing per-component accessors are deleted. The re-enqueue overflow that `execution_pipeline.py:375` counts as exhausted is counted as overflow.
2. The projector (D1) writes the registry's values to `session_counters(session_id, name, value)` on each run and in the final run (D7); the `sessions.dropped_*` columns are dropped by migration. Seeds write counter rows.
3. Reads come from the DB through D8's session join. `SystemStatusResponse` and `TelemetryStatusResponse` lose their bespoke counter fields; `/health` carries a `counters` list of `{name, stage, reason, kind, value}`, and the UI renders loss and sampling separately. This ships through D14's break path in the milestone's release.
4. `/telemetry/status` keeps only the probe: `degraded` from the DB health query (503 when it fails, as today), plus defaulted `projection_lag_seconds: float | None = None` (D8.3) and `database: Literal["ready", "restarting", "cooling", "failed"] = "ready"`, the `DatabaseService` state D23 reads: `restarting` between restarts, `cooling` in `EXHAUSTED_COOLING` (budget exhausted, a retry scheduled after `cooldown_seconds`; `DatabaseService`'s `max_cooldown_cycles` is the default 0, unlimited, `resources/restart.py:46`), and `failed` only in `EXHAUSTED_DEAD`. Both 200 and 503 bodies carry `database`. Projector lag never changes its HTTP status. The zero-fallback catches are deleted (#2844).
5. Not in the registry: per-listener and per-job guard counters (D6's per-session tables, because they belong to entity rows), gauges such as `pending_wait_for_count` (#2806 issues per D12), and private escalation state (heartbeat strikes, parent-guard skips).

**Pick A2 instead if** drop counts must be exact to the second in live mode. **Pick B instead if** the counter set were closed; the uncounted paths show it isn't.
**Reversibility:** easy
**Ratified:** Chose one `(stage, reason)` counter registry persisted as `session_counters` rows and read from the DB, over a registry with a live reader or bespoke typed fields, to make a new counter cost one enum member and count every loss path under one taxonomy, accepting a breaking change to both status responses and a projector-run lag on counts. (Added during the ledger challenge, from Finding 17.)

### D25: How are the new session-keyed tables retained and deleted?

**Deciding factor:** every new table has a deletion path that matches its growth shape, and a session is never half-deleted.

Context: append-only tables (`executions`, `blocking_events`, `log_records`) age out by their own timestamps as `RetentionTarget`s (`core/retention_targets.py`). A `sessions` row is deleted in parent-guard step 4 (`database_retention.py:217-254`) only once it stopped before the cutoff, is not current, and no `executions` or `blocking_events` row references it; the size failsafe never reclaims sessions. Session-referencing FKs are plain `REFERENCES sessions(id)` with no cascade (migrations 001, 005, 009). The new tables are of two kinds: snapshot-state tables (`app_runtime`, `app_instances`, `service_status`, the per-session listener and job counter tables, `session_counters`), bounded at one row per entity per session; and the append-only `app_status_events` (D2), which grows within a session.

| | A: snapshot-state rows deleted with their session; `app_status_events` ages out as its own target | B: every new table is its own age-based `RetentionTarget` | C: `ON DELETE CASCADE` on the new FKs |
|---|---|---|---|
| Snapshot rows vs their session | Same lifetime | Can age out first, leaving a session that reads `unknown` | Same lifetime |
| Event growth for a flapping app in a long session | Bounded by `retention_days` | Bounded | Unbounded while the session lives |
| Fits existing convention | Yes: explicit deletes, plain FKs, the NOT EXISTS guard | Yes, with more targets | No: a new FK style that depends on the `foreign_keys` pragma |
| Size failsafe | Sessions stay exempt; events follow their target's setting | Each table needs a failsafe setting | Unchanged |

**Recommendation:** A. Parent-guard step 4 deletes a session's snapshot-state rows in the same transaction, immediately before the session row, under the same conditions. `app_status_events` becomes a `RetentionTarget` on its event timestamp with `retention_days`, and joins step 4's NOT EXISTS guard alongside `executions` and `blocking_events`. New FKs stay plain `REFERENCES`. Tests pin that deleting an eligible session removes its snapshot-state rows, that a session with a referencing event row is kept, and that events past the cutoff age out.
**Pick B instead if** runtime rows of old sessions should disappear before the session row does. **Pick C instead if** the schema moves to cascading FKs in general, a larger change than this.
**Reversibility:** easy
**Ratified:** Chose deleting snapshot-state rows with their session and ageing `app_status_events` as its own retention target, over per-table targets or cascading FKs, to match each table's deletion to how it grows on the existing parent-guard pattern, accepting more statements in parent-guard step 4. (Added by the ledger comb.)

## Assumed

- The awaited `submit()` write path raises on failure or a 60s deadline instead of dropping; only appended telemetry uses the droppable `enqueue()` path. Evidence: `src/hassette/core/database_write_queue.py:199-258, 260-288`.
- `app_manifests` has no `session_id`; it is an identity snapshot table. Evidence: `src/hassette/migrations_sql/011.sql:6-7`.
- `persist_schedule_status` runs an awaited UPDATE on `scheduled_jobs` after every dispatch and reschedule, including recurring fires; registration goes through the `register_job` upsert, which writes no timing today. Evidence: `src/hassette/core/scheduler_dispatch.py:88-93`; `src/hassette/core/telemetry/repository.py:114, 241-260`; `src/hassette/core/scheduler_service.py:233`.
- The DB heartbeat defaults to 300s and its timeout and escalation constants are sized for that. Evidence: `src/hassette/config/models.py:86`; `src/hassette/core/database_service.py:37-45, 278-322`.
- `finalize_session` runs in `before_shutdown`, before child services stop and before `flush_queue` increments `_dropped_shutdown`. Evidence: `src/hassette/core/core.py:645-677`; `src/hassette/core/execution_pipeline.py:188-230`.
- `block_app` emits no bus event, and `apps_changed` is broadcast directly from `APP_LOAD_COMPLETED`. Evidence: `src/hassette/core/app_registry.py:126-134`; `src/hassette/core/runtime_query_service.py:134-139`.
- `/telemetry/status` returns zeros when a counter accessor raises `AttributeError`/`RuntimeError`. Evidence: `src/hassette/web/routes/telemetry.py:101-110`.
- System status is derived from live flags and children, including `has_ever_connected`. Evidence: `src/hassette/core/runtime_query_service.py:328-358`; `.claude/rules/core-startup.md`.
- The frontend gates and keys since-restart queries on WS `uptime_seconds`. Evidence: `frontend/src/hooks/use-scoped-query.ts:71-82`.
- `log_hint` is emitted at log `emit()` time, before persistence, and the log table recovers via a periodic refetch. Evidence: `src/hassette/logging_.py:152-168`; `frontend/src/components/shared/log-table/use-log-data.ts` (`PERIODIC_RESYNC_MS`).
- Seed timestamps all come from `ts()`, offset from a fixed `REFERENCE_INSTANT`. Evidence: `scripts/seed_scenarios/base.py:23, 355-360`.
- The compat-fixture generator builds its app over `create_hassette_stub` with action mocks and auth enabled, and pins action success shapes. Evidence: `tools/generate_client_compat_fixtures.py:248-269`.
- The CLI reads only the HTTP API. Evidence: `design/research/2026-10-16-db-source-of-truth/research.md`, "Current state".
- Pre-v1 clean breaks: no compatibility shims; breaking wire changes use `feat!:` with exactly one `BREAKING CHANGE:` footer. Evidence: `CLAUDE.md` ("Changelog"); `wire/` is released in lockstep with hassette.
- The Vite dev server proxies the API to `VITE_PROXY_TARGET`. Evidence: `frontend/vite.config.ts:9`.

## Build

- [ ] Implementation and tests committed
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**

## Addendum
