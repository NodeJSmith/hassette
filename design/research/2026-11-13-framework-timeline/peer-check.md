# Research Brief: Peer check for lifecycle history writers

**Date:** 2026-11-13
**For:** `design/specs/152-lifecycle-history-writers/design.md` (#3678), decisions D1–D7, the writer's drop counting, and the shutdown drain.

**Bottom line:** no decision contradicts what peers commonly do without giving a reason. Two places pick a different mechanism from peers and the ledger explains why: D1 differs from HA's recorder, and D2 dedupes in the writer. Three smaller gaps were never weighed against what peers do: D2 drops identical repeats without a count, D5 never considered a JSON details column, and rows lost in the shutdown drain aren't counted.

Searched with `exa-search`. Raw source was read for HA (`recorder/db_schema.py`, `config_entries.py`), Airflow (`jobs/job.py`), Prefect (`orm_models.py`, `models/events.py`), client-go (`tools/record/event.go`, `events_cache.go`), Uptime Kuma (`db/knex_init_db.js`, `server/model/monitor.js`) and the K8s Lease types (`coordination/v1/types.go`).

## Summary

| Decision | Ratified choice | What peers do | Verdict | Reason, if it diverges |
|---|---|---|---|---|
| D1: how app rows reach the writer | One funnel writes the row, then sends the event; a test bans other sends | Prefect: one funnel (`set_flow_run_state`) writes the state row, and a rule inside it emits the event. Airflow 3: a direct call at each transition endpoint; sites were missed twice (PRs 61932, 59639). HA recorder: a `MATCH_ALL` bus listener | Match (Prefect, Airflow); differs from HA | Explained. HA's listener runs synchronously and HA has a dedicated final-write shutdown stage. Hassette's bus buffers events and removes listeners at shutdown (D1, parent D11, `bus_service.py:759`) |
| D2: duplicate status | Writer skips a row identical to the last one for that app and instance; no count kept | HA, Airflow and Prefect dedupe at the source and the writer records whatever arrives. K8s dedupes in the writer but increments `count`/`lastTimestamp` instead of dropping | Diverge | Where the dedupe sits is explained (site 198 re-syncs on purpose). Silently dropping a genuine identical repeat was never weighed against K8s's count |
| D3: block diff | Diff locals inside `reconcile_blocked_apps`; `blocked`/`unblocked`/`removed` rows | The kubelet compares last-known `Unschedulable` with current and emits `NodeSchedulable`/`NodeNotSchedulable`. Airflow writes pause/unpause audit rows. HA writes a `state=""` row when an entity is removed | Match | — |
| D4: connection rows | One row per state change, including `waiting_for_core`; `flap` marker; outage length on `connected` | Gatus writes an event only when health flips, no duration. Uptime Kuma marks transitions `important` and works out downtime at read time. A separate "not ready yet" state exists in HA (`SETUP_RETRY`), Uptime Kuma (`PENDING`) and K8s (`Ready=Unknown`) | Match on row-per-change; Partial on storing the length | Stored length: parent D2 asks for it, and a stored length survives a dropped `disconnected` row. Flap marker: no peer has one; it comes from spec 131 D11 |
| D5: columns | `kind` per source, `from_status`/`to_status`, typed nullable `needs_restart`/`duration_s`, text `detail` | No peer state table has a "from" column: HA links to the previous row (`old_state_id`), Prefect relies on order, K8s Events have none. Prefect's event payload carries `intended.from/to` in JSON. Peers keep extras in JSON (Prefect `state_details`/`data`, Airflow `log.extra`, HA's shared attributes table) | Partial | `from_status` comes from parent D2's column list. A JSON details column was never among the options |
| D6: OutageLog hook | Passed-in row-writing callable, no-op default | tenacity's `before`/`after`/`before_sleep` callables default to no-ops. NetDaemon exposes `OnConnect`/`OnDisconnect` observables | Match (general pattern) | — |
| D7: heartbeat interval | Not stored | Airflow's `job` stores `latest_heartbeat` but not the rate; `is_alive` reads current config. HA's `recorder_runs` stores no interval. A K8s Lease stores `leaseDurationSeconds` because another process reads it | Match | — |
| Drops and counting | One `PipelineCounter` for full, not-live and no-session drops, plus one paced WARNING per episode | OTel semconv: a counter with `error.type=queue_full` and `already_shutdown`. client-go logs an ERROR per drop, no counter. HA's recorder stops recording on overflow with one ERROR | Match (OTel); stricter than K8s and HA | Rows abandoned by the shutdown drain are logged, not counted; OTel counts them as `already_shutdown` |
| Shutdown drain | Bounded at `SHUTDOWN_DRAIN_TIMEOUT_SECONDS` (5 s, clamped), then abandon with a WARNING | HA's final-write stage is bounded at 60 s with a WARNING on timeout. OTel Python span processor shutdown bounded at 30 s. client-go doesn't drain | Match | 5 s is shorter than peers; an existing constant this ledger didn't choose |

## Evidence

### D1
- Prefect: `set_flow_run_state` writes `flow_run_state` once orchestration rules accept it (https://github.com/PrefectHQ/prefect/blob/d6d16486/src/prefect/server/models/flow_runs.py); the event comes from `InstrumentFlowRunStateTransitions` inside the same funnel; payload built in `src/prefect/server/models/events.py:42-84`.
- Airflow 3: state written directly in `ti_run`/`ti_update_state`. Audit rows disappeared when logic moved out of model methods, restored by https://github.com/apache/airflow/pull/61932; a scheduler reset path missing `task_instance_history` was fixed in https://github.com/apache/airflow/pull/59639. No structural guard.
- HA recorder: `hass.bus.async_listen(MATCH_ALL, _event_listener)`, a synchronous `@callback` that enqueues directly (https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/core.py).

### D2
- HA: the state machine fires no event when state and attributes are unchanged unless `force_update`; the recorder writes every `state_changed` it receives (https://github.com/home-assistant/core/issues/111582).
- Airflow: `ti_update_state` treats "already in the requested state" as a no-op (https://github.com/apache/airflow/pull/64023); `ti_run` writes its audit row only in the `else` branch (PR 61932).
- Prefect accepts and writes RUNNING→RUNNING (https://github.com/PrefectHQ/prefect/pull/9447); duplicate Late→Late was fixed at the producer (https://github.com/PrefectHQ/prefect/pull/22316).
- K8s: key is source, involved object, type, reason, message (`getEventKey`, `client-go/tools/record/events_cache.go:52-67`); a repeat patches `Count`/`LastTimestamp` (`eventObserve`, lines 327-352), across a 4096-entry cache.

### D3
- Kubelet: `lastNodeUnschedulable` compared with spec, `recordNodeSchedulableEvent` (https://github.com/kubernetes/kubernetes/blob/63b36867/pkg/kubelet/kubelet_node_status.go).
- Airflow pause/unpause audit rows via `action_logging` (https://github.com/apache/airflow/pull/55091).
- HA config entries keep no history (`config_entries.py` ~1270); recorder writes `state=""` on removal ("None state means the state was removed", `recorder/db_schema.py:478-486`).

### D4
- Gatus: event only on health flip, no duration (https://github.com/TwiN/gatus/blob/master/storage/store/sql/sql.go).
- Uptime Kuma: `isImportantBeat` (`monitor.js:1438-1463`); UP→PENDING not important; downtime computed at read time (`monitor.js` ~1534-1555; PR 6894); `heartbeat.duration` is time since previous beat (`knex_init_db.js:141`).
- "Not ready yet" states: HA `SETUP_RETRY`, Uptime Kuma `PENDING`, K8s `Ready=Unknown` (https://kubernetes.io/docs/reference/node/node-status/).

### D5
- HA `states`: `state`, `old_state_id`, timestamps, `attributes_id`, context ids (`db_schema.py`).
- Prefect `flow_run_state`: `type`, `name`, `timestamp`, `message`, `state_details` JSON, `data` JSON, no "from" (`orm_models.py:161-181`); events carry `intended: {from, to}` (`models/events.py:72-79`).
- K8s Event: type, reason, message, count, timestamps, involved object, source. Airflow `log`: event, timestamp, ids, `extra`.

### D6, D7
- tenacity: https://github.com/jd/tenacity/blob/main/tenacity/before_sleep.py, `after.py`; NetDaemon commit 80d8bf8.
- Airflow `jobs/job.py` columns lines 95-110, `health_check_threshold`/`heartrate` from current config lines 72-83, 177-187. HA `recorder_runs` `db_schema.py:798-809`. K8s Lease `types.go:64`.

### Drops and shutdown
- OTel semconv: https://opentelemetry.io/docs/specs/semconv/otel/sdk-metrics/ (`queue_full`, `already_shutdown`).
- client-go: `event.go:468-477` ERROR per drop; up to 12 sink retries; `Shutdown()` cancels without draining (`event.go:289-325`).
- HA recorder `_async_check_queue` stops recording on backlog overflow; `FINAL_WRITE_STAGE_SHUTDOWN_TIMEOUT = 60` (`homeassistant/core.py`), WARNING on timeout (https://github.com/home-assistant/core/issues/147200).
- OTel Python shutdown bound: https://github.com/open-telemetry/opentelemetry-python/pull/4638.
- Hassette `SHUTDOWN_DRAIN_TIMEOUT_SECONDS = 5` (`src/hassette/config/models.py:43`).

## Divergences the ledger doesn't explain
1. D2: a genuine identical repeat is dropped with no count, where K8s keeps one.
2. D5: a JSON details column was never evaluated, though Prefect, Airflow and HA keep extras in JSON.
3. Shutdown drain: rows lost to a drain timeout are warned but not counted; OTel counts them as `already_shutdown`.
4. D4/D5 (minor): storing the outage length is justified only by parent D2; surviving a dropped `disconnected` row is a stronger reason.

## Not found
- A peer reconnect helper that persists history through a passed-in callback.
- A peer "flap" marker.
- Whether HA writes a fresh `states` row per entity at each startup.
- How AppDaemon records disabled apps.
