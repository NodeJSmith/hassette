# Design: Lifecycle history writers

**Date:** 2026-11-13
**Status:** draft
**Mode:** sketch
**Issues:** #3678
**Parent:** design/specs/142-diagnostic-evidence/design.md
**Prior art:** design/research/2026-11-13-framework-timeline/peer-check.md

## Summary

Connection and app lifecycle history lives only in memory and in logs today, so "what happened around 05:00" can't be answered after the fact. This change adds one append-only lifecycle table and its three writers: app status rows from app state transitions, connection rows from `OutageLog`, and block rows (`blocked`, `unblocked`, `removed`) from block reconciliation. It implements parent D1, D2 and D12 and refines parent D11's subscriber. Reading the table (`hassette timeline`, the merged API route, sessions query, loss count) is #4084 and is out of scope. So is the web UI.

Research: `design/research/2026-11-13-framework-timeline/research.md` (Q1–Q4, Q8, PR 1 of its split) and `design/research/2026-11-13-framework-timeline/peer-check.md` (each decision against peers). The parent's brief, `design/research/2026-11-01-diagnostic-evidence/prior-art.md`, covers the milestone as a whole.

New pieces and their homes:

- **Lifecycle table:** `src/hassette/migrations_sql/026.sql` (columns per D5).
- **Per-kind details models:** one small Pydantic model per row kind for the `details` JSON (D5), next to the repository insert in `src/hassette/core/telemetry/`.
- **Retention:** a new `RetentionTarget` in `src/hassette/core/retention_targets.py` on `database.retention_days`, `failsafe_exempt=True`. A `NOT EXISTS` line for the table goes in the session delete guard in `src/hassette/core/database_retention.py` (parent D12).
- **The one writer:** a sync, enqueue-based `SessionManager` method in `src/hassette/core/session_manager.py`, plus the repository insert. It never awaits, so sync callers (block reconciliation) can call it. It checks for a session before building the insert. Drops are handled per the Posture's failure-handling stance, with one new `PipelineCounter` member in `src/hassette/core/pipeline_counters.py` covering all three drop paths: queue full (`enqueue` returned False), queue not live (`enqueue` raised `RuntimeError`), and no session. The WARNING is paced like `ApiWriteRecorder.warn_drop` (`src/hassette/core/api_write_recorder.py`). Unlike `ApiWriteRecorder.enqueue`, the not-live path is counted, not just logged at DEBUG.
- **App rows:** the funnel in D1, deduplicated per D2, with the dedupe map on `SessionManager`.
- **Connection rows:** written from `OutageLog` (`src/hassette/core/websocket_reconnect.py`) on each connection-state change per D4, through the callable in D6.
- **Block rows:** written inside `reconcile_blocked_apps` (`src/hassette/core/app_lifecycle_config.py`), per D3.
- **Seeds and docs:** lifecycle rows in `scripts/seed_scenarios/` (`base.py` plus `healthy.py` and `lifecycle.py` at least), and the table, its retention and its best-effort contract on `docs/pages/core-concepts/database-telemetry.md`.

The PR body names every lifecycle transition that sends no state event and so writes no row (parent D2). The research brief's Q1 lists the known ones.

## Posture

- **Failure handling:** best-effort. Every dropped row is counted under one new `PipelineCounter` member and logged once per episode at WARNING. It is never retried and never affects the lifecycle path that wrote it (parent posture).
- **Compatibility:** clean break, since the project is pre-V1. The new table starts empty with no backfill. App state send sites may be restructured freely. No wire changes in this PR.
- **Scope:** writers and the table only. The read path is #4084. Docs cover only the telemetry database page.
- **Rollout:** ships outright, no flag. Migration `026.sql`.
- **Hardening:** project defaults. The parent D12 growth estimate (about 25 MB for one app crash-looping every minute over 30 days) must hold for connection rows too; D4 states their figure.
- **Altitude:** `build`; one session builds it.

## Decisions

### D1: How do app status rows reach the writer? (refines parent D2 and D11)

**Situation:** `HassetteAppStateEvent` is built and sent at six sites: `app_lifecycle_start_stop.py` lines 198, 208, 227, 399 and 466, and `app_lifecycle_instances.py` line 459. A seventh place, `emit_app_state_change` (`app_lifecycle_instances.py:496-507`), already funnels the outcome events. Parent D11 rules out a listener on Hassette's own bus, because `before_shutdown` removes those listeners before apps stop. There's a second reason: `BusService.serve` (`core/bus_service.py:759`) leaves its loop when shutdown is set without draining buffered events, so the last app's STOPPED can reach no listener at all. That was found by reading the code, not reproduced. Parent D2 wanted rows "from one subscriber" so a new lifecycle path that sends the event is covered automatically.

**Deciding factor:** every transition that sends the event writes a row, including at shutdown, with the fewest layers.

| | A: one funnel that writes, then sends | B: tap in `Hassette.send_event` | C: `ObserverList` on the lifecycle service | D: listener on a SessionManager-owned `Bus` |
|---|---|---|---|---|
| Last app's STOPPED at shutdown | Queued (lost only if the drain times out) | Queued | Queued | Can be lost (bus drain) |
| New send site covered | Only through the funnel; a structural test fails if `src/hassette/core/` sends the event anywhere else | Automatically | Same as A | Automatically |
| Layers added | None; one call | Telemetry check in the send path every HA event takes | Observer list with one consumer | Bus, dispatch, executor |
| Test harness | Funnel runs; writer no-ops without a session | Harness replaces `send_event` (`testing/_harness.py`), so the tap doesn't run | Same as A | Listener runs on the harness bus; the shutdown drain gap is unchanged |
| Precedent | `ApiWriteRecorder` direct call | none | `WebsocketService.connected_observers` | `RuntimeQueryService`'s own `Bus`, for in-memory state only |
| What peers do | Prefect: one funnel (`set_flow_run_state`) writes the state row and emits the event from inside it. Airflow 3: direct calls at each transition; sites were missed twice (PRs 61932, 59639) | none found | none found | HA recorder: a synchronous `MATCH_ALL` bus listener |

**Recommendation:** A. Widen `emit_app_state_change` (or add a sibling on the same class) to build the event, call the `SessionManager` writer, then send, and route all six sites through it. A test fails if `HassetteAppStateEvent` is sent from anywhere else in `src/hassette/core/`; `src/hassette/testing/_simulation.py` is exempt, because its harness-only simulation of another app's status never reaches the writer. This replaces parent D2's "subscriber" mechanism while keeping what it was for: no transition that sends the event can skip the row.
**Peer divergence:** matches Prefect and Airflow 3; the structural test guards against the missed-site failure Airflow hit twice. Diverges from HA's recorder (a bus listener), for a known reason: HA's listener runs synchronously and HA has a final-write shutdown stage, while Hassette's bus buffers events and removes listeners before apps stop.
**Pick B instead if** you'd rather have automatic coverage than keep telemetry out of the general send path. **Pick C instead if** a second consumer of app transitions is expected soon. **Pick D instead if** the bus drain is fixed first and you want writers decoupled from senders.
**Reversibility:** easy (internal)
**Ratified:** Chose one funnel that writes the row and then sends the event, with a structural test banning other sends from `src/hassette/core/` (exempting `testing/_simulation.py`), over a `send_event` tap, an observer list, or a bus listener, so every transition that sends the event writes a row even at shutdown with no added layer, accepting that a new send site is caught by a test rather than covered automatically, and that a shutdown drain that times out can abandon the final rows with a WARNING.

### D2: What happens when the same status is sent twice?

**Situation:** site 198 in `_start_app_unlocked` sends FAILED for every failed instance on each start. Some of those failures are new, recorded moments earlier by `create_instances`, and some are stale ones re-sent so the UI's status cache stays in sync. The comment there accepts the re-sends as harmless for the frontend. Written naively, each `start_app` on an app with stale failures adds duplicate FAILED rows. The writer is fire-and-forget and never learns the id of the row it wrote. Parent D1 says #1446's projector later replaces this writer with "one row per observed status change".

**Deciding factor:** rows record changes, not cache re-syncs; a drop never hides a later row; and the table stays append-only.

| | A: writer skips a row identical to the last one written for that (app, instance) | B: split site 198 into new failures (rows) and stale re-syncs (no rows) | C: write every event | D: Kubernetes-style `count`/`last_ts` updated on a repeat |
|---|---|---|---|---|
| Stale re-send | No row | No row | Duplicate row | Counted on the earlier row |
| A second, identical failure with no event between | Collapses into the first row; one with a different `details` (exception type, needs-restart) is written | Row written | Row written | Counted on the earlier row, indistinguishable from a re-send |
| New state | One map of last row content (`to_status`, `details`) per (app, instance), on `SessionManager`, created empty with the session | None, but site 198 has to know which names `create_instances` touched | None | The map plus each row's id |
| Table stays append-only (parent D1) | Yes | Yes | Yes | No; repeats become UPDATEs |
| Matches #1446's "per observed change" | Yes | Mostly | No | No |
| Also covers future re-sync sites | Yes | No; each one needs the same split | No | Yes |
| A failed enqueue or missing session | The entry is evicted, so the next event always writes (at most one duplicate re-sync row) | n/a | n/a | n/a |
| What peers do | Kubernetes dedupes identical events in the writer (key: source, object, type, reason, message; `events_cache.go:52-67`), and a failed sink write never suppresses a later event (`event.go`) | HA, Airflow and Prefect dedupe at the source and record whatever reaches the writer | Prefect writes RUNNING→RUNNING (PR 9447) | Kubernetes bumps `count`/`lastTimestamp` on a repeat (`events_cache.go:327-352`) |

**Recommendation:** A. It's one rule in the writer, it covers any future re-sync site, and it's already what #1446 will do. Two rows are identical when `to_status` and `details` both match, so a stale re-sync (rebuilt from the same stored error and needs-restart flag) is skipped, and a repeat failure with a new exception type is written. A dedupe skip leaves the entry as it is. The entry advances only when `enqueue` returned True, and it is evicted when `enqueue` returned False, raised, or found no session. Entries for instances that no longer exist stay until the session ends; the map is bounded by the number of instances. A real change in status, or a STOPPING/STOPPED in between, still writes.
**Peer divergence:** HA, Airflow and Prefect dedupe at the source. Hassette dedupes in the writer for a known reason: `HassetteAppStateEvent` doubles as a UI cache re-sync (site 198), which HA keeps separate with `force_update`, and splitting the source (B) misses future re-sync sites. Kubernetes also dedupes in the writer but counts repeats; Hassette drops them without a count, for a known reason: counting means updating an earlier row, which breaks the append-only table and needs row ids the fire-and-forget writer doesn't have, and the count couldn't tell a re-sync from a real repeat anyway.
**Pick B instead if** every repeated failure must be visible even with no transition between. **Pick C instead if** duplicate rows are acceptable and you want zero writer state. **Pick D instead if** knowing "failed N times identically" from the table alone is worth giving up the append-only table.
**Reversibility:** easy
**Ratified:** Chose a writer-side skip of a row identical (`to_status`, `details`) to the last one written for that app and instance, held on `SessionManager`, created empty with the session, advanced only on a successful enqueue and evicted on a failed enqueue or missing session, over splitting site 198, writing every event, or Kubernetes-style repeat counts, so rows record changes rather than cache re-syncs, a drop never hides a later row, and the table stays append-only for #1446's projector, accepting that two identical failures with no event between read as one row with no count and that a re-sync right after a drop writes one duplicate.

### D3: Where are block and unblock changes diffed?

**Situation:** `reconcile_blocked_apps` (`core/app_lifecycle_config.py:141`) computes `previously_blocked` (from `registry.unblock_apps`, which clears the set) and `currently_blocked` as locals, returns only the unblocked difference, and discards the newly blocked one. The issue body asked where the prior state lives. It already lives here, as a local. `BlockReason` has one member, `ONLY_APP`. The function is sync, and it's called from bootstrap (`app_lifecycle_service.py:213`), from change handling, and from pre-release replay.

**Deciding factor:** no new state, every `blocked` row gets a closing row, and a removed app never reads as "unblocked".

| | A: diff and write inside `reconcile_blocked_apps` | B: keep the last-reconciled set on the registry | C: return both sets; callers write |
|---|---|---|---|
| New state | None | A field to keep in sync | None |
| Call sites changed | None | None | 3 |
| Removed app while blocked | Excluded from `unblocked`; closed with a `removed` row instead | Same rule needed | Same rule needed at each caller |
| What peers do | The kubelet compares its last-known `Unschedulable` value with the current spec and emits `NodeSchedulable`/`NodeNotSchedulable` on change (`kubelet_node_status.go`); HA's recorder writes an empty state when an entity is removed | The kubelet keeps the previous value in a field | none found |

**Recommendation:** A. Write a `blocked` row per newly blocked app, an `unblocked` row per unblocked app still in `enabled_manifests`, and a `removed` row per app that left the blocked set because it left `enabled_manifests`. At bootstrap the prior set is empty, so each blocked app gets a `blocked` row at session start, which is correct for a per-session history.
**Peer divergence:** none. Diffing at the reconcile site matches the kubelet, and a distinct `removed` status matches HA's recorder recording removal rather than a return to normal.
**Pick B instead if** block state will be changed from more places than this function. **Pick C instead if** callers need the newly blocked set for something else.
**Reversibility:** easy
**Ratified:** Chose to diff and write inside `reconcile_blocked_apps`, intersecting unblocked apps with current `enabled_manifests` and closing a removed app's block with a `removed` row, over a stored set on the registry or returning both sets to callers, so no new state is added, every block has a closing row and a removed app never reads as unblocked, accepting a `blocked` row per blocked app at each session start and a third block status.

### D4: Which connection events write a row?

**Situation:** `OutageLog` tracks a *gap*, from `disconnected_at` until `record_connected`, inside an *episode* that stays open until a connection lasts `STABLE_CONNECTION_SECONDS` (120 s), so a flapping link is one episode. Episodes and flaps exist to pace log lines (spec 131 D11). `record_core_wait` runs on every recheck while HA's core isn't RUNNING. If Hassette starts while HA is starting, there's no `record_failure` at all, only core waits and then `record_connected`. During an HA restart the order is a failure, then core waits on the reconnected socket, then connected. Every attempt after the first goes through `handle_connection_failure` → `record_failure` (`core/websocket_service.py` ~323–371). A token rejection is a `record_failure` with `Disposition.PARK`. `OutageLog` is built in `WebsocketService.__init__` and rebuilt once at the top of `serve()` (`websocket_service.py:321`), which runs once per process. Parent D2 asks for an outage that starts during startup, with the outage's length in the row, and counted per-flap pairs against bus events.

**Deciding factor:** every connection change is visible with the outage's length, in the shape peers store connection history, with no open-interval bookkeeping that needs close rules.

| | A: per gap, core-wait row only with no gap open (flag) | B: per episode | C: per gap, no core-wait rows | D: one row per connection-state change |
|---|---|---|---|---|
| Rows written | `disconnected` on a gap's first failure; `waiting_for_core` on the first core wait when no gap is open; `connected` when a gap or core wait closes; `parked` on PARK | `disconnected` at episode start; `connected` once stable, with episode length | A without `waiting_for_core` | A row whenever the state differs from the last one `OutageLog` wrote: `disconnected`, `waiting_for_core`, `connected`, `parked` (fields per D5). The first connection of the process writes `connected` with no outage length |
| Hassette starts while HA is starting | Recorded | Recorded, if core waits open it | Missed | Recorded |
| HA restart shows the core wait | No (a gap is already open) | No | No | Yes: `disconnected` → `waiting_for_core` → `connected` |
| Healthy session | No rows | No rows | No rows | One `connected` row at first connect |
| Flapping link | One pair per flap, flagged from `gap_after_flap` | One pair | One pair per flap | One pair per flap; the `disconnected` row is flagged from `gap_after_flap` |
| New `OutageLog` state | A "core wait open" flag and its start, with close rules for failure, connect, abort and rebuild; two intervals can overlap | An episode-close point, which doesn't exist yet | None | The last state written and the outage start; no interval can be left without a close rule |
| Growth | About 2 rows a minute for a flap every minute | Lowest | Same as A | Same as A, plus one row per HA restart and one per session: a flap every minute is about 86,000 rows, roughly 15–20 MB, over 30 days, under parent D12's 25 MB crash-loop figure |
| What peers do | Tracks intervals, which no surveyed peer stores | none found | Partial | Gatus inserts an event only when health flips, plus a `START` event the first time (`storage/store/sql/sql.go`); Uptime Kuma marks status-change heartbeats `important`; HA's recorder writes a row per state change, including the initial one; Kubernetes keeps `lastTransitionTime` apart from heartbeats. A separate "not ready yet" state exists in HA (`SETUP_RETRY`), Uptime Kuma (`PENDING`) and Kubernetes (`Ready=Unknown`) |

**Recommendation:** D. Rechecks and repeated failures in the same state write nothing, so no open interval needs a close rule, and the core wait during an HA restart is recorded. The last-written state starts empty when `OutageLog` is built, so the first connection writes `connected`. The outage length on `connected` is measured from the first non-`connected` row since the last `connected`. A session ending mid-outage leaves its last row as the last known state; whether it was still true is the reader's call (#4084), per parent D2.
**Peer divergence:** row-per-change, the initial row and the "waiting for core" state match Gatus, Uptime Kuma, HA and Kubernetes. Two divergences, both for known reasons. Peers derive the outage length at read time (Uptime Kuma), while Hassette stores it, because parent D2 asks for it in the row and a stored length survives a dropped `disconnected` row. No peer has a flap marker; it carries spec 131 D11's flap concept so a reader can tell a flapping link from separate outages.
**Pick A instead if** you want rows only at gap boundaries and accept close rules for a second interval. **Pick B instead if** you'd build an episode-close point to keep flapping links to two rows. **Pick C instead if** startup while HA is starting doesn't matter to you.
**Reversibility:** easy (connection statuses aren't constrained by `CHECK`)
**Ratified:** Chose one row per connection-state change (`disconnected`, `waiting_for_core`, `connected` with outage length, `parked`), including a `connected` row at the first connection, with the flap flag on the `disconnected` row, over per-gap rows with a core-wait flag, per-episode rows, or no core-wait rows, to match how Gatus, Uptime Kuma, HA's recorder and Kubernetes store connection history with no open-interval close rules, accepting one row per session start, one extra row per HA restart, and a pair of rows per flap.

### D5: What columns does the table have?

**Situation:** parent D1 fixes one table in #1446's `app_status_events` shape, generalized by a `kind` column and keyed by session id and instance name. Spec 132 D2 names no columns, so the column list is open. Parent D2 lists "kind, session id, subject (app and instance name, or none), from and to status, a short detail (such as outage length), and a timestamp". Each kind has its own extras: app rows an exception type and a needs-restart flag; connection rows a cause, a core state, a flap flag and an outage length; block rows a reason. #4084 filters by time window, app and kind, and displays the extras without filtering on them. Migrations here use `REAL` epoch timestamps and `CHECK (x IN (...))` for enum-like columns (`025.sql`); no table has a JSON column yet (the closest are the `args_json`/`kwargs_json` text columns).

**Deciding factor:** each kind's extras are typed fields the reader never parses out of a string, the filtered columns stay plain SQL, and #1446's swap touches only the writer.

| | A: kind per source, typed `needs_restart`/`duration_s` plus a text `detail` | B: kind per transition | C: kind per source, everything extra in a text `detail` | E: kind per source, typed core plus one JSON `details` validated by a per-kind model |
|---|---|---|---|---|
| Columns | Core (below) plus `needs_restart INTEGER NULL`, `duration_s REAL NULL`, `detail TEXT` | `kind` like `app_failed`, `connection_lost`, `blocked`; no from/to | Core plus `detail TEXT` | Core plus `details TEXT NOT NULL` (JSON object) |
| Per-kind extras | Two mostly-NULL columns; `detail` holds cause, exception type, core state, block reason or a flap flag | Same as A | One string holding all of them | Each kind's named fields |
| Reader parses strings | Yes, for `detail` | Yes | Yes | No; the per-kind model gives typed access |
| Filtering on an extra in SQL | Plain SQL for two of them | Same as A | Not practical | `json_extract`; #4084 doesn't need it |
| Adding a field | Migration | Migration | No migration | No migration |
| #1446 swap | Projector writes `kind='app'` rows | Projector must emit the transition vocabulary | Same as A | Same as A |
| Repo precedent | Matches the typed tables | Matches | Matches | First JSON column |
| What peers do | none found | none found | Airflow `log.extra` (text) | Prefect `flow_run_state`: typed `type`/`name`/`timestamp`/`message` plus JSON `state_details` validated by a Pydantic model; HA `states`: typed core plus JSON attributes; Airflow `log`: typed core plus `extra` |

Core columns, shared by A, C and E: `id`, `session_id NOT NULL REFERENCES sessions(id)`, `kind CHECK IN ('app','connection','block')`, `app_key`, `instance_name`, `from_status`, `to_status`, `ts REAL NOT NULL`; indexes on `(ts)`, `(app_key, ts)` and `(session_id)`.

**Recommendation:** E. Per kind:
- **App rows:** `app_key` and `instance_name` set; `to_status` is the event's `ResourceStatus`; `from_status` is the event's `previous_status` only (what the sender knew), NULL when the sender didn't set it (sites 198, 208, 399, 466), never the D2 map. `details`: exception type, and `needs_restart` on FAILED rows, read from `AppRegistry.get_needs_restart` when the row is written.
- **Connection rows:** `app_key` and `instance_name` NULL; `to_status` is the new state and `from_status` the state `OutageLog` last wrote (NULL on the first row). `details`: cause on `disconnected` and `parked`, core state on `waiting_for_core`, flap flag on `disconnected`, outage length in seconds on `connected` (absent on the first connection).
- **Block rows:** `app_key` set, `instance_name` NULL; `to_status` is `blocked`, `unblocked` or `removed` (D3), `from_status` NULL. `details`: the block reason.

The writer builds `details` from the kind's model and stores it serialized; the models are the only place its keys are defined.
**Peer divergence:** the typed-core-plus-JSON-details shape matches Prefect, HA and Airflow. One divergence, for a known reason: no peer state table has a `from_status` column (HA links to the previous row, Prefect relies on order); Hassette keeps it because parent D2 lists from and to status, and for app rows it records what the sender knew, which can differ from the previous row when a transition sent no event.
**Pick A instead if** you want every extra queryable in plain SQL and would rather not set a JSON-column precedent. **Pick B instead if** you expect queries by transition name rather than by subject. **Pick C instead if** parent D2's single "short detail" was meant literally.
**Reversibility:** hard (schema; a later migration can still add or drop columns)
**Ratified:** Chose a per-source `kind` with typed core columns (session, subject, from/to status, timestamp) and one JSON `details` column validated by a per-kind Pydantic model, with app `from_status` taken only from the event's `previous_status`, over typed extra columns with a text `detail`, per-transition kinds, or one text `detail`, to match how Prefect, HA and Airflow store per-type extras and keep the reader from parsing strings, accepting the repo's first JSON column, `json_extract` for any SQL filter on an extra, and NULL `from_status` where the sender didn't set it.

### D6: How does `OutageLog` reach the writer?

**Situation:** `OutageLog` is a dataclass holding a logger and a URL, with no `hassette` reference. It records monotonic times only. It's built in `WebsocketService.__init__` (line 162) and rebuilt at the top of `serve()` (line 321). Its unit tests construct it directly.

**Deciding factor:** the state comparison and gap and flap logic stay in one place, and `OutageLog` stays testable without a `Hassette`.

| | A: a row-writing callable passed in at both construction sites, no-op default | B: `WebsocketService` writes rows after each `OutageLog` call | C: `OutageLog` takes a `hassette` reference |
|---|---|---|---|
| Where state and flap logic lives | `OutageLog` only | Duplicated, or `OutageLog` returns what happened | `OutageLog` only |
| Unit tests | Pass a recording callable | Need a `WebsocketService` | Need a `Hassette` |
| Wall-clock time | Callable stamps `time.time()`; lengths come from the monotonic difference | Same | Same |
| What peers do | tenacity's `before`/`after`/`before_sleep` callables default to no-ops; NetDaemon exposes `OnConnect`/`OnDisconnect` observables | none found | none found |

**Recommendation:** A, because the gap and flap facts already live in `OutageLog`, and the last-written state D4 adds belongs beside them.
**Peer divergence:** none. A passed-in callable with a no-op default is tenacity's pattern; no surveyed peer persists reconnect history at all.
**Pick B instead if** you want `OutageLog` to stay a pure logging helper. **Pick C instead if** it will need more of Hassette soon.
**Reversibility:** easy
**Ratified:** Chose a row-writing callable passed into `OutageLog` at both construction sites with a no-op default, over writing rows from `WebsocketService` or giving `OutageLog` a `hassette` reference, so the state and flap logic stays in one place and `OutageLog` stays testable alone, accepting one more constructor argument.

### D7: Does a session store its heartbeat interval?

**Situation:** parent D2 says an unclean end's time is the session's last heartbeat, and the read says the crash came up to one heartbeat interval later. The interval is `DatabaseConfig.heartbeat_interval_seconds` (default 30). `sessions` doesn't store it, so #4084 can quote only the value configured now, which may differ from the one the crashed session ran with.

**Deciding factor:** don't add a column for a rarely changed setting.

| | A: don't store it | B: a `REAL` column on `sessions`, written at `create_session` |
|---|---|---|
| Accuracy of "up to one interval later" | Correct unless the setting changed since the crash | Always correct |
| Schema cost | None | One column in this PR's migration |
| Read side (#4084) | Quotes the current value and says so | Reads it per session |
| What peers do | Airflow's `job` table stores `latest_heartbeat` but not the rate, and `is_alive` reads current config; HA's `recorder_runs` stores no interval | A Kubernetes Lease stores `leaseDurationSeconds`, because a different process reads it |

**Recommendation:** A, don't store it; #4084 quotes the current value and says so.
**Peer divergence:** none. Matches Airflow and HA; Kubernetes stores it only because another process reads the lease, which doesn't apply here.
**Pick B instead if** you change the heartbeat interval often enough that the quoted value would mislead.
**Reversibility:** easy
**Ratified:** Chose not to store the heartbeat interval per session, over a column on `sessions`, to add no schema for a rarely changed setting, accepting that #4084 quotes the current value, which can differ from the one a crashed session ran with.

## Assumed

- **Parent D1 holds:** one append-only lifecycle table in #1446's shape, with the app-row writer replaced by #1446's projector later. Evidence: parent D1; #1446 is still open.
- **Parent D11 holds:** writers go through `SessionManager`. Nothing is a listener on Hassette's own bus. Evidence: parent D11; `core/core.py` `before_shutdown` removes root bus listeners.
- **Parent D12 holds:** the table is its own `RetentionTarget` on `database.retention_days`, failsafe-exempt, and in the session delete guard. Like every other session child table, `session_id` has no `ON DELETE` clause, so the guard line is the only thing protecting the session delete; a case in `tests/integration/database/test_session_retention.py` pins it, as for the others. HA's recorder likewise purges children explicitly rather than cascading. Evidence: parent D12; spec 132 D25; `core/retention_targets.py` already orders targets as D12 states; `core/database_retention.py` ~385–394; `migrations_sql/001.sql`, `005.sql`, `009.sql`, `024.sql` (no session FK cascades).
- **Parent D2's "no claim about what was up" and session boundaries** are read-side and belong to #4084. Session starts and ends are not copied into this table. Evidence: parent D2.
- **A session id exists before any writer can run:** `mark_orphaned_sessions` and `create_session` run right after the database starts and before other services. Evidence: `core/core.py` ~390.
- **Rows written while apps stop at shutdown are queued before the database detaches, but the drain is bounded:** `AppHandler` stops before the foundation stage, and `DatabaseService` drains its write queue on the way down within `SHUTDOWN_DRAIN_TIMEOUT_SECONDS` (5 s, clamped to the shutdown deadline). On timeout it abandons the remaining writes with a WARNING, so the final rows can be lost on a slow drain (accepted in D1). Peers bound it the same way: HA's final-write stage at 60 s with a WARNING, OTel's span processor at 30 s. Evidence: `core/database_service.py` ~346–367; `core/database_write_queue.py` ~150–182; `config/models.py:43`.
- **Rows abandoned by the drain can't be counted:** OTel counts post-shutdown drops as `already_shutdown`, but here the session record, the only place counters outlive the process, is written by `_finalize_session` before the database drains, and lifecycle counters live only in memory. The drain's WARNING is the durable record. Evidence: `core/core.py` `_run_foundation_stage` (~585–606) and `_finalize_session` (~657–676).
- **`enqueue` is the write path for fire-and-forget rows:** it returns `False` on a full queue and raises `RuntimeError` when the queue isn't live. Evidence: `ApiWriteRecorder.enqueue` (`core/api_write_recorder.py` ~201–212).
- **Needs-restart can be read when the FAILED row is written:** `settle_*` sets it before the outcome event is sent, and it survives `unregister_app`; at shutdown every outcome event is sent before `registry.clear_all()`. Evidence: `core/app_registry.py:150`; `core/app_lifecycle_instances.py` ~478–493.

## Build

- [ ] Implementation and tests committed
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**
