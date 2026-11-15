# Design: Lifecycle history writers

**Date:** 2026-11-13 (re-sketched 2026-11-15 after #4091 and #4092 merged)
**Status:** built
**Mode:** sketch
**Issues:** #3678
**Parent:** design/specs/142-diagnostic-evidence/design.md
**Prior art:** design/research/2026-11-13-framework-timeline/peer-check.md; design/specs/153-connection-state-owner/peer-check.md

## Summary

Connection and app lifecycle history lives only in memory and in logs today, so "what happened around 05:00" can't be answered after the fact. This change adds one append-only lifecycle table and its three writers: app status rows from each `StatusChange` the registry applies, connection rows from each `ConnectionState` transition, and block rows (`blocked`, `unblocked`, `removed`) from block reconciliation. It implements parent D1 and D12 and parts of parent D2 and D11. It supersedes these parent clauses, each at the decision named: parent D2's "app rows come from one subscriber" and D11's "an app state subscriber" (D1: a call in `set_app_status`); parent D2's "connection rows from `OutageLog`'s failure and recovery points" (D4: rows per `ConnectionState` transition) and D11's "called directly by `OutageLog`" (D6: a call in `set_connection_state`); parent D2's single "short detail" (D5: a typed JSON `details` per kind) and its outage-length example (D8: derived at read time); parent D2's needs-restart flag "read from the registry when the event is handled" (D5: read from `StatusChange.needs_restart`, which carries the same flag). Reading the table (`hassette timeline`, the merged API route, sessions query, loss count, and the derived outage length and flap marker from D8) is #4084 and is out of scope. So is the web UI.

The two prerequisites have landed. #4148 (spec 154) made `AppRegistry.set_status` the only writer of app instance status: it returns a `StatusChange` with the real previous status, or `None` when the write isn't a change, and `AppInstanceLifecycleMixin.set_app_status` is its only caller. #4102 (spec 153) made `WebsocketService.set_connection_state` the only writer of connection state and added `WAITING_FOR_CORE`. Spec 153 D10 left the transition-observer seam to this sketch, with its D2–D5 as input. Both owners now know what changed, so neither writer here keeps any memory of what it last wrote.

Research: `design/research/2026-11-13-framework-timeline/research.md` (Q1–Q4, Q8, PR 1 of its split), `design/research/2026-11-13-framework-timeline/peer-check.md` (each decision against peers), `design/research/2026-11-13-framework-timeline/structural-gaps.md` (why the prerequisites came first), and `design/specs/153-connection-state-owner/peer-check.md` (observer mechanics). The parent's brief, `design/research/2026-11-01-diagnostic-evidence/prior-art.md`, covers the milestone as a whole.

New pieces and their homes:

- **Lifecycle table:** `lifecycle_events`, created in `src/hassette/migrations_sql/026.sql` (columns per D5).
- **Per-kind details models:** one small Pydantic model per row kind for the `details` JSON (D5), next to the repository insert in `src/hassette/core/telemetry/`.
- **Retention:** a new `RetentionTarget` for `lifecycle_events` on its `ts` column in `src/hassette/core/retention_targets.py`, on `database.retention_days`, `failsafe_exempt=True`. A `NOT EXISTS` line for the table goes in the session delete guard in `src/hassette/core/database_retention.py` (parent D12).
- **The one writer:** a sync, enqueue-based `SessionManager` method in `src/hassette/core/session_manager.py`, plus the repository insert. It never awaits, so sync callers (block reconciliation, the recv-task done-callback) can call it. It checks for a session before building the insert and stamps the wall-clock time itself, since every caller calls it at the moment of change. Its drop and failure handling is the Posture's failure-handling stance. Its counter is one new `PipelineCounter` member, `LIFECYCLE_ROWS_DROPPED = ("lifecycle_row", "dropped", CounterKind.LOSS)` beside `API_WRITE_RECORD_DROPPED`, in `src/hassette/core/pipeline_counters.py`, covering every row that never reached the queue whatever the cause. Its WARNING is paced like `ApiWriteRecorder.warn_drop` (`src/hassette/core/api_write_recorder.py`), worded neutrally ("could not queue lifecycle row"); the writer keeps its own pacing state, so an API-write drop never suppresses a lifecycle WARNING, and whether the pacing code is shared is left to the build. Owners don't call it through the `hassette.session_manager` accessor, which raises when services aren't wired (`src/hassette/core/hassette_accessors.py`): they call one module-level function next to the repository insert in `src/hassette/core/telemetry/`, taking the owner's `hassette` and the row's fields, which looks up the session manager and calls the writer inside the guard (counting a failed lookup on `hassette.pipeline_counters`), so the lookup is covered by the never-raise rule too. This puts one function between the owners and parent D11's `SessionManager` method.
- **App rows:** one writer call in `AppInstanceLifecycleMixin.set_app_status` (`src/hassette/core/app_lifecycle_instances.py`), per D1 and D2.
- **Connection rows:** one writer call in `WebsocketService.set_connection_state` (`src/hassette/core/websocket_service.py`), which gains an optional `detail` argument, per D4 and D6.
- **Block rows:** written inside `reconcile_blocked_apps` (`src/hassette/core/app_lifecycle_config.py`), per D3.
- **Seeds and docs:** lifecycle rows in `scripts/seed_scenarios/` (`base.py` plus `healthy.py` and `lifecycle.py` at least), and the table, its retention and its best-effort contract on `docs/pages/core-concepts/database-telemetry.md`.

The PR body names every lifecycle transition that writes no row (parent D2): an app instance a runtime start registers after `shutdown_all` took its list, which `clear_all` removes with no event (spec 154's accepted limitation), and a core-state change during the core wait, which is not a connection transition (spec 153 D6).

## Posture

- **Failure handling:** best-effort. Every row dropped before it is queued is counted under one new `PipelineCounter` member and logged once per episode at WARNING. The drop paths are: not queued (`enqueue` returned False: a full queue, or yielding to a waiting `submit()`, which `enqueue` also counts under `DB_WRITE_QUEUE_YIELDED_TO_SUBMIT`), queue not live (`enqueue` raised `RuntimeError`, which unlike `ApiWriteRecorder.enqueue` is counted, not only logged at DEBUG), and no session. The writer never raises: the session check, details-model build, serialization and enqueue sit in one `except Exception` that logs with the traceback under the same pacer and counts under the same member, so no failure of its own escapes into a status owner (OpenTelemetry's rule that instrumentation must not throw unhandled exceptions at run time). A row that fails after being queued is logged at ERROR by the write worker and not counted, as for `ApiWriteRecorder`. Nothing is retried, and no drop affects the lifecycle path that wrote it (parent posture). Lifecycle rows share `DatabaseService`'s one bounded write queue with logs, API writes and execution batches, so drops cluster around the bursts the table records; that is accepted, with no separate queue, as HA, OTel and client-go each use one bounded queue. Readers find gaps by D8's reading contract, not by the in-memory counter.
- **Compatibility:** clean break, since the project is pre-V1. The new table starts empty with no backfill. `set_connection_state` gains a keyword argument. No wire changes in this PR.
- **Scope:** writers and the table only. The read path is #4084. Docs cover only the telemetry database page.
- **Rollout:** ships outright, no flag. Migration `026.sql`.
- **Hardening:** project defaults. Parent D12's growth estimate for one crash-looping app is the reference figure; D4 states the connection-row figure, including the worst case at the reconnect backoff cap.
- **Altitude:** `build`; one session builds it.

## Decisions

### D1: Where do app status rows get written? (supersedes parent D2's and D11's app state subscriber)

**Situation:** `AppInstanceLifecycleMixin.set_app_status` (`app_lifecycle_instances.py:165-195`) is the one path every app status write takes. It calls `AppRegistry.set_status`, which returns a `StatusChange` (`app_registry.py:69-83`) or `None`, then sends `HassetteAppStateEvent.from_change(change)` and only logs a send failure. It is `set_status`'s only caller, a rule the `src/hassette/core/REVIEW.md` question on status writes guards. Parent D11 rules out a listener on Hassette's own bus, because `before_shutdown` removes those listeners before apps stop. `BusService.serve` (`core/bus_service.py`, with `close_event_streams`) also leaves its loop on shutdown without draining buffered events, so the last app's STOPPED can reach no listener (#4093, open). Parent D2 wanted rows "from one subscriber" so a new lifecycle path is covered automatically.

**Deciding factor:** every status change writes a row, including at shutdown and when the event send fails, with no new layer.

| | A: writer call in `set_app_status`, before the send | B: listener on Hassette's bus | C: `AppRegistry.set_status` calls the writer |
|---|---|---|---|
| Last app's STOPPED at shutdown | Queued (lost only if the drain times out) | Can be lost (bus drain, #4093; listeners removed first) | Queued |
| Event send fails | Row still written | No row | Row still written |
| New lifecycle path covered | Yes: every status write already goes through `set_app_status` | Yes | Yes |
| Layers added | One call | Listener, dispatch, executor | One call, but in the registry |
| Coupling | Lifecycle mixin already holds `hassette` | Writer decoupled; bus delivery and shutdown order become its concerns | Registry, today plain in-memory state with no `hassette` reference, gains a telemetry dependency |
| What peers do | Prefect: `set_flow_run_state` writes the state row and emits the event from inside one funnel | HA recorder: a synchronous `MATCH_ALL` bus listener | none found |

**Recommendation:** A. The single funnel already exists, so the writer is one call between `set_status` and the send. Writing before the send means a failed send can't cost the row. The single-caller rule on `set_status` is guarded by the existing `src/hassette/core/REVIEW.md` question.
**Peer divergence:** matches Prefect's funnel, and avoids Airflow 3's per-site calls, whose missed sites (PRs 61932, 59639) are the failure a funnel prevents. Diverges from HA's recorder (a bus listener), for a known reason: HA's listener runs synchronously and HA has a final-write shutdown stage, while Hassette's bus buffers events and removes listeners before apps stop (#4093).
**Pick B instead if** #4093 lands first and you want writers decoupled from the lifecycle. **Pick C instead if** you want the row written even by a hypothetical second caller of `set_status`.
**Reversibility:** easy (internal)
**Ratified:** Chose one writer call in `set_app_status` between `set_status` and the event send, over a bus listener or a writer call inside the registry, so every status change writes a row even at shutdown or when the send fails with no new layer, accepting that a second caller of `set_status` would bypass the row (guarded by the existing REVIEW.md question).

### D2: Does the writer skip repeated statuses?

**Situation:** nothing in the lifecycle re-sends a standing status any more: #4148 removed the start-time loop that re-sent every standing failure as a UI cache re-sync. `set_status` decides what is a change: a different status, or FAILED with a different error object (compared by identity) or a new needs-restart flag. A non-change returns `None` and sends nothing. So a repeated `start_app` of an app whose class fails construction writes FAILED → FAILED, each with a new exception object (`app_lifecycle_start_stop.py`, the construction-result loop), and each is a change.

**Deciding factor:** rows record exactly the changes the status owner applied, with no writer state.

| | A: write every `StatusChange` | B: keep a writer-side content map and skip a row identical to the last |
|---|---|---|
| Genuine repeat failure (new error object) | One row each | Collapsed into one row |
| Writer state | None | A map on `SessionManager`, with advance and evict rules |
| #1446's "one row per observed status change" | Already that | Stricter than #1446 |
| What peers do | Prefect keeps genuine repeats (RUNNING→RUNNING, PR 9447) and rejects only what its funnel's rules call duplicates. HA and Airflow dedupe at the source | Kubernetes dedupes identical events in the writer (`events_cache.go`) |

**Recommendation:** A. The thing the map existed for is gone, and the owner already decides what a change is.
**Peer divergence:** none. The owner decides inside the funnel, as Prefect's orchestration rules do inside `set_flow_run_state`.
**Pick B instead if** you expect a new re-send path that `set_status` would report as a change.
**Reversibility:** easy
**Ratified:** Chose to write every `StatusChange` with no writer-side dedupe, over a content map that skips identical rows, so rows record exactly the changes the registry applied with no writer state, accepting that a genuine repeat failure (new error object) writes a row each time.

### D3: Where are block and unblock changes diffed?

**Situation:** `reconcile_blocked_apps` (`core/app_lifecycle_config.py:141`) computes `previously_blocked` (from `registry.unblock_apps`, which clears the set) and `currently_blocked` as locals, returns only the unblocked difference, and discards the newly blocked one. The issue body asked where the prior state lives. It already lives here, as a local. `BlockReason` has one member, `ONLY_APP`. The function is sync, and it has two call sites: bootstrap (`app_lifecycle_service.py`, which ignores the return value) and change handling (`app_lifecycle_config.py`, which intersects the returned set with `enabled_manifests` before starting apps; pre-release replay reaches it through change handling).

**Deciding factor:** no new state, every `blocked` row gets a closing row, and a removed app never reads as "unblocked".

| | A: diff and write inside `reconcile_blocked_apps` | B: keep the last-reconciled set on the registry | C: return both sets; callers write |
|---|---|---|---|
| New state | None | A field to keep in sync | None |
| Call sites changed | None | None | 2 |
| Removed app while blocked | Excluded from `unblocked`; closed with a `removed` row instead | Same rule needed | Same rule needed at each caller |
| What peers do | The kubelet compares its last-known `Unschedulable` value with the current spec and emits `NodeSchedulable`/`NodeNotSchedulable` on change (`kubelet_node_status.go`); HA's recorder writes an empty state when an entity is removed | The kubelet keeps the previous value in a field | none found |

**Recommendation:** A. Write a `blocked` row per newly blocked app, an `unblocked` row per unblocked app still in `enabled_manifests`, and a `removed` row per app that left the blocked set because it left `enabled_manifests`. At bootstrap the prior set is empty, so each blocked app gets a `blocked` row at session start, which is correct for a per-session history. The function's return value is unchanged: it still returns every app that left the blocked set, removed ones included, and its caller's `enabled_manifests` intersection keeps removed apps out of the start list.
**Peer divergence:** none. Diffing at the reconcile site matches the kubelet, and a distinct `removed` status matches HA's recorder recording removal rather than a return to normal.
**Pick B instead if** block state will be changed from more places than this function. **Pick C instead if** callers need the newly blocked set for something else.
**Reversibility:** easy
**Ratified:** Chose to diff and write inside `reconcile_blocked_apps`, intersecting unblocked apps with current `enabled_manifests` and closing a removed app's block with a `removed` row, over a stored set on the registry or returning both sets to callers, so no new state is added, every block has a closing row and a removed app never reads as unblocked, accepting a `blocked` row per blocked app at each session start, a third block status, and that `removed` means "left the enabled config", so an app disabled in config while blocked also gets a `removed` row (as HA records disabling and deleting an entity the same way).

### D4: Which connection changes write a row? (supersedes parent D2's `OutageLog` connection source)

**Situation:** `ConnectionState` now has five members: DISCONNECTED, CONNECTING, WAITING_FOR_CORE, CONNECTED, AUTH_FAILED. `set_connection_state` ignores same-state calls, so failed attempts that stay in CONNECTING and core-wait rechecks produce no transition. The edges are in `WS_VALID_TRANSITIONS` (`websocket_service.py`). Typical sequences:
- **Healthy start:** DISCONNECTED → CONNECTING (top of `serve()`) → CONNECTED.
- **Start while HA is starting:** CONNECTING → WAITING_FOR_CORE → CONNECTED.
- **Drop by recv-task death** (the usual HA restart): CONNECTED → DISCONNECTED (done-callback, no cause, a close code) → CONNECTING (`handle_connection_failure`, with `plan.cause`) → WAITING_FOR_CORE → CONNECTED.
- **Drop found by a send failure:** CONNECTED → CONNECTING with the cause.
- **Token rejected:** CONNECTING → AUTH_FAILED (`park`), left only at shutdown.
- **Shutdown:** any state → DISCONNECTED (`cleanup`).

`OutageLog` doesn't track the five states and isn't a source for these rows.

**Deciding factor:** every connection change is visible with no second vocabulary and no writer state, in the shape peers store status history.

| | A: one row per `ConnectionState` transition | B: map states onto `connected`/`disconnected`/`waiting_for_core`/`parked`; write when the mapped value changes |
|---|---|---|
| Vocabulary | `ConnectionState`'s, which `hassette.types` exports | A second one, with a mapping to keep in step with the enum |
| Writer state | None | None (the mapping is a pure function of old and new) |
| Healthy session | 2 rows (CONNECTING, CONNECTED) | 1 row |
| Recv-death drop | 2 rows before reconnecting: DISCONNECTED with the close code, then CONNECTING with the cause | 1 row, without the cause (it arrives on the skipped DISCONNECTED → CONNECTING step) |
| Start while HA is starting | Recorded (WAITING_FOR_CORE row) | Recorded |
| Growth | Rows per flap: 3 (DISCONNECTED, CONNECTING, CONNECTED), or 4 when the reconnect waits on the core, as an HA restart does. A flap every minute at 4 rows: roughly 173,000 rows and 30 MB over 30 days. Worst case, a link dropping right after each connect at the 5 s backoff cap (`FAST_BACKOFF_CAP_SECONDS`): one flap about every 10 s, roughly 1,040,000 rows and 170–180 MB at 4 rows, bounded only by `retention_days` | About two thirds of A |
| What peers do | HA's recorder writes a row per state change, in the entity's own state vocabulary, including the initial one | Kubernetes conditions (`Ready` True/False/Unknown plus a reason), Gatus (health flips plus a `START` event) and Uptime Kuma (status-change heartbeats marked `important`) store a coarse status |

**Recommendation:** A. A row is exactly a transition of a state users can already see, so there's nothing to map or keep in step, and the cause lands on the row where the code knows it. The extra CONNECTING row per drop is cheap. The worst-case growth is accepted as a known limitation: the rows are the evidence for exactly that incident, nothing is lost silently, and retention bounds them.
**Peer divergence:** the row-per-change shape matches all four. Two divergences, for known reasons. Gatus, Uptime Kuma and Kubernetes store a coarse status; Hassette stores its own five states because they already exist and are public, and the coarse view is a read-side grouping #4084 can apply. Gatus and Uptime Kuma also record a monitored target's health, while this table records Hassette's own client link, which no surveyed peer persists; the kubelet's node conditions are the closest self-reporting peer. Gatus caps events per endpoint by count (`DefaultMaximumNumberOfEvents = 50`), while Hassette bounds rows by age only, like HA and Uptime Kuma.
**Pick B instead if** you want the table itself to read as up/down/waiting/parked, and accept losing the cause on recv-death drops.
**Reversibility:** easy (connection statuses aren't constrained by `CHECK`)
**Ratified:** Chose one row per `ConnectionState` transition in the enum's own vocabulary, over a coarse mapped status, so every change is visible with no mapping to keep in step and each detail lands where the code knows it, accepting two rows per healthy session, an extra row per drop, and worst-case growth of about 170–180 MB over 30 days at the backoff cap, bounded only by retention.

### D5: What columns does the table have? (supersedes parent D2's single short detail)

**Situation:** parent D1 fixes one table in #1446's `app_status_events` shape, generalized by a `kind` column and keyed by session id and instance name. Spec 132 D2 names no columns, so the column list is open. Parent D2 lists "kind, session id, subject (app and instance name, or none), from and to status, a short detail (such as outage length), and a timestamp". Each kind has its own extras: app rows an exception type and a needs-restart flag; connection rows a cause, a core state or a close code; block rows a reason. #4084 filters by time window, app and kind, and displays the extras without filtering on them. Migrations here use `REAL` epoch timestamps and `CHECK (x IN (...))` for enum-like columns (`025.sql`); no table has a JSON column yet (the closest are the `args_json`/`kwargs_json` text columns). Both status owners now hand the writer the real previous state: `StatusChange.previous` and `set_connection_state`'s `old`.

**Deciding factor:** each kind's extras are typed fields the reader never parses out of a string, the filtered columns stay plain SQL, each column has one meaning, and #1446's swap touches only the writer.

| | A: kind per source, typed `needs_restart`/`duration_s` plus a text `detail` | B: kind per transition | C: kind per source, everything extra in a text `detail` | D: kind per source, typed core plus one JSON `details` validated by a per-kind model |
|---|---|---|---|---|
| Columns | Core (below) plus `needs_restart INTEGER NULL`, `duration_s REAL NULL`, `detail TEXT` | `kind` like `app_failed`, `connection_lost`, `blocked`; no from/to | Core plus `detail TEXT` | Core plus `details TEXT NOT NULL` (JSON object) |
| Per-kind extras | Two mostly-NULL columns; `detail` holds cause, exception type, core state or block reason | Same as A | One string holding all of them | Each kind's named fields |
| Reader parses strings | Yes, for `detail` | Yes | Yes | No; the per-kind model gives typed access |
| Filtering on an extra in SQL | Plain SQL for two of them | Same as A | Not practical | `json_extract`; #4084 doesn't need it |
| Adding a field | Migration | Migration | No migration | No migration |
| #1446 swap | Projector writes `kind='app'` rows | Projector must emit the transition vocabulary | Same as A | Same as A |
| Repo precedent | Matches the typed tables | Matches | Matches | First JSON column |
| What peers do | none found | none found | Airflow `log.extra` (text) | Prefect `flow_run_state`: typed `type`/`name`/`timestamp`/`message` plus JSON `state_details` validated by a Pydantic model; HA `states`: typed core plus JSON attributes; Airflow `log`: typed core plus `extra` |

Core columns, shared by A, C and D: `id`, `session_id NOT NULL REFERENCES sessions(id)`, `kind CHECK IN ('app','connection','block')`, `app_key`, `instance_name`, `from_status`, `to_status`, `ts REAL NOT NULL`; indexes on `(ts)`, `(app_key, ts)` and `(session_id)`. `id` is the sequence key: order by `id` within a session (and per instance for app rows). `ts` is for display and time-window filtering only, since rows enter one FIFO queue synchronously at the moment of change (`database_write_queue.py` `put_nowait`, one worker), while wall-clock time can tie or step back (an RTC-less host stepping its clock by NTP after boot).

**Recommendation:** D. Per kind:
- **App rows:** `app_key` and `instance_name` set; `to_status` is `StatusChange.status` and `from_status` is `StatusChange.previous`, both `ResourceStatus` values and always set. `details`: the exception type on FAILED rows (from `change.error`), and the needs-restart reason and pending task names when `change.needs_restart` is set.
- **Connection rows:** `app_key` and `instance_name` NULL; `to_status` is the new `ConnectionState` and `from_status` the old one, always set. `details`: the cause on CONNECTING after a failure (`plan.cause`) and on AUTH_FAILED, the core state on WAITING_FOR_CORE, and the close code on DISCONNECTED from recv-task death. Each is absent where the code has none.
- **Block rows:** `app_key` set, `instance_name` NULL; `to_status` is `blocked`, `unblocked` or `removed` (D3), `from_status` NULL. `details`: the block reason.

`from_status` means one thing, the owner's previous state, and is NULL only on block rows, which have no owner state machine. The writer builds `details` from the kind's model and stores it serialized; the models are the only place its keys are defined. `details` carries no version key: models change only by adding optional fields, and readers tolerate missing keys within the retention window. The `kind` CHECK follows the repo's enum-column convention, so a fourth source (scheduler, session) is a table-rebuild migration, as `009.sql` did for `executions.status`.
**Peer divergence:** the typed-core-plus-JSON-details shape matches Prefect, HA and Airflow, and an unversioned details model matches all three. Two divergences, for known reasons. No peer state table has a `from_status` column (HA links to the previous row, Prefect relies on order); Hassette keeps it because parent D2 lists from and to status and both owners now supply the exact value, so it costs nothing and survives a dropped previous row. HA and Kubernetes leave their kind-like discriminator open; Hassette constrains it, following its own migrations, and accepts a rebuild per new kind on a small, retention-bounded table. HA's history and Prefect's state reads order by timestamp (`last_updated_ts`, `timestamp`); Hassette orders by `id`, because its single synchronous enqueue makes `id` the exact order and it survives a clock step.
**Pick A instead if** you want every extra queryable in plain SQL and would rather not set a JSON-column precedent. **Pick B instead if** you expect queries by transition name rather than by subject. **Pick C instead if** parent D2's single "short detail" was meant literally.
**Reversibility:** hard (schema; a later migration can still add or drop columns)
**Ratified:** Chose a per-source `kind` (CHECK-constrained) with typed core columns, `id` as the sequence key and `ts` for display and filtering only, and one unversioned JSON `details` column validated by a per-kind Pydantic model, with `from_status` as the owner's previous state (NULL only on block rows), over typed extra columns with a text `detail`, per-transition kinds, or one text `detail`, to match how Prefect, HA and Airflow store per-type extras and keep the reader from parsing strings, accepting the repo's first JSON column, `json_extract` for any SQL filter on an extra, additive-only `details` changes, a table rebuild for a fourth kind, and ordering by `id` where HA and Prefect order by timestamp.

### D6: How do connection rows reach the writer? (supersedes parent D11's `OutageLog` caller)

**Situation:** `set_connection_state(new)` (`websocket_service.py:228-268`) is synchronous and is the only writer of connection state. One caller, `_handle_recv_task_done`, is an `asyncio` done-callback and can't await. Each detail D5 stores is in scope at exactly one call site: `plan.cause` in `handle_connection_failure`, the core state in `wait_for_core_running`, the close code in the done-callback, the rejection in `park`. Spec 153 D10 deferred a transition-observer list, a `ConnectionTransition(old, new, detail, at)` payload and a replay-on-register to this sketch, with its D2–D5 as input. The writer is that list's only planned consumer. The async `connected_observers`/`disconnected_observers` stay as they are (spec 153 D7), as does the ready reason (spec 153 D8; its derivation belongs to #4101).

**Deciding factor:** state and row change together at the transition, from every call site including the done-callback, with no layer that has one consumer.

| | A: `set_connection_state(new, *, detail=None)` calls the writer directly | B: a sync observer list on `WebsocketService` with a `ConnectionTransition` payload and replay on register (spec 153 D2–D5) | C: a row-writing callable passed into `OutageLog` |
|---|---|---|---|
| Layers | One call | An observer list type, a payload type, a registration method with replay, and log-and-skip | A callable and `OutageLog`-inferred states |
| Consumers today | The writer | The writer | The writer |
| Done-callback | Works: the writer never awaits | Works: observers are sync | Works |
| Session-start row | The first transition after the session exists, DISCONNECTED → CONNECTING at the top of `serve()` | Replay gives one wherever the observer registers | `OutageLog`'s first state |
| Matches the app side (D1) | Yes: a direct call at the owner, like `set_app_status` | No | No |
| Without a session | No row; a counted drop, per Posture | Same | Same |
| What peers do | Prefect's funnel writes the row itself; `ApiWriteRecorder` is the in-repo precedent | gRPC (Python and Go), HA `ConfigEntry` and NetDaemon expose state callbacks or observables; gRPC Python, gRPC Go and home-assistant-js-websocket replay the current state to a new subscriber | tenacity passes `before`/`after` callables with no-op defaults |

**Recommendation:** A. With one consumer, an observer list is a layer with no second implementation, and the app side already writes from its owner directly. The call goes last in `set_connection_state`, after the state assignment and the `_connected_event`/generation bookkeeping, so a writer problem can't leave a transition half-applied. `detail` is the connection kind's details model (D5), built at the call site that has the fact. If a second in-process consumer of connection transitions appears (the #4101 announcer is the likely one), that change can introduce the observer list and move this call onto it.
**Peer divergence:** gRPC, HA and NetDaemon expose state callbacks because their callers are external subscribers they can't enumerate; this writer is internal and the only consumer, so Hassette uses a direct call, as Prefect's funnel does. Spec 153 D2–D5's inputs (sync over awaited, `old` passed, monotonic `at`, replay) stay on file for that later change.
**Pick B instead if** you want the seam now so #4101 and the writer share it from the start. **Pick C instead if** you want `WebsocketService` free of any telemetry call.
**Reversibility:** easy (internal; B can be added later without changing rows)
**Ratified:** Chose a direct writer call placed last in `set_connection_state` (after the state assignment and event/generation bookkeeping), with an optional `detail` (the connection details model) built at the call site and a writer that never raises, over a sync observer list with a `ConnectionTransition` payload and replay, or a callable into `OutageLog`, so state and row change together from every call site with no single-consumer layer and no writer failure can half-apply a transition, matching the app side, accepting a telemetry call inside `WebsocketService` and that a second consumer later introduces the observer list.

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

### D8: Are the outage length and the flap marker stored or derived? (supersedes part of parent D2)

**Situation:** parent D2 asks for "the outage's length in the row", and a flap marker would show a flapping link apart from separate outages. Storing them would draw on `OutageLog`: the length from `disconnected_at` (which a start that only waits on the core never sets) and the flap flag from `gap_after_flap`, a log-pacing concept (spec 131 D11). With rows written per `ConnectionState` transition (D4), both are functions of the row sequence, in `id` order (D5). The outage is the time from the first non-CONNECTED row after a CONNECTED one (or the session start, if the session never connected) to the next CONNECTED row. A flap is a CONNECTED row whose next row (non-CONNECTED) comes within `STABLE_CONNECTION_SECONDS` (120 s), the one stability test (`is_stable_connection`, `websocket_reconnect.py`), and that is followed by another CONNECTED row in the same session; a session shut down soon after connecting ends in DISCONNECTED with no later CONNECTED, so it is not a flap. Storing either one needs state outside the transition: an outage start on `WebsocketService` with its own reset rules, or a read of `OutageLog`'s episode fields.

**Deciding factor:** no writer state and no coupling to log pacing, at the cost of a computation #4084 does anyway.

| | A: derive both at read time (#4084) | B: store the outage length on CONNECTED rows and a flap flag on the row that leaves CONNECTED |
|---|---|---|
| New state | None | An outage start on `WebsocketService` (set on leaving CONNECTED or at the first transition, cleared on CONNECTED), or `OutageLog` passing its fields through |
| Coupling | None | `OutageLog`'s episode model feeds the table, or a third copy of "when the gap began" |
| A dropped row | Shows as a `from_status` break; no figure is reported across it (reading contract below) | Length survives on the CONNECTED row; a dropped non-CONNECTED row still hides a flap |
| Start while HA is starting | Length from the WAITING_FOR_CORE row (or session start) to CONNECTED | Needs the outage start set by the first transition, not only by leaving CONNECTED |
| Reader work | One window function over the session's connection rows, plus the stability constant | Read a field |
| What peers do | Uptime Kuma derives outage durations from heartbeats at read time; HA's history derives durations from consecutive state rows. No surveyed peer has a flap marker | none found |

**Recommendation:** A. It keeps the writer stateless and leaves `OutageLog` untouched, and it matches how Uptime Kuma and HA get durations. #4084 implements the derivation under this reading contract:

- **Order:** `id` within a session (D5).
- **Mid-sequence drop** (any drop path in Posture's failure-handling stance): shows as a `from_status` break, a row whose `from_status` differs from the previous row's `to_status`, compared per instance for app rows and per session for connection rows. Block rows have no `from_status`; since D3 writes only on change, a dropped block row shows as two `blocked` rows in a row for one `app_key`, or an `unblocked`/`removed` with no `blocked` before it in the session, and nothing is derived from block rows. Derived figures are reported only over a run with no break; across one, #4084 shows that rows are missing instead of a number. An app row with `from_status` NOT_STARTED after a STOPPED row is not a break, since STOPPED removes the registry entry and a missing entry reads as NOT_STARTED (`app_registry.py`, `set_status`).
- **Lost head** (retention removed the oldest rows of a session older than `retention_days`): a session's first retained row is never a break and never an anchor; a figure with no earlier row reads "since at least" that row's `ts`.
- **Lost tail** (the shutdown drain timed out): invisible in the rows; how a session ended comes from `sessions` (Assumed, the bounded-drain bullet).
- **No persisted drop count:** the `PipelineCounter` member and WARNING serve the live session only; for past sessions the `from_status` chain is the gap signal.

**Peer divergence:** none for the derivation. It supersedes parent D2's "outage's length in the row" because the row-per-transition shape (D4) makes the length derivable without state, which parent D2 didn't have available. The gap rule matches HA, whose `old_state_id` links each state row to its predecessor, and no surveyed peer persists a per-run drop count (OTel exports a live metric; HA and client-go log). The head rule has no surveyed counterpart: HA purges states by age, and how its history renders a purged predecessor is unknown.
**Pick B instead if** a figure that survives a dropped row matters more than keeping the writer stateless.
**Reversibility:** easy (B can be added as `details` fields without a migration)
**Ratified:** Chose to derive the outage length and flap marker at read time (#4084) from the connection rows in `id` order, under a reading contract (a `from_status` break marks a drop and blocks a figure across it, a session's first retained row is never a break or anchor, a session's end comes from `sessions`, no persisted drop count), over storing them on the rows, so the writer stays stateless, `OutageLog` stays untouched and gaps stay visible after a restart, matching HA's predecessor link and how Uptime Kuma and HA derive durations, accepting that a dropped final row is invisible in the rows and superseding parent D2's "outage's length in the row".

## Assumed

- **Parent D1 holds:** one append-only lifecycle table in #1446's shape, with the app-row writer replaced by #1446's projector later. Evidence: parent D1; #1446 is still open. #1446's projector would now be a consumer of `StatusChange` (spec 154).
- **Parent D11 holds:** writers go through `SessionManager`. Nothing is a listener on Hassette's own bus. Evidence: parent D11; `core/core.py` `before_shutdown` removes root bus listeners; #4093 (bus drain) is still open.
- **Parent D12 holds:** the table is its own `RetentionTarget` on `database.retention_days`, failsafe-exempt, and in the session delete guard. Like every other session child table, `session_id` has no `ON DELETE` clause, so the guard line is the only thing protecting the session delete: a session with lifecycle rows must not be deleted, as for the other child tables. HA's recorder likewise purges children explicitly rather than cascading. Evidence: parent D12; spec 132 D25; `core/retention_targets.py` already orders targets as D12 states; `core/database_retention.py` ~385–394; `migrations_sql/001.sql`, `005.sql`, `009.sql`, `024.sql` (no session FK cascades).
- **Parent D2's "no claim about what was up" and session boundaries** are read-side and belong to #4084. Session starts and ends are not copied into this table. Evidence: parent D2.
- **`set_status` decides what is a change:** it returns `None` for a non-change (same status, or a FAILED with the same error object and flag) and a `StatusChange` with the real previous status otherwise, and `set_app_status` is its only caller. Evidence: `core/app_registry.py:105-187`; `core/app_lifecycle_instances.py:184`; `core/REVIEW.md` (status-writer question).
- **`set_connection_state` is the only writer of connection state under `src/` after `__init__`, and ignores same-state calls.** Evidence: spec 153 D9; `core/websocket_service.py:228-268`; the call sites at `:344, :386, :400, :476, :525, :556, :594` and `testing/_ws_mocks.py:106-107`.
- **A session id exists before any writer can run:** `mark_orphaned_sessions` and `create_session` run right after the database starts and before other services, so `serve()`'s first transition already has a session. Transitions in tests without a session write no row and count as drops, per Posture. Evidence: `core/core.py` ~387–388.
- **Rows written while apps stop at shutdown are queued before the database detaches, but the drain is bounded:** `AppHandler` stops before the foundation stage, and `DatabaseService` drains its write queue on the way down within `SHUTDOWN_DRAIN_TIMEOUT_SECONDS` (5 s, clamped to the shutdown deadline). On timeout it abandons the remaining writes with a WARNING, so the final rows can be lost on a slow drain. The same holds for the connection row `WebsocketService.cleanup()` writes at shutdown, since the websocket service also stops before the foundation stage. How a session ended comes from `sessions` (`stopped_at` and its status), not from its last lifecycle row: a finalized session whose tail rows are missing ended cleanly and lost its tail. Peers bound it the same way: HA's final-write stage at 60 s with a WARNING, OTel's span processor at 30 s. Evidence: `core/database_service.py` ~346–367; `core/database_write_queue.py` ~150–182; `config/models.py:43`.
- **Rows abandoned by the drain can't be counted:** OTel counts post-shutdown drops as `already_shutdown`, but here the session record, the only place counters outlive the process, is written by `_finalize_session` before the database drains, and lifecycle counters live only in memory. The drain's WARNING is the durable record. Evidence: `core/core.py` `_run_foundation_stage` and `_finalize_session` (~657–676).
- **`enqueue` is the write path for fire-and-forget rows:** it returns `False` on a full queue and raises `RuntimeError` when the queue isn't live. A queued write that raises is logged at ERROR by the worker and not counted. Evidence: `ApiWriteRecorder.enqueue` (`core/api_write_recorder.py` ~201–212); `core/database_write_queue.py:44-70`.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**
- Three typed entry points (`record_app_change`, `record_connection_change`, `record_block_change`) in `core/telemetry/lifecycle_rows.py` each hand a builder for a `LifecycleChange` to `record_lifecycle_change`, the one function between the owners and the writer, instead of one untyped function taking every row field: each owner passes only what it has.
- The guard sits where the ledger puts it, in `SessionManager.write_lifecycle_row`: the session check, the builder call (which can raise, since it reads the change and builds the details model), serialization and enqueue are inside one `except Exception`, and every drop there is counted with a paced WARNING. `record_lifecycle_change` covers only the `hassette.session_manager` lookup: with no session manager wired (tests and harnesses) it counts the drop and logs at DEBUG, since there is no writer holding pacing state. The writer takes the builder rather than a built change so a failing build is caught inside that one guard.
- The insert takes the `LifecycleChange` plus the session id, serialized details and time; there is no separate row dataclass.
- The paced WARNING is a shared `WarnPacer` (`src/hassette/utils/warn_pacer.py`), chosen at the ship-time challenge. Every site that paced a WARNING by hand moved onto it: the lifecycle writer, `ApiWriteRecorder`, `ListenerMissRecorder`, `PendingResponses`, the execution write queue's capacity and empty-`app_key` WARNINGs, and the sync executor's and bus's saturation WARNINGs. Each holds its own instance, so one site never suppresses another's WARNING, and passes its interval per call. `wait_for_cancellations` keeps its own gate, since it also counts the calls it holds back. The bus's saturation gate now passes its first call regardless of process uptime (it started from `0.0`).
- `park()` takes the PARK plan's cause as an argument so the AUTH_FAILED row carries it; it had no other way to reach the call site.
- `make_mock_hassette()` sets `session_manager = None`, so code under a sealed mock counts a lifecycle drop instead of raising on attribute access.
- The removed-app manifest prune waits on lifecycle rows too, like every other table keyed by `app_key`, so a removed app's history keeps its manifest until the history ages out.
- `lifecycle_events.kind` is listed in the wire-parity test's server-only columns until #4084 serves the rows.
