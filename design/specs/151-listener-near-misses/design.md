# Design: Listener Near-Misses

**Date:** 2026-11-12
**Status:** built
**Mode:** sketch
**Issues:** #1817
**Parent:** design/specs/142-diagnostic-evidence/design.md
**Prior art:** design/research/2026-11-01-diagnostic-evidence/prior-art.md

## Summary

An event that reaches an app listener and gets dropped leaves nothing behind unless DEBUG is on. A listener showing 0 runs looks the same whether it rejected 500 events or never saw one. This change records each listener-scoped drop in an hourly rollup per listener and reason, keeping the last event's entity and values, and exposes it through `GET /api/telemetry/listener/{listener_id}/misses` and `hassette listener <id> --misses`. It implements parent D3, D4 and D5 as refined below. Out of scope: web UI (parent Breakdown), the merged timeline (#3678), framework-tier listeners (parent D4), and drops before any listener is reached (the global event filter, events before the connection is ready).

New pieces and their homes:

- **Scope predicate:** `Listener` (`src/hassette/bus/listeners.py`) gains a separate scope predicate next to `predicate`, filled by the registration methods in `src/hassette/bus/bus.py` with the filters they build to select events (D1), including the change filter when `changed=` isn't passed (D2). `on_state_change` and `on_attribute_change` change `changed`'s default to `NOT_PROVIDED`, which behaves as `True`. `NOT_PROVIDED` is a falsey sentinel, so every truthiness test of `changed` (`bus.py:910`'s `changed=False` warning check, `_build_preds`' `if changed:` at `bus.py:1749`) resolves the sentinel to `True` first; a test pins that the default still filters on change and doesn't warn. Their docstrings and `docs/pages/core-concepts/bus/methods.md` say so. `Listener.matches` evaluates scope first; a scope rejection is not a miss.
- **Filter attribution:** `Listener.matches` walks the top-level `AllOf` of the user-facing predicate (flattening nested `AllOf`s) and reports which child rejected (parent D5). The walk is the evaluation: `Listener.matches` evaluates the flattened user-facing children itself, once each, in order, stopping at the first false one, in place of calling the folded predicate, so no child is ever evaluated a second time to attribute a rejection. `BusService._match_listeners` (`src/hassette/core/bus_service.py`) remembers a rejected listener for the rest of that event's routes, next to its existing `failed` set.
- **Drop reporting:** `BusService` binds one drop reporter to each app listener's `HandlerInvoker` at registration (beside `mark_registered`), and each drop site calls it with `(reason, event)`, so nothing is allocated per dispatch; this matches the injected `record_predicate_failure` and HA's attach-time `did_not_trigger` reporter. `HandlerInvoker.dispatch` (`src/hassette/bus/listeners.py`) gains the event and calls the reporter for the spent-`once` guard and for mode-guard `SUPPRESSED`/`DROPPED` outcomes (`src/hassette/execution_mode.py`); `RateLimiter` (`src/hassette/bus/rate_limiter.py`) calls it for a throttled call, and records `debounce_superseded` in `debounced_call`'s branch that cancels a still-pending previous task, for the event that task was holding (RateLimiter keeps the pending call's event or drop report beside `_debounce_task`); the `CancelledError` branch in `delayed_call`, also reached by listener removal and shutdown, records nothing; `BusService._spawn_dispatch_task` reports backpressure drops; `DurationHoldManager` (`src/hassette/bus/duration_hold.py`) and `DurationTimer.evaluate_cancel_event` (`src/hassette/bus/duration_timer.py`) report hold cancellations and fire-time recheck drops through an injected callable, as `record_predicate_failure` is injected today (D5, D7).
- **Aggregator:** a new `ListenerMissRecorder` in `src/hassette/core/listener_miss_recorder.py`, composed by `BusService` (parent D11). The dispatch path only updates an in-memory entry keyed by listener, hour, reason and filter (D3): count, first and last time, and the last event's raw tracked values plus its id, origin, parent id and topic. No I/O and no value rendering happen on the dispatch path; values are rendered at flush with the trigger formatter in `src/hassette/core/execution_record_builder.py` (spec 147 D2). It records only app-tier listeners with a `db_id`.
- **Flush:** a task in `BusService`'s task bucket flushes on an interval (D4) and once on shutdown, as one batched upsert through `TelemetryRepository`. An in-memory entry holds only what accrued since the last flush: at flush the recorder swaps its entry map for an empty one, so dispatch writes to fresh entries and closed hours leave memory. The upsert adds `count = count + excluded.count`, keeps `first_ts = MIN(first_ts, excluded.first_ts)`, and replaces the last-event columns only when `excluded.last_ts >= last_ts`, so a restart or app reload within the hour adds to the row rather than resetting it. The flush task awaits `DatabaseService.submit()` for its batch, as the execution flusher does (`src/hassette/core/execution_pipeline.py:280`), so a SQLite error, a submit timeout or an unavailable queue reaches the recorder. A retryable failure merges the swapped-out batch back; any other dropped or failed flush loses exactly that batch and is counted and warned about through a new `PipelineCounter` member, per Posture's failure handling. On shutdown, `BusService` awaits dispatch idle, then runs the final flush through the same awaited path, before `DatabaseService` detaches its write queue.
- **Storage:** migration `src/hassette/migrations_sql/025.sql` adds `listener_misses`: listener id (FK to `listeners` with `ON DELETE CASCADE`, so the three existing listener deletes in `src/hassette/core/session_manager.py`, `src/hassette/core/telemetry/repository.py` and `src/hassette/core/database_retention.py`, and any later one, remove a listener's miss rows instead of failing on the enforced FK. Miss rows therefore live exactly as long as their listener row: the retention delete only removes listeners retired before the cutoff, so their rows were already past it, while the two once-listener cleanups (stale `once=True` listeners from earlier sessions, and once-listeners no longer registered at reconcile) remove a fired or abandoned once-listener's rows at the next start or reload, as the startup cleanup already does for its executions; `database-telemetry.md` says so), hour start, reason, filter summary, count, first and last timestamps, and the last trigger fields in the same columns and display-string shape as executions' trigger columns (spec 147 D2), with a unique index on (listener id, hour, reason, filter) for the upsert. A new `RetentionTarget` in `src/hassette/core/retention_targets.py` ages it out on `database.retention_days` and puts it second in the failsafe order, after DEBUG log lines (parent D12); later priorities shift by one.
- **Read surface:** a query beside `get_listener_summary` in `src/hassette/core/telemetry/registration_queries.py`; a `ListenerMiss` wire model in `wire/src/hassette_wire/telemetry.py` with `hour_ts`, `reason`, `filter` (None for non-filter reasons), `count`, `first_ts`, `last_ts` and `trigger`, an `ExecutionTrigger` for the last event (spec 147 D1; `caused_by` per D6 below); the route `GET /api/telemetry/listener/{listener_id}/misses` in `src/hassette/web/routes/telemetry.py`, beside `/listener/{listener_id}/executions` and taking the same `since` and `limit` query parameters with the same defaults, ordered by `last_ts` descending; a client method in `client/src/hassette_client/client.py`; a `--misses` flag on `cmd_listener` in `src/hassette/cli/commands/listener.py`, valid only with a listener id, which swaps the invocation table for a miss table (hour, reason, filter, count, last time, entity, old → new) and honors `--since`, `--limit` and `--json` as the invocation view does.
- **Docs:** `docs/pages/core-concepts/database-telemetry.md` (the table, retention and failsafe place, best-effort flush), `docs/pages/cli/commands.md` and `docs/pages/cli/workflows.md` (`--misses`, a "why didn't my listener run" walkthrough), and `docs/pages/core-concepts/bus/filtering.md` (which filters count as misses). Both the walkthrough and `filtering.md` state that an empty `--misses` doesn't mean the listener saw no events: scope rejections, including the default change filter (D2), record nothing. Regenerated schemas and frontend types; seed scenarios gain miss rows.
- **Benchmark:** a new file under `tests/benchmarks/` timing an in-scope event rejected by a `where` child through `BusService._match_listeners`; the 10% limit (parent D3) is the miss path's added time as a fraction of that pass. The benchmark is committed before the recording code and run with `uv run nox -s benchmarks` on both commits, and both numbers go under "Calls made during the build".

## Posture

- **Failure handling:** recording is best-effort and never affects dispatch or a handler. A flush whose write provably didn't run (a submit timeout, or a SQLite `OperationalError` that rolled it back) merges its batch back for the next flush, up to three flushes in a row, as the execution flusher retries the same failures. Any other failed or dropped flush, a retryable failure past that bound, and a retryable failure on the final shutdown flush is counted as a new `PipelineCounter` member with one WARNING per episode, and isn't retried. (Revised at the ship-time challenge from the parent Posture's drop-and-count; see Build.)
- **Compatibility:** clean breaks; pre-V1. The new table starts empty with no backfill. The wire change is additive and goes through `client_compat` (parent Posture).
- **Scope:** only #1817's slice of the parent Done-when ("which events reached a listener and were dropped, by which filter and with what values"). No UI, no timeline merge.
- **Rollout:** on by default, no flag. Migration `025.sql` chains after `024.sql`.
- **Hardening:** project defaults, plus parent D3's 10% limit on the miss path, compared by hand rather than gated in CI; the Summary's Benchmark bullet says what is measured.
- **Altitude:** `build`; one session builds it from this ledger.

## Decisions

### D1: How does a listener keep registration-built selection filters apart from the filters that count as misses?

**Situation:** parent D4 says a filter the registration method builds to select events (entity, domain, service, component) is the listener's scope and doesn't count as a miss, while `where` and the change filters do. Today they all land in one list. `_build_preds` (`src/hassette/bus/bus.py:1730`) starts a state or attribute listener's list with `P.EntityMatches(entity_id)`; `on_call_service` (`bus.py:1002`) appends `P.DomainMatches`/`P.ServiceMatches`; `on_component_loaded` and `on_service_registered` add `P.ValueIs`/`DomainMatches`/`ServiceMatches`; `_subscribe` (`bus.py:685`) appends the user's `where`; `_on_internal` folds the list into one `Listener.predicate`. Without a split, a glob such as `sensor.kitchen_*`, routed through the domain topic `hass.event.state_changed.sensor`, would record a miss for every other sensor's event. A user can also pass `P.EntityMatches` inside `where`, where it should count.

**Deciding factor:** scope is decided once, where the registration method knows what it built, with no rule a user's own predicate can trip over.

| | A: separate scope predicate on `Listener` | B: scope marker on predicate types | C: count of leading scope children |
|---|---|---|---|
| Where the split is decided | Each registration method passes selection filters and user filters separately | Classes such as `EntityMatches` are always scope | Registration records how many leading children are scope |
| User's `where=P.EntityMatches(...)` | Counts as a miss, correctly | Treated as scope, wrongly | Counts, correctly |
| Order sensitivity | None | None | Breaks if a builder reorders or a nested `AllOf` is flattened differently |
| Change size | New field; registration methods pass two lists; `config_matches` compares both; descriptions render both combined as today | A flag on a few classes | One int; every builder must keep scope first |
| Dispatch cost | Scope check first, so out-of-scope events skip the user filters (a small saving) | Same as today | Same as today |
| What peers do | HA: a trigger's entity and platform select the event, conditions filter it, two separate configs | unknown | unknown |

**Recommendation:** A, because the registration method is the only place that knows which filters it built for selection, and a separate field makes the scope impossible to confuse with a user's filter. `wait_for` and `on()` have no selection filters; their whole predicate is user-facing.
**Pick B instead if** you'd accept a user's `where=P.EntityMatches(...)` silently not counting, for the smallest diff. **Pick C instead if** you want no new field and accept an ordering invariant every builder must keep.
**Reversibility:** easy (internal)
**Ratified:** Chose a separate scope predicate on `Listener`, filled by each registration method, over a scope marker on predicate types or a leading-children count, so scope is decided where the selection filters are built and a user's own `EntityMatches` in `where` still counts, accepting a new field that `config_matches` compares and registration methods that pass two lists.

### D2: Does the default `changed=True` filter count as a miss? (refines parent D4)

**Situation:** `on_state_change` and `on_attribute_change` default to `changed=True`, which builds `P.StateDidChange` or `P.AttrDidChange(attr)` (`bus.py:1779`, `bus.py:1800`). On `on_attribute_change("light.kitchen", "brightness")`, that filter rejects every state-changed event for the light where brightness didn't change: every on/off, every color change, every other attribute update. On `on_state_change`, it rejects every attribute-only update. Parent D4 says "the change filters still count as misses", which read literally records all of these. They answer no "why didn't it run" question a person asks: nobody expects a brightness listener to run when the color changes. A comparison passed as `changed=` (for example `changed=lambda old, new: new > old`) is a real user filter.

**Deciding factor:** a miss row means an event the listener was about (parent D4's own test), without noise that drowns the rows people look for.

| | A: `changed=True` is scope; a comparison counts | B: count it, as parent D4 reads | C: count it only when the caller passes `changed=` |
|---|---|---|---|
| Brightness listener, 500 color changes an hour, default `changed` | No rows | One row an hour, count 500, filter "attribute brightness changed" | No rows |
| Same listener with `changed=True` written out | No rows | One row an hour | One row an hour |
| `changed_to="on"` rejection on the same listener | Its own row (and D3 keys rows by filter) | Its own row only if D3 keys by filter; otherwise the chatty row can overwrite it | Same as A |
| "Did the listener see events at all?" | Answered by the listener's other rows or runs; a listener that only ever fails `changed=True` shows nothing | Always answered | Answered when the caller asked for the change filter |
| Dispatch cost on those events | Rejected at scope, nothing recorded | A recorder update per event | As A by default, as B when passed |
| Signature change | None | None | `changed` defaults to the `NOT_PROVIDED` sentinel, as `changed_from` and `changed_to` already do (`bus.py:748`); `NOT_PROVIDED` behaves as `True` does today |
| Honors a caller who wrote the filter out | No | Yes | Yes |
| Redundant explicit `changed=True` (e.g. hautomate `dryer_humidity.py:62`) | No rows | One row an hour | One row an hour |

**Recommendation:** C, because a caller who writes the change filter out has asked for it, so its rejections are events the listener was about, while the default stays scope and keeps the busiest, least useful row off most listeners. A redundant explicit `changed=True` costs at most one row an hour, and D3 keeps it from burying other rows.
**Pick A instead if** you'd rather keep `changed`'s default as `True` in the signature and accept that writing it out records nothing. **Pick B instead if** "the listener saw this event and ignored it" is evidence you want even when nothing about the event was relevant.
**Reversibility:** easy (moving a filter between the two lists; the sentinel default can revert to `True`)
**Ratified:** Chose counting the change filter only when the caller passes `changed=` (the default becomes the `NOT_PROVIDED` sentinel, behaving as `True` and treated as scope), over always treating `changed=True` as scope or always counting it, so a filter the caller wrote out records its rejections and the default adds no noise, accepting a sentinel default in the signature and that a redundant explicit `changed=True` records up to one row an hour.

### D3: Does the failing filter join the rollup key?

**Situation:** parent D3 keys a row by listener, reason and hour, with the failing filter's summary as a last-value column, so when two filters reject in the same hour the row names only the later one. The parent Done-when asks "which events were dropped, by which filter", and the parent Breakdown left this to pickup. With D2's scope rule, a listener's counting filters are its `changed_from`, `changed_to`, a `changed=` the caller passed and each top-level child of its `where`, usually one to three.

**Deciding factor:** answering "by which filter" for every rejection in the hour, within a size bound close to parent D3's.

| | A: filter in the key | B: last filter as a column (parent D3) |
|---|---|---|
| Two filters reject in one hour | Two rows, each with its own count and last values | One row; count covers both; names the later filter |
| "Was it `changed_to` or `where` that blocked the 04:59 event?" | Answered | Answered only if it was the last rejection that hour |
| Key on the dispatch path | Child position in the flattened `AllOf` (no rendering); summary rendered at flush | No filter in the key |
| Expected size (90 listeners, 30 days) | About the parent's 25 MB; most listeners reject on one filter | About 25 MB |
| Bound | About 140 MB at three filters per listener, against the parent's 110 MB | About 110 MB |
| Non-filter reasons | Filter column empty | Same |
| What peers do | Kubernetes dedupes events by reason and message, so a distinct message is a distinct series | HA records the trigger's single reason |

**Recommendation:** A, because it answers the Done-when's "by which filter" without depending on which rejection came last, for about 30 MB more at the bound and nothing extra expected.
**Pick B instead if** the parent's 110 MB bound is a hard ceiling and you'd accept the row naming only the latest filter.
**Reversibility:** easy (the key widens or narrows with the unique index)
**Ratified:** Chose putting the failing filter in the rollup key over keeping it as a last-value column, so every rejecting filter in an hour has its own count and last values, accepting a bound of about 140 MB against parent D3's 110 MB. The database key is the filter's rendered summary (child position keys only the in-memory entry), so two children that render alike, such as two lambdas both summarized as `<lambda>`, merge into one row through the additive upsert; `filtering.md` suggests named functions over lambdas for that reason (chosen over a position key column at the sketch-time challenge).

### D4: How often do rollups flush?

**Situation:** the dispatch path only updates in-memory entries (parent D3), so a miss reaches the database at the next flush, and a crash loses everything since the last one. The read surface reads only the database, so the flush interval is also how long someone debugging live waits before `hassette listener <id> --misses` shows a miss they just caused. Each flush writes one upsert per entry changed since the last flush, at most listeners × reasons × filters, in one batch. Executions flush at most every 5 seconds (`database.max_flush_interval_seconds`); the failsafe and retention run hourly.

**Deciding factor:** a short wait for someone debugging live and a small crash window, without a new setting.

| | A: every 30 seconds (constant) | B: every 5 seconds (constant) | C: every 5 minutes (constant) | D: 5 minutes, and the read merges unflushed entries |
|---|---|---|---|---|
| Wait before a live miss shows | Up to 30 s | Up to 5 s | Up to 5 min | None |
| Crash loss | 30 s | 5 s | 5 min | 5 min |
| Upserts per hour for a listener that misses constantly | 120 | 720 | 12 | 12 |
| New machinery | None | None | None | A read path into `BusService`'s memory, merged with database rows |
| New setting | None | None | None | None |
| What peers do | unknown | unknown | unknown | unknown |

**Recommendation:** A, because a 30-second wait is short next to the incidents this answers (found hours or a day later), the write load is trivial, and the read stays a plain query. The docs state the interval.
**Pick B instead if** live debugging is the main use and you'd accept six times the upserts. **Pick C instead if** write load matters more than a five-minute wait. **Pick D instead if** you want both a long interval and an instant read, accepting a second read path.
**Reversibility:** easy (a constant)
**Ratified:** Chose a 30-second flush as a module constant over 5 seconds, 5 minutes, or 5 minutes with a live merge in the read, to keep the live-debugging wait and crash window short with a plain database read and no new setting, accepting up to 30 seconds before a miss shows and up to 30 seconds of rollups lost in a crash.

### D5: What reason codes are there? (refines parent D4)

**Situation:** parent D4 asks for "one stable reason code per step", and the codes become a wire `Literal`, a database `CHECK` and CLI output. Some steps drop for more than one cause. The mode guard drops when a `single` listener is busy (`ExecutionModeGuard.run_single`) or when a `queued` listener's queue is full (`run_queued`). A duration hold ends without running when a later event leaves the target state (`DurationTimer.evaluate_cancel_event`), or when the state no longer matches at fire time (`on_duration_fire`'s recheck, including an entity missing from the cache).

**Deciding factor:** each code tells the reader which setting to change, without adding codes no fix depends on.

| | A: one code per cause | B: one code per step |
|---|---|---|
| Codes | `filter`, `throttled`, `debounce_superseded`, `once_spent`, `busy` (single), `queue_full` (queued), `backpressure`, `hold_cancelled`, `hold_recheck_failed` | `filter`, `throttled`, `debounce_superseded`, `once_spent`, `mode_guard`, `backpressure`, `hold_cancelled` |
| Tells the reader what to change | Yes: `busy` points at the mode, `queue_full` at the queue cap; a recheck failure means the state moved without an event | Mode-guard rows need the listener's mode looked up; recheck failures read as cancellations |
| Count | Nine | Seven |
| Matches existing counters | `suppressed` and `dropped` on `ExecutionModeGuard` are already separate | Merges them |

**Recommendation:** A, because the existing guard counters already split busy from queue-full, and each code maps to a different fix.
**Pick B instead if** you want the shortest list and accept looking up the mode to read a mode-guard row.
**Reversibility:** easy before release; a code removed later is a wire break
**Ratified:** Chose one reason code per cause (nine codes) over one per step (seven), so each code points at the setting to change and matches the guard's existing split counters, accepting a longer code list on the wire and in the database `CHECK`, that retiring any of the nine later is a wire break, and that a `hold_recheck_failed` row doesn't say whether the state moved without an event or the entity was missing from the cache at fire time (`filtering.md` names both causes).

### D6: Does a miss row carry `caused_by`?

**Situation:** the wire reuses `ExecutionTrigger` for a row's last event (spec 147 D1 said #1817 would). That model includes `caused_by`, the API write whose context matches the trigger's (spec 149 D5), computed on read by a subquery on `api_writes` (`_CAUSED_BY_SUBQUERY`, `src/hassette/core/telemetry/execution_queries.py:45`). For a miss it answers "did my own app's write cause the event my filter then rejected", which is a known loop pattern. Leaving it out means the field is always None on miss rows, which reads as "no write caused this".

**Deciding factor:** the reused model means the same thing on every row it appears in.

(Collapsed decision: the two options are computing it and leaving it None.)

**Recommendation:** compute `caused_by` on miss reads with the same subquery, against the row's last context id, so the field means what it means on executions.
**Pick leaving it None instead if** the subquery measurably slows the misses read; the field description would then have to say it isn't computed for misses.
**Reversibility:** easy
**Ratified:** Chose computing `caused_by` on miss reads with the executions' subquery over leaving it None, so the reused `ExecutionTrigger` field means the same thing everywhere and answers "did my own write cause this rejected event", accepting one indexed lookup per row.

### D7: Which event does a hold-cancelled row record?

**Situation:** a duration hold starts on one event (the light turned on) and is cancelled by a later one (the light turned off within the hold). The event that never ran the handler is the first; the event that ended the hold is the second. A row keeps one last event's values.

**Deciding factor:** the values answer "why didn't the hold complete".

| | A: the cancelling event | B: the starting event |
|---|---|---|
| Values shown | `on` → `off` at 22:03, what ended the hold | `off` → `on` at 22:00, when it began |
| Answers "why didn't it complete" | Directly | By inference; look the cause up in HA history |
| Answers "when did the hold start" | No, but the start always matches the listener's own `changed_to` | Yes |
| `caused_by` points at | The write, if any, that ended the hold | The write that started it |
| Code | The cancel path already holds this event | The timer must keep the start event's values until cancel |

**Recommendation:** A, because its old and new values show what ended the hold, and it is already in hand where the cancel happens. The row records the `event` that `DurationTimer.evaluate_cancel_event` received, not the normalized copy it evaluates (`strip_old_state` in `src/hassette/core/duration_hold_adapters.py` sets `old_state` to None on that copy). For `hold_recheck_failed` (D5), the row records the synthetic fire-time event, which spec 147 D7 gives the real context of the change that set the cached state.
**Pick B instead if** you'd rather see when the hold began than what ended it.
**Reversibility:** easy
**Ratified:** Chose recording the cancelling event as `evaluate_cancel_event` received it, with its `old_state`, over the starting event, so the row shows what ended the hold (old and new values) with an event already at hand on the cancel path, accepting that the hold's start time isn't on the row.

## Assumed

- Parent D3 holds: an hourly rollup per listener and reason (plus filter, per D3 here), last entity and values on the row, nothing but in-memory updates on the dispatch path, values kept extracted and rendered at flush, and the existing live counters (`suppressed`, `dropped`, `backpressure_dropped`) left as they are. Evidence: parent ledger D3.
- Parent D4 holds except where D2 (the change filter) and D5 (one code per cause rather than per step) refine it: every listener-scoped drop on app listeners counts, debounce records only the superseded event, a predicate that raises already records an error execution and isn't a miss, and drops before any listener is reached are out. Evidence: parent ledger D4; `BusService._record_predicate_failure` (`src/hassette/core/bus_service.py:570`).
- Parent D5 holds: the walk flattens nested `AllOf`s, stops at the first false child, and leaves later children unevaluated; other combinators and custom callables report their own summary; a listener rejected on one route isn't evaluated again for that event. Today only raising listeners are deduplicated across routes (`failed` in `_match_listeners`, `bus_service.py:404`). Evidence: parent ledger D5.
- Parent D11 and D12 hold: the aggregator is a helper `BusService` composes, losses are `PipelineCounter` members, the table ages out on `database.retention_days`, and it is second in the failsafe order after DEBUG lines. `api_writes` sits at priority 3 today. Evidence: parent ledger D11, D12; spec 146 D3; `_RETENTION_TABLES` in `src/hassette/core/retention_targets.py`.
- Values use spec 147 D2's display strings (strings as-is, others compact JSON, cut at 255 with `…`), through `format_trigger_value`. Evidence: `src/hassette/core/execution_record_builder.py:177`.
- The duration fire-time recheck event carries the cached state's real context and the base state-changed topic. Evidence: spec 147 D7; `src/hassette/core/duration_hold_adapters.py`.
- Listener rows are stable identities upserted on registration, so a miss row's listener id stays valid across restarts. Evidence: `listeners` table (`src/hassette/migrations_sql/001.sql`, later migrations) and `TelemetryRepository`'s listener upsert (`src/hassette/core/telemetry/repository.py:85`).
- The latest migration is `024.sql`, and #3098, #3675 and #3676 are closed. Evidence: `src/hassette/migrations_sql/`; GitHub issue states.
- A benchmark harness exists: `uv run nox -s benchmarks` runs `tests/benchmarks/` serially and compares against the last saved run. Evidence: `noxfile.py` `benchmarks` session.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**

- D3 refines parent D3 by moving the failing filter from a last-value column into the rollup key: noted here, the decision body is unedited.
- `HandlerInvoker` passes its reporter and the event into `RateLimiter.call(handler, event, report)`, so the limiter holds no listener reference.
- `Listener.cancel()` unbinds `report_drop`, so a cancelled `once=True` listener's in-flight dispatch records nothing and a removed listener records nothing more: no separate "fired by dispatch" flag is needed for `once_spent`.
- Hold predicates (`hold_preds`, starting with `EntityMatches`) need no scope split: hold reasons carry no filter, so the hold predicate is evaluated whole.
- An entry keeps a reference to the last event and summarizes it at flush with `summarize_trigger`: cheaper than extracting values on dispatch, and the same code path as executions.
- The in-memory key uses the routing `listener_id` (unique per `Listener` object), not `db_id`, so a replaced listener sharing a `db_id` never mixes filter indexes; rows key on `db_id`.
- The `filter` column is `NOT NULL DEFAULT ''` for non-filter reasons, because SQLite's unique index treats NULLs as distinct; the read maps `''` to None.
- The upsert is `INSERT … SELECT … WHERE EXISTS (listener)`, so a listener deleted between record and flush skips its row instead of failing the batch on the foreign key.
- The recorder records nothing when no `DatabaseService` is wired (`Hassette.try_database_service()` returns None), which is the test harness's bus; the repository is built per flush.
- `_match_listeners` remembers scope rejections too (one `rejected` set alongside raises), since evaluation is deterministic per event.
- `hold_recheck_failed` with the entity missing from the cache records the event that started the hold, since no state exists to build a fire-time event from.
- `Listener.predicate` stays the caller's filters; `filters` is derived in `__post_init__`; `full_predicate` rebuilds the combined predicate only for the registered description, so registered descriptions are unchanged.
- `Listener.evaluate` returns ints (`MATCHED=-1`, `OUT_OF_SCOPE=-2`, else the filter index) to keep the dispatch path allocation-free.
- `hold_matches`/`evaluate_predicate` return None on a raising predicate so the recheck can tell a raise (an error execution, not a miss) from a mismatch.
- CLI miss table columns: Hour (local, from `hour_ts`), Reason, Filter, Count, Last, Entity, Old → New. `fmt_hour` and `fmt_change` live in `cli/formatters.py` with the other column formatters.
- `caused_by_subquery()` became the template constant `CAUSED_BY_SUBQUERY` (formatted with the table alias), since module-level SELECT lists are built from it at import.
- A failed flush passes its exception to `count_loss`, which logs it with `exc_info`; the WARNING is paced by `lifecycle.command_executor_capacity_warn_rate_limit_seconds`, like the execution queue's capacity WARNING.
- Client-compat fixtures request `/misses` for a listener that has miss rows (`SeedIds.missed_listener_id`), falling back to any listener; the healthy seed scenario gives `plant_monitor`'s state listener an hour of rows.
- The generated `Bus` sync facade's header imports `ComparisonCondition` and `FalseySentinel` under `TYPE_CHECKING`, since `changed`'s annotation is now a string.
- Benchmark (`tests/benchmarks/test_bench_listener_matching.py`, 20,000 rounds, same machine, medians in µs): two filters, the expensive `StateTo` and a `where` lambda that returns False (the cheap case, where recording is the largest share it can be). The pre-change commit (0619cc39, with the cheap case added) and this branch were run twice each, alternating. Pre-change: 120.69/118.54 (expensive), 116.31/118.25 (cheap). Branch without a reporter: 117.73/114.69, 109.60/112.58; with a `ListenerMissRecorder` bound: 119.63/122.15, 114.79/112.78. Repeat runs of one build differ by 2–5 µs, so against the pre-change commit, recording is within noise. The largest delta between paired runs is 5.2 µs, 4.7% of the cheap pass, under parent D3's 10% limit. Routing, not the filter, dominates the pass, so the cheap filter barely changes the denominator.
- `DurationHoldManager` reads `listener.invoker.report_drop` when the hold fires rather than taking an injected reporter (the Summary says injected), because it already holds the listener and reading at fire time picks up `cancel()`'s unbinding; `DurationTimer` has no listener, so it gets the injected `on_hold_cancelled` closure, which also reads the reporter at call time.
- `CLI` old → new rendering is one helper, `fmt_value_change` in `cli/formatters.py`, shared by `hassette log`'s trigger summary and the miss table.
- Ship-time challenge Finding 3 (user's choice): a submit `TimeoutError` or `sqlite3.OperationalError` merges the batch back into the entry map instead of dropping it, folding into any entry recorded since the swap (that newer entry keeps its last event). The shutdown flush passes `final=True`, which counts such a failure as a loss, since no later flush would write a merged-back batch. `MAX_FLUSH_RETRIES` (3, the execution flusher's bound) caps consecutive merge-backs, so a database that stays read-only or full reaches the failure counter. A merge-back logs its own unpaced WARNING (at most three per episode), so it never suppresses the paced loss WARNING.
- Comb minor findings 2 (duplicated facts: the 10% limit, failed flush, migration chain) were left as is: cosmetic, and each restatement is consistent.

## Addendum

- 2026-11-12 (PR #4013 review): an `immediate=True` listener whose cached state a filter rejects records a `filter` near-miss with `is_synthetic=True`. Synthetic events never pass through `BusService._match_listeners`, so `DurationHoldManager.immediate_fire_task` reports it itself; both sites decode the `Listener.evaluate` result through `Listener.report_filter_rejection`. The miss table's Hour column shows local minutes, so a half-hour-offset zone reads `05:30`, not `05:00`.
