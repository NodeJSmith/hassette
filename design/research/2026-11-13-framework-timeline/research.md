# Research Brief: Framework timeline and `hassette timeline` (#3678)

---
proposal: "Implement #3678: one append-only lifecycle table (connection, app status, block changes) written through SessionManager, and `hassette timeline --around <time> [--window] [--app]` plus an API route and wire models that merge it with executions, near-misses and API writes."
date: 2026-11-13
status: Draft
flexibility: Decided (ledger D1/D2/D11/D12/D13 ratified; pickup items open)
motivation: "Next piece of the ratified Diagnostic Evidence milestone; #3098, #1817 and #3677 have landed. Inform the pickup sketch and check the ledger against the code as it stands."
constraints: "Pre-V1 (no shims), small user base, Python 3.11+, SQLite telemetry DB, uv workspace (hassette-wire, hassette-client). Repo CLAUDE.md and .claude/rules apply. Web UI out of scope."
non-goals: "Web UI display; framework service failure rows (#2938); #1446's projector."
depth: deep
---

**Initiated by**: research ahead of `/mine-sketch design/specs/142-diagnostic-evidence/ #3678`.

## Bottom line

The ledger holds. Nothing that landed since 2026-11-01 makes D1, D2, D11, D12 or D13 wrong. Retention, the session delete guard and the failsafe are already shaped the way D12 expects, and the next migration is `026.sql`. Four findings will still change the sketch:

1. **D11 gives the right reason, but the real hazard is a different one.** Hassette's own bus listeners are removed in `before_shutdown` (`core/core.py`, `remove_all_listeners`). Separately, `BusService.serve` breaks out of its loop on its own `shutdown_event` without draining what is still buffered in the event stream (`core/bus_service.py:759`), so a STOPPED event sent by the last app to stop can go undelivered to *any* bus listener. A write at the send site avoids both problems. (The race is Inferred from reading the code; it was not reproduced.)
2. **There is no read surface for sessions or for live loss counts.** No route, wire model, client method or CLI lists sessions. `PipelineCounters` isn't exposed: `/api/telemetry/status` returns only the three `dropped_*` execution counters. The timeline's "session boundaries, unclean ends, and live loss count" are all new read work.
3. **App state events aren't one per transition.** `app_lifecycle_start_stop.py:198` re-broadcasts every already-failed instance on each `start_app`, so a naive writer stores duplicate FAILED rows. Some transitions send no event at all (listed under Q1).
4. **Spec 149 handed "chain walking" to this issue** (`design/specs/149-api-write-records/design.md:154`). That conflicts with D13's "reports evidence, doesn't draw conclusions". Flag it before the sketch absorbs it (Open Questions).

Recommended split: **two PRs**. The first adds the table and its writers; the second adds the merged read. For comparison, #4002 (API writes) was 87 files and #4013 (near-misses) was 134; #3678 as one PR would be the milestone's largest.

### Answers at a glance

| # | Question | Recommendation |
|---|---|---|
| 1 | App-state subscriber | Send all 7 send sites through one lifecycle funnel. The funnel calls a sync, enqueue-based `SessionManager` method, then `hassette.send_event`. Dedupe by keeping the last status written per (app, instance). No bus listener. |
| 2 | Block prior state | None needed. `reconcile_blocked_apps` already holds both the previous and current sets as locals. Write both diff directions there. |
| 3 | `record_core_wait` | Yes, at most once per gap. Without it, starting Hassette while HA is starting leaves no row. |
| 4 | `kind` values | Per source: `app`, `connection`, `block`, with from/to status. Add typed nullable `needs_restart` and `duration_s` columns and a short `detail`. |
| 5 | `--window` / `--around` | `--around` accepts what `--since` accepts (local time for naive input). `--window` means ±, default 15m. The API takes `since` and `until` epochs. |
| 6 | Near-miss buckets | Include a bucket when its first–last span overlaps the window, sort by `last_ts`, show "×N, first–last". Omit unflushed misses and state the 30 s flush window (151 D4 precedent). |
| 7 | Merge shape | A new `TimelineEntry` union keyed on `kind`. Don't widen `ActivityFeedEntry`; embed it for execution rows. |
| 8 | Heartbeat interval | `DatabaseConfig.heartbeat_interval_seconds`, the value in effect now, returned in the response. Say it may differ from the interval the crashed session ran with. |

## Context

### What prompted this
"What happened around this time" takes several commands plus `docker logs` today, and outage state lives only in memory. D1 and D2 settle on one append-only table in #1446's `app_status_events` shape, generalized by a `kind` column. D13 settles on one merged `hassette timeline` command.

### Current state (verified)
- **Startup order** (`core/core.py` ~365-400): DatabaseService starts first, then `mark_orphaned_sessions()` and `create_session()` run (L390-391), so a session id exists before any other service starts. SessionManager and WebsocketService are level 0, BusService is level 1, and AppHandler comes last. An outage that begins at startup already has a session id.
- **Stop order:** `before_shutdown` removes the root bus's listeners first. The stop stage then runs levels in reverse: AppHandler (apps send STOPPING, then STOPPED or FAILED) stops before BusService. In the foundation stage, `_finalize_session`, then SessionManager, then DatabaseService (which detaches and drains the write queue). Rows enqueued during app shutdown therefore reach the database (`core/database_service.py:346-367`).
- **Retention as built** (`core/retention_targets.py`): DEBUG logs, listener_misses, framework executions, blocking_events, api_writes, app executions, then exempt log_records. This is exactly D12's order. The session delete guard (`core/database_retention.py:386-394`) checks `executions`, `blocking_events` and `api_writes`. The lifecycle table joins it with one `NOT EXISTS` line plus the docstring at L327-332.
- **Migrations:** plain `NNN.sql`, `REAL` epoch timestamps, `CHECK (kind IN (...))` for enum-like columns, plain `REFERENCES sessions(id)` with no cascade (`024.sql:10`). No STRICT tables.
- **#1446 shape:** spec 132 D2 says only "one row per observed status change". It names no columns. D25 (`design/specs/132-db-source-of-truth/design.md:445-461`) makes it a `RetentionTarget` on `retention_days` in the session-delete NOT EXISTS guard. The 142 ledger's D12 adds failsafe exemption. The column list is ours to choose.
- **Unclean end:** `_do_mark_orphaned_sessions` (`core/session_manager.py:104-133`) sets `stopped_at = last_heartbeat_at` for any session left open. `running` becomes `unknown`; a session already at `failure` keeps that status. There is no staleness threshold.

## Feasibility analysis

### What would need to change

| Area | Files (approx.) | Effort | Risk |
|---|---|---|---|
| Migration `026.sql` and table assertions in migration and seed tests | 4–5 | Low | Low |
| Retention target and session guard | 2 | Low | Low; D25 already specifies it |
| `SessionManager.record_lifecycle(...)`, sync and enqueue-based, plus a new `PipelineCounter` member | 3 | Low–Med | First enqueue-style writer on SessionManager, which today awaits `submit` for everything |
| App-state funnel: 7 send sites, dedupe, needs-restart read | 3 | Med | Sites 198 and 226 have their own semantics. Harness tests mock `send_event`. |
| Block diff in `reconcile_blocked_apps` | 1–2 | Low | Removed apps must not read as "unblocked" |
| OutageLog hook | 2 | Med | Monotonic times; a gap-vs-episode choice; OutageLog is recreated in `serve()` (`websocket_service.py:321`) |
| Read: sessions query, windowed queries for 4 sources, merge | 3–4 | Med–High | Executions have no `app_key` and need the `handler_job_union_arms` join. Today's helpers support only `since`, not `until`. |
| Wire models, route, client method, compat fixtures, schema regen | ~10 | Med | First discriminated union in the wire package |
| CLI `timeline` command and snapshots | 4 | Med | First command that renders heterogeneous rows |
| Docs: `database-telemetry.md`, `cli/commands.md`, `cli/workflows.md`, `python-client.md` | 4–5 | Low | — |
| Seed rows in `scripts/seed_scenarios/base.py`, `healthy.py`, `lifecycle.py` | 3–4 | Low | — |

### What already supports this
- `ApiWriteRecorder` (`core/api_write_recorder.py` ~150-260) is the writer pattern to copy. It captures `try_session_id()` and `time.time()` and enqueues a repository coroutine. On `RuntimeError` it logs DEBUG; on a `False` return it counts and paces one WARNING per episode.
- `handler_job_union_arms` (`core/telemetry/helpers.py:236-299`) and `get_per_app_activity_buckets` already query executions by window with both bounds in `extra_*_where`.
- Indexes already exist for every source except sessions: `idx_exec_time`, `idx_aw_ts` and `idx_aw_app_ts`, and `idx_lm_last_ts`. `sessions` is small and pruned.
- HA's logbook builds one time-ordered stream with `UNION ALL` over a shared timestamp column (`logbook/queries/all.py`, with `States.last_updated_ts.label("time_fired_ts")` in `queries/common.py`). That supports a single SQL merge.

### What works against this
- No sessions read and no loss-counter exposure (finding 2).
- Re-broadcast and refusal paths in the lifecycle code (finding 3).
- `OutageLog` holds no `hassette` reference and records only monotonic times (`core/websocket_reconnect.py:237-334`).
- Two settings are both named `heartbeat_interval_seconds`: `DatabaseConfig` (models.py:118) and `WebsocketConfig` (models.py:195, the aiohttp ping). Both default to 30.

## Pickup questions: options and recommendations

### Q1. App-state subscriber: placement and timing

**Evidence.** `HassetteAppStateEvent` (`events/hassette.py:155`) is sent from 7 sites:

| Site | Status sent |
|---|---|
| `app_lifecycle_start_stop.py:198` | Re-broadcasts FAILED for already-failed instances |
| `app_lifecycle_start_stop.py:208` | NOT_STARTED |
| `app_lifecycle_start_stop.py:226` | Discarded entry: FAILED if flagged needs-restart, else STOPPED |
| `app_lifecycle_start_stop.py:399` | FAILED on class-load or create failure |
| `app_lifecycle_start_stop.py:466` | NOT_STARTED |
| `app_lifecycle_instances.py:459` | STOPPING |
| `app_lifecycle_instances.py:504` | `emit_app_state_change`, the funnel for RUNNING, FAILED-on-init, STOPPED, FAILED-on-stop and FAILED-after-raise |

The payload has `app_key`, `instance_name`, `status`, `previous_status` and exception fields, but no needs-restart field. The flag is readable at send time from `AppRegistry.get_needs_restart(app_key, instance_name)` (`core/app_registry.py:150`). It is set in `settle_*` before the outcome event is sent, and it survives `unregister_app`.

**Transitions that send no state event** (the PR must name these, per the acceptance criteria):
- A start refused because the app is blocked (`AppBlockedError` at `_start_app_unlocked` ~L137 and `_create_instance_unlocked` ~L433). The block diff covers this.
- A start refused because the app needs a restart (`outcomes.refused`, ~L441).
- No STARTING event exists, even though RUNNING and FAILED events claim `previous_status=STARTING` (`app_lifecycle_instances.py:129`).
- A failed init sends no STOPPING.
- Enabling or disabling an app in config sends no event of its own; only the resulting stop or start does.
- A "crash of a running app" isn't an app-level transition (handler errors are executions). Not fully verified for every `App` internal.

**Options:**

| | A: one lifecycle funnel calls `SessionManager` | B: `ObserverList` on the lifecycle service | C: tap in `Hassette.send_event` | D: bus listener on a SessionManager-owned `Bus` |
|---|---|---|---|---|
| Sees final STOPPED at shutdown | Yes | Yes | Yes | No (finding 1) |
| SessionManager starts before the bus | Irrelevant | Irrelevant | Irrelevant | Must register late |
| New sends covered automatically | Only through the funnel; add a structural test that `HassetteAppStateEvent` is sent nowhere else | Same as A | Yes, from anywhere | Yes |
| Layers | One call | Observer list with a single consumer | Side effect in a hot, general send path | Bus, dispatch, executor |
| Harness | Funnel runs; writer no-ops without a session | Same | Harness replaces `send_event` (`testing/_harness.py:409`) | — |
| Precedent | `ApiWriteRecorder` direct call | `WebsocketService.connected_observers` (`core/observer_list.py`) | none | `RuntimeQueryService` uses its own `Bus` (`core/runtime_query_service.py:131`), but for in-memory state, where a lost STOPPED doesn't matter |

**Recommendation: A.** Route all 7 sites through one helper on the lifecycle (extend `emit_app_state_change`'s role, or add a sibling). The helper builds the event, calls `SessionManager.record_app_status(...)` (sync, enqueue), then sends. D2 wanted new lifecycle paths covered automatically: keep that by testing that `HassetteAppStateEvent` is constructed and sent only from the funnel, rather than by putting a hook in `send_event`. B adds an observer list with one consumer, which `reader-load.md` argues against. C has the best automatic coverage but puts telemetry knowledge inside `Hassette.send_event`, which every HA event passes through. D is ruled out.

**Dedupe:** keep a last-written status per (app_key, instance_name) in the writer and skip unchanged statuses. This handles the site-198 re-broadcast, and it is already the "per observed change" semantics #1446's projector will have (D1), so the later swap changes less. Reset the map per session.

**Needs-restart:** read `get_needs_restart` in the funnel for FAILED rows only.

### Q2. Block reconciliation prior state

`reconcile_blocked_apps` (`core/app_lifecycle_config.py:141-157`) computes `previously_blocked = registry.unblock_apps(ONLY_APP)` and `currently_blocked` as locals. It returns only `previously - currently` and discards `currently - previously`. The prior set isn't lost, just never returned. `BlockReason` has one member (`ONLY_APP`, `types/enums.py:157`), and `block_app` and `unblock_apps` have no other callers.

| | A: diff and write inside `reconcile_blocked_apps` | B: store last-reconciled set on the registry | C: return both sets; callers write |
|---|---|---|---|
| New state | None | One field to keep in sync | None |
| Callers changed | 0 | 0 | 3 (`app_lifecycle_service.py:213`, `_fold_unblocked_apps_into_changes`, replay path) |

**Recommendation: A.** Two details:
- At bootstrap the prior set is empty, so every blocked app gets a "blocked" row at session start. That is correct for a per-session timeline.
- An app that leaves `enabled_manifests` while blocked falls out of `currently_blocked`. Intersect the unblocked set with current manifests so a removed app doesn't read as "unblocked".

The function is sync, which is why the `SessionManager` method must enqueue rather than await.

### Q3. Do `record_core_wait` episodes become connection rows?

`record_core_wait` (`websocket_reconnect.py:314`) runs after the socket is authenticated, while HA's core state isn't RUNNING. It is called on every recheck (`websocket_service.py:451`), and it opens an outage episode if none is open. If Hassette starts while HA is STARTING, there is no `record_failure` at all, only core waits and then `record_connected`. Without a row here, the acceptance criterion's "outage that starts during startup" is missed in exactly that case. An HA restart otherwise reads as: failure with cause (e.g. `CoreShuttingDownError`), then a core wait, then connected.

**Recommendation: yes.** Write one `connection` row per gap on the first core wait (to_status `waiting_for_core`, detail = core state), never per recheck.

**Sub-question the sketch must settle: per gap or per episode.** `OutageLog` distinguishes a *gap* (`disconnected_at` until `record_connected`) from an *episode* (which stays open until a connection survives `STABLE_CONNECTION_SECONDS = 120`).
- Per-gap rows are simple: a "disconnected" row with the cause, and a "connected" row with `duration_s`. But a flapping link writes a pair per flap. D2 counted exactly that against bus events.
- Per-episode rows need an episode-close point, and none exists (the reset is lazy, in `record_failure` L269-271).

Recommendation: per gap, carrying `OutageLog`'s existing `gap_after_flap` as a `flap` marker. Volume is bounded by backoff and sits within D12's crash-loop estimate.

**Implementation notes:**
- Pass a row-writing callable into `OutageLog` at both construction sites (L162 and L321), with a no-op default for tests.
- Compute wall-clock time with `time.time()` at the write; convert durations from the monotonic difference.
- PARK (token rejected) is a `record_failure` and becomes a row too.

### Q4. `kind` values and needs-restart

| | A: kind per source, with from/to status | B: kind per transition (`app_failed`, `connection_lost`…) |
|---|---|---|
| #1446 swap | Projector writes `kind='app'` rows; nothing else moves | Projector must emit the transition vocabulary |
| Query "what happened to app X" | `kind='app' AND app_key=?` | A list of kinds |
| Adding a status | No migration | `CHECK` migration |

**Recommendation: A.** Proposed columns:
- `id`
- `session_id NOT NULL REFERENCES sessions(id)`: the writer skips and counts if there's no session, which can't happen given startup order.
- `kind CHECK IN ('app','connection','block')`
- `app_key`, `instance_name`: both NULL for connection rows.
- `from_status`, `to_status`: app rows use the event's `ResourceStatus` values.
- `needs_restart INTEGER NULL`: app rows only.
- `duration_s REAL NULL`: connection recovery rows.
- `detail TEXT`: cause, exception type, or block reason.
- `ts REAL NOT NULL`

Indexes on `(ts)`, `(app_key, ts)` and `(session_id)`.

Connection statuses: `disconnected`, `waiting_for_core`, `connected`, `parked`. Block rows: `blocked` / `unblocked`, with the reason in `detail`.

Typed `needs_restart` and `duration_s` columns beat packing them into `detail`, because the wire model and later UI shouldn't have to parse strings. D2's "a short detail (such as outage length)" reads as illustrative, not as a requirement for one free-text column. Ask if that reading is wrong.

### Q5. `--window` default and `--around` format and timezone

Existing CLI time input: `convert_since` (`src/hassette/cli/types.py:41-85`) accepts relative `\d+[smhdw]`, ISO with `Z`, ISO with offset, naive ISO (read in the **terminal's** zone via `SYSTEM_TZ`, not Hassette's configured zone), and date-only. It doesn't accept `HH:MM`, epoch numbers, or an upper bound. Every `--since` defaults to `None`, and the server decides. Routes take `since` as an epoch float (`SinceQuery`, `web/dependencies.py:28`).

Peers:
- docker logs: naive times use client-local, and `Z` or an offset wins ([container_logs.md](https://github.com/docker/cli/blob/master/docs/reference/commandline/container_logs.md)).
- journalctl: naive times use the local zone.
- kubectl: a duration and an absolute time are separate flags.
- HA logbook REST: one-day window ([rest_api.py](https://github.com/home-assistant/core/blob/dev/homeassistant/components/logbook/rest_api.py)).
- Datadog log search: defaults to the last 15 minutes. Its "view in context" window isn't documented.

No peer has an "around" flag with a documented default.

**Recommendation:**
- **`--around`** reuses `convert_since`'s formats unchanged, so a relative value means "that long ago" (`--around 2h`). Naive times stay terminal-local.
- **`--window`** is a duration meaning ± around that time, default **15m** (a 30-minute view). Use the same `\d+[smhdw]` grammar, factored out of `convert_since`.
- **API:** the route takes `since` and `until` epoch floats, with a new `UntilQuery` matching `SinceQuery`. The CLI computes them. This keeps the API reusable by the UI, which will pan and zoom rather than think in terms of "around".
- **Output:** return a `truncated` flag with the existing `limit`.

Open preference: whether `--around` should also accept a bare `HH:MM[:SS]` meaning today, local time. Incidents are usually remembered that way ("about 5am"), but no other flag accepts it, and it would need to apply to `--since` too to stay consistent.

### Q6. Hour-long near-miss rows and unflushed misses

A `listener_misses` row (`025.sql`) is one listener × reason × filter × hour, with `count`, `first_ts`, `last_ts` and the last trigger's values. Only `last_ts` is indexed (`idx_lm_last_ts`). Rows are app-scoped through `listeners.app_key`.

| | A: include when `last_ts` is in the window, sort by `last_ts` | B: include on overlap (`first_ts <= until AND last_ts >= since`), sort by `last_ts` | C: sort at hour start |
|---|---|---|---|
| Misses straddling the window's end | Dropped | Shown | Shown |
| Sort position matches a real miss | Yes, the last one | Yes; can sort just past the window's end | No: the hour start can precede every miss by up to 59 min |
| Index | `idx_lm_last_ts` | `idx_lm_last_ts`, plus a filter on `first_ts` | none |
| Peer | `kubectl events` sorts on last-seen and prints "x5 over 12m" ([events.go](https://github.com/kubernetes/kubectl/blob/master/pkg/cmd/events/events.go)); [k8s#29838](https://github.com/kubernetes/kubernetes/issues/29838): "people expect to see the time of last occurrence" | Same, plus Grafana region annotations (one row, `time` and `timeEnd`) | none |

**Recommendation: B.** Display "×N, first HH:MM:SS – last HH:MM:SS". State in the docs and the wire field description that `count` covers the whole bucket, not just the window.

**Unflushed misses:** omit them, and state the 30-second flush window (`FLUSH_INTERVAL_SECONDS`, `core/listener_miss_recorder.py:44`). Spec 151 D4 already rejected reading memory alongside database rows for `--misses` (option D). An unflushed `MissEntry` holds live `Listener` and `AnyEvent` references, and a merge would double-count a row already stored for the same key. HA's one-shot logbook read accepts its 5-second `commit_interval` gap the same way; only its streaming read closes the gap. Print the note only when `until` is within 30 seconds of now, to keep normal output clean.

### Q7. Reuse `ActivityFeedEntry` or add `TimelineEntry`

`ActivityFeedEntry` (`wire/src/hassette_wire/telemetry.py:217-244`) is execution-only (`row_id`, `status`, `timestamp`, `app_key`, handler fields, `duration_ms`, `error_type`, `kind` handler|job). The per-app activity route, the CLI's `app activity` and the frontend's `recent-activity-section.tsx` consume it.

| | A: widen `ActivityFeedEntry` | B: new `TimelineEntry` union keyed on `kind` |
|---|---|---|
| Existing consumers | Every consumer sees optional fields for four sources | Untouched |
| Typing | Many nullable fields; reader must branch | Each member typed; generated TS gets a union |
| Reuse | Same model | Execution members embed `ActivityFeedEntry`; miss members embed `ListenerMiss` plus listener identity; write members embed `ApiWrite` |

**Recommendation: B.** The response would be `TimelineResponse{entries, sessions, live_loss_count, heartbeat_interval_s, since, until, truncated}`. Session start and end can be entries too, as HA renders its own start and stop as ordinary logbook rows ([homeassistant/logbook.py](https://github.com/home-assistant/core/blob/dev/homeassistant/components/homeassistant/logbook.py)). The repo has no discriminated union in the wire package yet, so check `export_schemas.py --types` and the TS generator output early.

### Q8. Which heartbeat interval the unclean-end note quotes

`DatabaseConfig.heartbeat_interval_seconds` (models.py:118, default 30, `ge=10`) drives `UPDATE sessions SET last_heartbeat_at` (`core/database_service.py:331`, `638`). There is no separate orphan threshold, and `max_consecutive_heartbeat_failures` isn't an end-of-session interval.

**Recommendation:** quote the current configured value, returned as `heartbeat_interval_s` in the response. Word the note "up to one heartbeat interval later (currently N s)", because the crashed session may have run with a different setting and `sessions` doesn't store it. Storing it per session is possible but not worth a column now. Docs name the `database.` setting explicitly, given the WebSocket setting of the same name.

**Two kinds of unclean end:** `status='unknown'` (orphaned while running) and `status='failure'` with a backfilled `stopped_at`.

## Ledger check: anything invalidated?

- **D1, D12:** hold. Next migration is 026. The `RetentionTarget` uses `failsafe_exempt=True` and goes after app executions. The guard gets one extra `NOT EXISTS`. #1446, #2938 and #3280 are still open, as D1 assumed.
- **D2:** holds, with three complications:
  - The site-198 re-broadcast needs the dedupe above.
  - `record_core_wait` is needed for the startup case.
  - "Connection rows from `OutageLog`'s failure and recovery points" has to choose between gaps and episodes (Q3).
- **D11:** holds. Its fallback ("a small dedicated subscriber could feed SessionManager") is close to Q1's option A. The reason it gives is incomplete (finding 1).
- **D13:** holds. The sessions read and live loss count are unbudgeted new read work.
- **Spec 149 D5's "chain walking belongs to #3678"** is not in D13 (see Open Questions).

## Concerns

### Technical risks
- **Shutdown dispatch race (finding 1).** It only matters if someone later moves the writer onto the bus. Add a test that the last app's STOPPED row is written during shutdown, so a regression shows.
- **Funnel coverage erodes.** A new lifecycle path that calls `send_event` directly writes no row: the Airflow PR 61932 failure from the prior-art brief. A structural test (no `HassetteAppStateEvent` sent outside the funnel) is the cheap guard.
- **Windowed execution reads across all apps.** `--app`-less output covers every app's executions in 30 minutes. A chatty install may hit `limit`, so the `truncated` flag and message matter.
- **Sync writer from `reconcile_blocked_apps`.** The `SessionManager` method must never await. `enqueue` returns `False` on a full queue, which is counted.

### Complexity risks
- The first discriminated-union wire model and the first heterogeneous CLI table. Column snapshots (`tests/snapshots/cli_columns.json`) need a design for a `kind`-dependent summary column.
- Loss counts: past sessions store only the three `dropped_*` columns, so "live session's loss count" can't be shown for earlier sessions. The ledger asks only for the live one.

### Maintenance risks
- The app-row writer is temporary until #1446 (D1). Per-observed-change dedupe now keeps that swap small.

## Recommended PR split

1. **PR 1, record (writers).**
   - Schema: `026.sql`, the retention target and session guard, and the `PipelineCounter` member.
   - Writers: `SessionManager.record_*` (sync enqueue), the app-state funnel with dedupe and needs-restart, the block diff, and the OutageLog hook with core-wait rows.
   - Supporting work: seed rows, migration, retention and writer tests, and `database-telemetry.md` (table, retention, best-effort).
   - The PR names the transitions that send no event.
   - Verifiable on its own through seed and integration tests and a shutdown test.
2. **PR 2, read (`hassette timeline`).**
   - Queries: sessions, windowed queries for four sources, and `UntilQuery`.
   - Read surface: the `TimelineEntry` union and route, the live loss-count exposure, the client method and its `client_compat` fixture (`tools/client_compat_requests.py`, `client_compat_live_state.py`), schema regen, and the client schema floor bump (`.claude/rules/client-schema-floor.md`).
   - CLI: `cli/commands/timeline.py` with snapshots.
   - Docs: `cli/commands.md`, `cli/workflows.md` ("what happened around T"), and `python-client.md`.

PR 1 leaves rows with no read path for one PR. That's acceptable inside a ratified milestone that already excludes the UI, but both PRs must close one issue (`closes #3678` only on PR 2).

## Open questions

- [ ] **Chain walking.** Spec 149 D5 says following a write → HA automation → downstream run chain "belongs to #3678's timeline". D13 says the timeline draws no conclusions, and Hassette stores no HA events to walk through. Drop it explicitly, or define it as showing each execution's existing `caused_by` (no walking)? Needs your call.
- [ ] **`--around HH:MM`** (today, local): worth a format no other flag accepts?
- [ ] **Flap rows:** per-gap rows with a `flap` marker (recommended) or per-episode rows? Prototype on a flapping-link test, because the volume matters.
- [ ] **Typed `needs_restart` and `duration_s` columns** vs D2's single "short detail": confirm the reading.
- [ ] **Loss count shape:** one summed number of `CounterKind.LOSS` counters, or a per-counter breakdown? The ledger says "loss count"; a breakdown helps a reader tell which evidence is missing.
- [ ] **Unknown:** whether the shutdown race in finding 1 fires in practice. It needs a buffered STOPPED event at the moment BusService's `shutdown_event` is set. Not reproduced. It's moot under option A.

## Recommendation

Proceed with the sketch on the ledger as ratified. Settle the four pickup items as in the table above, and add the sessions read and loss-count exposure to scope explicitly. Take the funnel-plus-`SessionManager` route for app rows rather than any bus subscriber. That is Supported by the shutdown ordering and the `serve` loop's break, and it matches D11's own fallback. Split into a writers PR and a read PR.

### Suggested next steps
1. `/mine-sketch design/specs/142-diagnostic-evidence/ #3678`, seeding its ledger with Q1–Q8 and the chain-walking question.
2. In PR 1, write the shutdown test (last app's STOPPED row lands) and the structural funnel test first, as RED.
3. Before PR 2, generate a throwaway `TimelineEntry` union through `export_schemas.py --types` to check the frontend type output.

## Sources

- HA logbook UNION ALL: https://github.com/home-assistant/core/blob/dev/homeassistant/components/logbook/queries/all.py ; shared ts label: .../logbook/queries/common.py
- HA logbook REST default period: https://github.com/home-assistant/core/blob/dev/homeassistant/components/logbook/rest_api.py
- HA logbook live/DB handoff via commit future: https://github.com/home-assistant/core/blob/dev/homeassistant/components/logbook/websocket_api.py ; `DEFAULT_COMMIT_INTERVAL = 5`: .../recorder/const.py
- HA start/stop as logbook rows: https://github.com/home-assistant/core/blob/dev/homeassistant/components/homeassistant/logbook.py
- HA `recorder_runs.closed_incorrect` / `end_incomplete_runs`: https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/db_schema.py ; .../recorder/util.py. HA closes a crashed run at the *next start's* time, not a heartbeat. Hassette's last-heartbeat end is more precise.
- HA traces have start/finish, with no lifecycle record: https://github.com/home-assistant/core/blob/dev/homeassistant/components/trace/models.py
- AppDaemon current-state-only `app.<name>` entities and `app_initialized`/`app_terminated` events: https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/app_management.py
- NetDaemon enabled flag mirrored to an HA entity: https://github.com/net-daemon/netdaemon/blob/main/src/Runtime/NetDaemon.Runtime/Internal/AppStateManager.cs
- kubectl events sort by last-seen and print "x N over": https://github.com/kubernetes/kubectl/blob/master/pkg/cmd/events/events.go ; rationale: https://github.com/kubernetes/kubernetes/issues/29838
- Grafana region annotations: https://github.com/grafana/grafana/blob/main/pkg/api/annotations.go
- docker logs time formats and local default: https://github.com/docker/cli/blob/master/docs/reference/commandline/container_logs.md
- systemd time spec (local default): https://github.com/systemd/systemd/blob/main/man/systemd.time.xml

Searched with `exa-search` and by fetching raw source; no WebSearch fallback was needed. Not found: Datadog's documented "view in context" window, a `git log --since` timezone rule, and NetDaemon failure history.
