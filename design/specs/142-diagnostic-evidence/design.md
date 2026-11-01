# Design: Diagnostic Evidence

**Date:** 2026-11-01
**Status:** ratified
**Mode:** sketch
**Issues:** #3675, #3676, #1817, #3677, #3678, #3679 (milestone *Diagnostic Evidence*)
**Prior art:** design/research/2026-11-01-diagnostic-evidence/prior-art.md

## Summary

People open Hassette after something happened that shouldn't have, or didn't happen when it should have. Of 13 investigated incidents, 8 were "didn't happen", and the evidence that settled them usually lived outside Hassette: app source, Home Assistant history, `docker logs`. Hassette records runs, but not the events a listener rejected, what triggered a run beyond a context id, what a run asked Home Assistant to do and how that ended, or connection and lifecycle history. The question list and per-step inventory are in the 2026-11-01 diagnostic questions research, kept in the Dotfiles repo.

This milestone records that evidence and exposes it through the API and CLI. The web UI redesign displays it later and is out of scope.

New pieces and their homes:

- **Near-miss rollups:** a new telemetry table owned by the listener's identity row, fed from the bus dispatch path through an in-memory aggregator composed by `BusService` (D3, D4, D5, D11).
- **Trigger detail:** new columns on executions (D6).
- **API write records:** a new telemetry table, written when each write's outcome is known, linked to the calling execution when there is one, through one write function (D7, D8, D11).
- **Framework timeline:** one append-only lifecycle table in the shape #1446 plans for `app_status_events`, written through `SessionManager` from an app state subscriber, `OutageLog` and block reconciliation (D1, D2, D11).
- **Debug-line retention tier:** a new retention target on log records (D9).
- **Per-app debug capture:** a runtime switch held by the app lifecycle and reached through `hassette app debug` and a matching API route, plus a per-app exception held by the log persistence path (D10).
- **Read surface:** additions to the telemetry API, the wire package, the client and the CLI (D13).

Out of scope: raw event or state storage (a stored event history gets its own follow-up issue, filed with the Breakdown, as does one to stop documenting `Api`'s raw methods), embedding Home Assistant history, app-internal state, the log-trust issues (#2839, #3188, #345), and all web UI work, including #1817's dashboard criterion.

## Posture

- **Failure handling:** recording is best-effort and can never affect dispatch or a handler. A failed or overflowing write is counted, with one WARNING per episode, the same way the execution pipeline handles drops. It isn't retried. Driven by the existing pipeline and by Home Assistant and Kubernetes treating this kind of record as best-effort.
- **Compatibility:** clean breaks; the project is pre-V1. New tables and columns start empty with no backfill. Wire changes are additive and go through the released-client compatibility check.
- **Scope:** only what the milestone's Done-when asks for.
- **Rollout:** on by default with no feature flag. Migrations chain after the instance-name migration (#3098).
- **Hardening:** project defaults, with one exception: the dispatch path and database growth get stated limits that a test or measurement can check, because this adds work for every rejected event. D9 states how far a debug capture can overshoot the size limit.
- **Altitude:** `milestone`; most issues get built after #3098, #3099 and #3100 move this code, so the ledger names concepts and ends in an issue breakdown.

## Decisions

### D1: Where does connection, restart and lifecycle history live?

**Situation:** the milestone needs "what connection, restart and app lifecycle events happened around a given time". Today that means scattered log lines, some at DEBUG and most hidden by the default log view; outage state and service status live only in memory. #1446 would record this as `app_status_events`, but it's a large single-writer projector for *current* state, sits in the later *DB as Source of Truth* milestone, and is blocked by #2695, #2938 and what remains of #2990 (its heartbeat, starvation fix and registry have landed; the counter migration in #3280 hasn't). Its ledger chose an append-only history table as a side effect of the projector.

**Deciding factor:** one table at the end and a #1446 rework limited to swapping a writer, without taking on current-state projection the Done-when doesn't ask for.

| | A: one lifecycle table in #1446's shape, event writer now | B: pull #1446 and its blockers in | C: derive from logs | D: move #2938 and #2990 first, then A's table | E: small table with its own schema |
|---|---|---|---|---|---|
| Size of work | One table, one subscriber, three call sites | Large: #1446 itself, plus its remaining blockers; moves a Later initiative ahead of the roadmap's one Now | Smallest: raise some lines to INFO and tag them | A plus #2938 and the remaining #3280 migration, about 25 files, which a table doesn't need | Same as A |
| Answers the Done-when | Yes | Partly: app status history yes, but connection is stored only as current state on the session, so outage history still needs new writers | Only while log settings keep the lines | Yes | Yes |
| Depends on log level | No | No | Yes: `log_level = WARNING` loses INFO lifecycle lines | No | No |
| Missed-transition risk | App rows covered whenever a transition sends the state event | Lowest: the projector diffs state | Each transition must log | Same as A | Same as A |
| Work when #1446 lands | Replace the app row writer; connection writer stays; rows move from per event to per observed change | None | #1446 still adds a table | Same as A | Schema migration and writer rewrite |
| What peers do | Prefect and Kubernetes keep a separate event stream with a TTL | Airflow keeps a mutable heartbeat row for liveness only | unknown | Same as A | Same as A |

**Recommendation:** A. One lifecycle table, generalized from #1446's `app_status_events` by a `kind` column and keyed by session id and instance name. Its retention follows the #1446 ledger's D25 (spec 132), and the projector later replaces the event writer for app rows. Spec 132 (`db-source-of-truth`)'s D2 and D25 carry amendment notes that match.
**Pick B instead if** you've decided to move DB as Source of Truth up regardless, and accept a separate connection writer anyway. **Pick C instead if** you'd accept losing lifecycle history whenever someone raises the log level, in exchange for no new table. **Pick D instead if** you want #2938 fixed first regardless. **Pick E instead if** you expect #1446 to be dropped or redesigned.
**Reversibility:** easy (nothing depends on the table until #1446)
**Ratified:** Chose one lifecycle table in #1446's shape with an event writer now, over pulling #1446 forward, deriving from logs, moving #2938 and #2990 first, or a separate schema, to end with one table and a writer-only rework at #1446, accepting that app rows change from per event to per observed change when the projector takes over. App status rows ship in this milestone, because the Done-when asks for them and #1446 is in Later.

### D2: Which events go on the timeline, and where does each come from?

**Situation:** every extra kind of event adds a writer to keep correct and more rows. Incidents needed: did a reconnect or restart interfere (6 of 13), and what happened to this app. Most app transitions already send a state event, from about ten lifecycle sites. Connection facts live whole in `OutageLog`; connection bus events miss an outage that starts during startup, carry no outage length, and produce a pair per flap. Framework service status events can't tell an app's child resources from the framework's (#2938). Required framework services end the process when they fail, and the session row records why; only the two optional watchers survive a failure, and they log at ERROR.

**Deciding factor:** each row kind comes from wherever the fact already exists whole, with the fewest kinds and call sites that answer the incident questions, and the timeline never presents an inference as a fact.

| | A: connection and app status; subscriber plus `OutageLog`; block changes recorded | B: subscriber on all topics, plus block calls | C: call-site writers | D: A plus framework service failures, requiring #2938 |
|---|---|---|---|---|
| New lifecycle path covered automatically | Yes, if it sends the state event | Yes, if it sends the state event | No | Same as A |
| Outage that starts at startup | Recorded | Missed | Recorded, if wired at `OutageLog` | Recorded |
| Outage length in the row | Yes | Needs subscriber-side timing | Yes | Yes |
| Block, unblock, needs-restart | Recorded: block changes as diffs between reconciliations, needs-restart on the failed row | Recorded | Recorded | Recorded |
| Watcher failure | ERROR log line | ERROR log line | ERROR log line | Timeline row too |
| New call sites | Three | Three or more | About ten or more | Three, plus #2938 first |
| What peers do | Airflow 3 lost transitions that weren't wired in (PR 61932) | Same | Same risk, most exposed | Airflow and Prefect record state transitions, with no separate service-failure kind in the brief |

**Recommendation:** A. App rows come from one subscriber to app state events, by the mechanism D11 leaves to pickup; connection rows from `OutageLog`'s failure and recovery points; block and unblock changes from the place that reconciles them. A needs-restart flag travels on the failed row, read from the registry when the event is handled. Rows store kind, session id, subject (app and instance name, or none), from and to status, a short detail (such as outage length), and a timestamp. Session starts and ends are read from `sessions`, not copied. App stop events must reach the writer (D11). A transition that sends no state event leaves no row, so the timeline issue checks each transition and names any that don't send one.

The timeline makes no claim about what was up. It shows recorded rows and session boundaries, marks unclean ends from the session's status, and shows the live session's loss count, so "last row, then session ended unclean" is the reader's conclusion to draw. An unclean end's time is the session's last heartbeat; the crash itself came up to one heartbeat interval later, and the timeline says so. A dropped row is lost and counted, per the Posture.

**Pick B instead if** you never expect to need outages that begin during startup. **Pick C instead if** the bus proves unavailable at the moments you need rows. **Pick D instead if** you've been caught by a dead file watcher; adding the kind later doesn't change the table, and #2938 can land independently either way.
**Reversibility:** easy (adding event kinds later doesn't change the table)
**Ratified:** Chose connection and app status rows, from one subscriber, `OutageLog`, and block diffs, with no claim about what was up, over all-topic subscribers, call-site writers, or framework service failures, to answer the incident questions with few writers and no false answers, accepting that watcher failures stay in the logs, "was it up" is read from rows and session boundaries, and an unclean end's time is the last heartbeat rather than the crash itself. #2938 stays independent of this milestone.

### D3: How are near-misses stored and bounded?

**Situation:** an event that reaches a listener but gets rejected leaves nothing unless DEBUG is on. #1817 asks for a counter, and the question map also needs "which gate, with what values". Volume is the risk: `on_state_change("sensor.power", changed_to=...)` can reject an event every second, and direct peers record nothing at all. Only Home Assistant records near-misses, in a separate bucket of 5 for selected cases. The clearest incident (3534e408) was one rejected event at 04:59:29, found by the person the next morning.

**Deciding factor:** a hard size limit with no new settings, keeping exact values for rare misses and days of pattern for chatty ones.

| | A: hourly rollup by listener and reason | B: per-listener counter plus ring of recent rows | C: per-listener counter only | D: every miss as a row, short TTL | E: daily rollup per entity | F: hourly per entity, globs opt in | G: drop it, use HA history |
|---|---|---|---|---|---|---|---|
| Stored per | Listener, reason, hour; last entity and values on the row | Lifetime counter; last N misses per listener | Lifetime counter | Each miss | Listener, entity, reason, day | Listener, entity, reason, hour | Nothing |
| 3534e408 (one miss, next morning) | Exact: it's the only one that hour | Exact, unless N newer misses pushed it out | Count only | Exact | Time only; values from HA | Exact | By hand from source and HA |
| Chatty sensor, one specific miss | Count, first and last time, last values | Lost after N more misses | Count only | Exact until TTL | Same as A, by day | Same as A | From HA |
| Pattern over days (3 incidents) | Yes, by hour | No | No | Only within TTL | Yes, by day | Yes, by hour | Manually |
| Which filter or step rejected it | Yes | Yes | Yes | Yes | Yes | Yes | No |
| Size at 90 listeners, 30 days | About 100k rows, 25 MB expected (about 1.5 active reasons per listener); bound about 450k rows, 110 MB | Fixed: 90 × N | 90 rows | Millions | About 4k rows, unbounded for fan-out listeners | About 100k rows expected, unbounded if opted in | None |
| New setting or warning | None | None | None | None | None | One of each | None |
| What peers do | Kubernetes dedupes with a count and first and last time | HA's bucket of 5 is a ring | EventBridge counts the matched side only | None found | Same as A | None found | AppDaemon, NetDaemon: nothing recorded |

**Recommendation:** A, because one row shape does the counter, the values and the pattern, and listeners × reasons × hours is a limit no listener can exceed. Glob and base-topic listeners get one row per reason per hour, not one per entity, and single-entity listeners lose nothing. A row's reason is D4's step code; the failing filter's summary is a last-value column, so when two filters reject in the same hour, the row names the later one. For a per-event view of a chatty listener's filter rejections, debug capture (D10) records each evaluation through the app's own bus logger. Throttle and debounce drops log on a shared logger that capture leaves out, so rollups are their only record. The dispatch path only updates an in-memory entry, with no I/O and no rendering of the whole event; entries flush periodically, so a crash loses the unflushed window. The near-miss issue states the flush interval, which is the length of that window. The limit on the dispatch path: the miss path may add at most 10% to rejected-event dispatch. It renders no summary per miss, keeping a reference to the failing filter and rendering at flush, and it keeps extracted values, not event references. The listener counters that exist today (`suppressed`, `dropped`, `backpressure_dropped`) stay as exact per-session totals, which #1446 persists; rollups are the best-effort detail behind them, and can read lower when evidence was lost.
**Pick B instead if** you care more about the last few individual misses than about patterns over days. **Pick C instead if** you'd rather stop at #1817's original scope. **Pick E instead if** about 25 MB expected, about 110 MB at the bound, is too large and you'd accept going to HA for values. **Pick F instead if** per-entity history on globs justifies a setting. **Pick G instead if** rejected events aren't worth recording at all. **Pick D instead if** exact history of every miss matters more than days of pattern, and millions of rows are acceptable.
**Reversibility:** easy (new table; retention ages out rows)
**Ratified:** Chose an hourly rollup keyed by listener and reason over per-entity rollups, glob opt-in, counters, rings, a row per miss, or relying on HA history, to get a hard size limit with no settings, accepting that a glob or base-topic listener keeps only its last entity per hour, that the bound is about 110 MB against about 25 MB expected, and that one dropped flush loses that window's rollups for all listeners, with the counter recording the drop.

### D4: Which rejections count as near-misses?

**Situation:** a listener can drop an event at several steps: its filter (`changed=`, `changed_from`, `changed_to`, `where`), throttle, debounce superseding an earlier event, a spent `once`, an execution-mode guard, backpressure, or a duration hold being cancelled. Each is a silent or DEBUG-only drop today. Home Assistant reports only "interesting" cases, which leaves you unable to tell "evaluated and silent" from "not evaluated". Framework-owned listeners also exist and get evaluated constantly.

**Deciding factor:** "why didn't it run" must have an answer whichever step dropped it.

| | A: every listener-scoped drop, app listeners only, selection filters are scope | B: filter rejections only | C: every drop, framework listeners too | D: A, but selection-filter rejections count as misses |
|---|---|---|---|---|
| Throttle or mode-guard incidents | Answered | "No miss recorded" misleads | Answered | Answered |
| Rows | Moderate | Fewest | Most, with no diagnostic value for users | Moderate, plus one per reason per hour per filtered listener |
| Places that report | About seven | One | About seven | About seven |
| Unrelated service call on a filtered `on_call_service` listener | Not recorded | Not recorded | Not recorded | Recorded as a miss |
| Mistyped domain or service on `on_call_service` | No miss shown | No miss shown | No miss shown | Miss shown |
| What peers do | No peer covers this much | HA reports selected trigger cases | None | No peer covers this much |

**Recommendation:** A, with one stable reason code per step. A rejection by a filter the registration method built to select events (entity, domain, service, component) is the listener's scope, not a miss, and isn't recorded; so `on_call_service(domain="light", service="turn_on")` doesn't record every unrelated service call. A user's `where` and the change filters still count as misses. The near-miss issue settles how the walk in D5 tells these apart, since both are children of the same `AllOf`. Debounce records only the superseded event. Drops before any listener is reached (the global exclusion filter, events before the connection is ready) aren't listener-scoped and stay out. A predicate that raises already records an error execution and doesn't count.
**Pick B instead if** you'd accept that a throttled event looks like one that never arrived, for fewer places to maintain. **Pick D instead if** you'd rather see a rejection for a mistyped domain or service, since the scope rule hides exactly that. **Pick C instead if** framework listeners' drops start explaining user incidents.
**Reversibility:** easy (reason codes can be added)
**Ratified:** Chose recording every listener-scoped drop for app listeners, with one reason code per step and registration-built selection filters treated as scope, over filter rejections only, including framework listeners, or recording selection rejections too, so "why didn't it run" has an answer whichever step dropped the event and a miss row means an event the listener was about, accepting about seven reporting points and that a mistyped domain or service on `on_call_service` shows no miss.

### D5: How does a rejection name the filter that failed?

**Situation:** a listener's filters combine into one `AllOf` predicate, and `Listener.matches` returns only true or false. To say which filter failed, something has to look inside. Predicates already have `summarize()`, and a custom callable summarizes as "custom condition" or its callable name. User predicates may have side effects or be expensive, so running them twice is a risk. On the live database, the 56 of 60 app listeners that have a predicate are all a top-level `AllOf`, because the bus builds one from the registration's filters. A domain-wide glob such as `sensor.*` is reached through two routes, and today a rejection isn't remembered between them, so its predicates run twice for one rejected event.

**Deciding factor:** naming the failing filter without calling any predicate twice.

| | A: walk the top-level `AllOf` in `matches`, remember the rejection across routes | B: re-evaluate children after a miss | C: no attribution; store the whole predicate summary and the event values | D: A's walk, keeping today's second evaluation and documenting doubled counts |
|---|---|---|---|---|
| Says which filter failed | Yes | Yes | No; the reader compares by hand | Yes |
| Calls user predicates twice | No | Yes, on every miss | Only on a glob's second route, as today | Only on a glob's second route, as today |
| One rejected event on `sensor.*` | One miss | One miss | Two misses | Two misses |
| Change | A few lines in one place, plus a few lines in dispatch | Similar, plus a second pass | None | A few lines in one place |
| Dispatch behavior change | Removes today's second call | Adds a call on every miss | None | None |
| Stale result risk | None | Time or state may differ on the second call | None | Second route's walk may differ |
| What peers do | HA: the trigger itself reports a reason code | unknown | EventBridge: compare the event to the pattern by hand | unknown |

**Recommendation:** A. `Listener.matches` walks the `AllOf`'s children, flattening nested `AllOf`s, and stops at the first false, reporting that child's summary. Other combinators need no change: a failed `AnyOf` means every branch failed, and a failed `Not` means its inner predicate passed, so their summaries are complete. A predicate that isn't an `AllOf` reports its own summary. A custom callable reports its name. Later filters stay unevaluated, as they are today. A listener rejected on one route isn't evaluated again for that event, because a domain-wide glob such as `sensor.*` is reached through both the entity and domain routes; this makes one rejected event one miss and one predicate call, and removes today's second call.
**Pick C instead if** the walk breaks D3's 10% limit on the dispatch path. **Pick D instead if** you want this milestone's dispatch change to touch only recording. **Pick B instead if** you need every filter's verdict and accept calling user predicates again.
**Reversibility:** easy (internal)
**Ratified:** Chose walking the top-level `AllOf` in `matches` and remembering a rejection for the rest of that event's routes, over a second evaluation, no attribution, or documenting doubled counts on domain-wide globs, to name the failing filter with no predicate called twice per event, accepting that a custom callable reports only its name, later filters stay unevaluated, and dispatch behavior changes by removing today's second call.

### D6: What does an execution store about its trigger?

**Situation:** an execution stores `trigger_context_id` and `trigger_origin`, but not the topic, entity, or old and new values, so a wildcard listener's run can't tell you which entity fired it. Near-miss rows (D3) need the same facts. Separately, state changes carry the context id of the service call that caused them (up to 5 seconds on the Home Assistant side), so storing returned context ids (D8) makes "this run was caused by that run" answerable.

**Deciding factor:** answering "which event triggered this" with a small row, using one shape for executions and near-misses.

| | A: event summary as columns | B: side table, one row per execution | C: full event JSON, capped | D: stored event table, one row per event |
|---|---|---|---|---|
| Fields | Event type, entity id, old and new value, context id and parent id | Same | Everything, including all attributes | Same as A, shared by the runs an event triggered |
| Query simplicity | No join | One join | JSON parsing | One join |
| Rows using the fields | 29% of the table: jobs (71% on the live DB) leave them empty, costing about 0.4 MB in total | 100% of that table | Handler rows only | 100% of that table |
| Size per handler run | About 100 bytes; about 3.4 MB over 30 days on the live DB | Same plus a key and index | Often kilobytes | Same plus a key and index, less when one event triggers several listeners |
| Trigger facts in one place | Yes, with the existing trigger columns | Only if those move too | Yes, with the existing trigger columns | Only if those move too |
| Retention | Follows executions | New target or a delete in step | Follows executions | New target that must outlive its runs |
| A `where=` on an attribute the listener doesn't track | Value not shown | Value not shown | Shown, if under the cap | Value not shown |
| What peers do | n8n and Temporal keep full input with the run and hit size limits | unknown | Same as A's note | unknown |

**Recommendation:** A. For attribute listeners, old and new hold the tracked attribute's values; long values are truncated, at a limit the trigger-detail issue names. The execution read reports `caused_by` when its trigger context id matches a recorded API write. The field description says it means "same Home Assistant context id, best-effort": a match can be wrong if an unrelated update lands within Home Assistant's 5-second window, and absence proves nothing, because it also follows a rejected or unresolved write, a lapsed window, or an entity that wasn't directly targeted. The wire model presents these as one nested `trigger` object, absent on jobs. Option D is the start of a raw event store and is out of scope; it is tracked as a follow-up issue and can absorb these columns.

The name `caused_by` was weighed against `same_context_as`:

| | `caused_by` | `same_context_as` |
|---|---|---|
| Accurate on a false match | No; the description has to correct it | Yes |
| Legible at a glance in the CLI | Yes | Needs a moment |
| Fits D13's "doesn't draw conclusions" | Weakly | Yes |

**Pick B instead if** you expect the trigger fields to grow well beyond this list. **Pick C instead if** you often need attributes that aren't the tracked value, and accept the growth. **Pick `same_context_as` instead if** output is often taken literally and the name itself should carry the caveat. **Pick D instead if** you're building stored event history in this milestone anyway.
**Reversibility:** easy (nullable columns)
**Ratified:** Chose event summary columns on executions over a side table, a stored event table, or full event JSON, to keep every trigger fact together and aging out with its run, and kept the name `caused_by` over `same_context_as` because the plain word serves the person checking "did my app do this", accepting empty columns on job rows, values repeated when one event triggers several listeners, and a name that the field description has to qualify.

### D7: How does a fire-and-forget service call learn how it ended?

**Situation:** by default `call_service` sends and returns. Home Assistant's reply finds no pending entry and is ignored, so a rejected call is invisible. Home Assistant always replies, after the service handler finishes, with a context id on success and an error code on failure. `wait_for_ack=True` exists but makes the handler wait.

**Deciding factor:** learning every outcome without changing how long handlers take.

| | A: track every reply in the background, no deadline | B: make waiting the default | C: record the send only | D: A plus a long deadline; a late reply updates the row | E: A plus a pending row at send, updated on reply |
|---|---|---|---|---|---|
| Answers "how did it end" | Yes | Yes | No: fails the Done-when | Yes, after a correction if the update lands | Yes |
| Handler timing | Unchanged | Handlers wait for slow devices | Unchanged | Unchanged | Unchanged |
| Rejected call visibility | Row plus a framework WARNING | Exception in the handler | None | Row plus a framework WARNING | Row plus a framework WARNING |
| Behavior change for users | One new WARNING line for rejected calls | Breaking; new exceptions in existing handlers | None | One new WARNING line for rejected calls | One new WARNING line for rejected calls |
| Slow call that succeeded | `success`, with the true reply time | Handler waits, then `success` | Unknown | Temporarily timed out, then corrected | Pending, then `success` |
| New machinery | One cap on the existing table | None | None | Timer or sweeper, row update path, cap | Row update path, cap |
| Writes per call | One | One | One | One, sometimes two | Two; a dropped second write leaves a row stuck at pending |
| Call still in flight | No row until it resolves | No row until it resolves | Row at send | Row after the deadline | Visible as pending |
| What peers do | Temporal and Step Functions record typed outcomes per call | unknown | NetDaemon: no per-call record | Temporal records `TimedOut` against a timeout the caller chose | Temporal appends scheduled and completed as separate events |

**Recommendation:** A. Every call gets a pending entry; when it resolves, one row is written with an outcome of `success`, `rejected` (with Home Assistant's code and message), or `connection_lost`, meaning outcome unknown because the connection ended before a reply. There is no deadline and no timed-out outcome: Home Assistant replies only after the handler finishes, however long that takes, so a timer would store a false outcome for a slow call that succeeded. An entry lives until its reply or the end of the connection, in the existing pending-reply table with a cap; an evicted call leaves no row, only a count as a `PipelineCounter`. The caller's execution id is captured at send time, so the WARNING and the row both carry it. Callers that already wait keep getting exceptions as they do today. "Success" means Home Assistant's service handler returned, not that the device changed; docs say so.
**Pick B instead if** you want rejected calls to raise by default, which is a separate breaking decision worth its own issue. **Pick C instead if** knowing a call was sent is enough, which the Done-when rules out. **Pick D instead if** you want a stored signal for calls silent for a long time, and accept a sweeper and a row update path. **Pick E instead if** seeing in-flight calls, or evidence of a call in flight at a crash, is worth two writes per call.
**Reversibility:** easy
**Ratified:** Chose tracking every `call_service` reply in the background, with no reply deadline and no timed-out outcome, over making waiting the default, recording only the send, a long deadline with row updates, or a pending row at send, to learn every outcome without changing handler timing and without storing an outcome that later proves false, accepting one new WARNING for rejected calls, that success means only that HA's handler returned, and that a call in flight has no row until it resolves.

### D8: Which API writes get a record, and what does it contain?

**Situation:** "what did this run ask Home Assistant to do" needs at least the call and its target. One incident (a light set to the wrong colour) would need the data too, which can hold notification text and other personal content; logs in the same database can already hold such content. `Api` has five kinds of named write: `call_service`, `set_state`, `fire_event`, `delete_entity`, and the helper client's writes (create, update and delete). It also has public raw methods (`ws_send_and_wait`, `ws_send_json`, `post_rest_request`) that carry reads as well as writes. Hassette's real callers are in other repositories, so what one user's apps call isn't evidence of what matters.

**Deciding factor:** every write the framework can name gets recorded, with no guessing about what a raw message means.

| | A: every named write | B: named writes plus all raw calls | C: every call that isn't a known read | D: `call_service` and `set_state` only | E: `call_service` only, no data |
|---|---|---|---|---|---|
| Wrong-colour incident | Answered | Answered | Answered | Answered | Not answered |
| "Who wrote this sensor?" | Answered | Answered | Answered | Answered | Not answered |
| Raw write by a user | Not recorded; the write-record docs say so | Recorded | Recorded | Not recorded | Not recorded |
| Raw read by a user | Not recorded | Recorded as if a write | Recorded unless on the list | Not recorded | Not recorded |
| Sites | About five | About seven | Two, plus a read list that goes stale | Two | One |
| Personal content in the DB | Up to the cap; docs state it | Up to the cap | Up to the cap | Up to the cap | None |
| What peers do | Temporal records all activity input, by type; HA warns that traces can hold sensitive data, and doesn't redact | unknown | unknown | unknown | NetDaemon: nothing |

**Recommendation:** A, in a table named for what it holds, with a `kind` column. Rows hold app key, instance name, execution id (empty for calls outside a run, such as `on_initialize`), kind, target, data as the caller passed it truncated at 2 KB, outcome, Home Assistant's returned context id where it returns one, and send and reply times. Only app-owned `Api` instances record. `render_template` POSTs but only reads, so it's excluded. Every kind records through the one write function (D11). Only `call_service` needs background tracking (D7); an awaited write takes the same outcomes from what its call returns or raises, with `rejected` for an error response and `connection_lost` for a request that ended with no response. The rejected-call WARNING is specific to `call_service` because the others already raise into the caller. A follow-up issue stops documenting the raw methods, which shouldn't be treated as public API.
**Pick B instead if** users commonly write through raw methods and reads appearing in the record is acceptable. **Pick C instead if** complete coverage matters more than keeping a read list current. **Pick D instead if** you'd rather start small; adding kinds doesn't change the table. **Pick E instead if** you don't want this data in the database at all.
**Reversibility:** easy
**Ratified:** Chose recording every named write with capped data over adding raw calls, a read list, or fewer kinds, to cover every write the framework can name without guessing, accepting that raw-method writes aren't recorded, that the data can hold personal content up to the cap, and that CLI output can include that data, with docs saying to check it before sharing.

### D9: How are persisted DEBUG lines retained?

**Situation:** `log_records` has one retention window and is exempt from the size failsafe, on the grounds that it is tiny and holds the evidence for diagnosing an overage. That holds only while DEBUG lines aren't stored. With persisted DEBUG lines filling the database, the failsafe deletes executions to make room and never touches them. On the live DB, `log_records` is already 7.1 MB against 9.8 MB for the `executions` table, with no DEBUG rows. `executions` already has separate retention targets per tier. A user with few apps has no size pressure, and may be a new user who needs these lines most.

**Deciding factor:** debug lines never cost real evidence, and nobody loses logs they had room to keep.

| | A: same age, first out by size, outside the shared budget | B: 48 hours, first out | C: new setting for debug age | D: no change | E: A's age and order, plus a row budget at write time |
|---|---|---|---|---|---|
| Small install | Keeps `log_retention_days` | Loses them at 48 hours | Keeps them unless lowered | Keeps them | Keeps them, up to the budget |
| Executions protected from debug lines | Yes | Yes | Yes | No | Yes |
| Forgotten capture | Fills to the size limit, then churns | Clears within 48 hours | Same as A unless lowered | Can erase execution history | Newest lines dropped and counted above the budget |
| Capture over about 3 lines a second | Debug target is outside the failsafe's shared 10,000-rows-an-hour budget, so each run clears it; overshoot is at most one failsafe interval of capture | Outruns the shared budget within the window | Same as A | Grows; nothing can delete it | Bounded by the budget |
| Setting needed | No | No | Yes | No | No, but a budget and a check on each batch |
| What peers do | Unknown: no surveyed peer evicts debug by size | Seq: Debug at 48 hours, the rest at 30 days | Loki: `retention_stream` by selector | Dagster warns against debug; `event_logs` grows unbounded | Kubernetes rate-limits and silently drops the tail |

**Recommendation:** A. DEBUG lines become their own failsafe target, first in the order, and age out on `log_retention_days` like other log lines. They don't draw on the failsafe's shared row budget: each run deletes them until live data is under the limit, so `max_size_mb` overshoots by at most one failsafe interval of capture. A long run holds the single database writer for longer, which is accepted. INFO and above stay exempt from the failsafe. The deletion order is what protects executions, so no separate age is needed. The issue also corrects the docs' "rounding error" description of the table.
**Pick B instead if** low disk use after a forgotten capture matters more than keeping logs on small installs. **Pick C instead if** people want shorter debug retention without changing all logs; it can be added later. **Pick D instead if** you drop per-app capture. **Pick E instead if** a long failsafe run holding the writer proves worse than losing the newest lines.
**Reversibility:** easy (retention rules; no schema change beyond an index if needed)
**Ratified:** Chose keeping DEBUG lines on the normal log age and deleting them first by size, outside the failsafe's shared row budget, over a 48-hour limit, a new setting, a write-time row budget, or no change, so debug lines never cost real evidence and small installs keep what they have room for, accepting that a forgotten capture fills to the size limit and churns there, overshooting by at most one failsafe interval of capture, with a longer failsafe run holding the writer.

### D10: How is one app's debug capture turned on and ended?

**Situation:** the Done-when needs full debug logs for one app at runtime, without a restart. Today `PUT /api/logs/level` changes one logger by name, not in the CLI; an app reload resets it; and `log_persistence_level` is global, so the lines still don't reach the database unless it was set at startup. Shared services' DEBUG lines aren't per-app (accepted in spec 133 D4). No peer auto-expires debug: Spring and Envoy reset by hand, and HA's toggle turns off after a second restart.

**Deciding factor:** one action that turns on what's needed, and that's visible if left on.

| | A: per-app switch, ended by off or restart | B: A plus an auto-expiring timer | C: document the existing endpoint and config |
|---|---|---|---|
| Works without restart | Yes | Yes | No: persistence level needs a restart |
| Survives app reload | Yes: the lifecycle reapplies it | Yes | No |
| Forgotten switch | Fills to the size limit, then churns (D9); executions stay protected; ends at restart | Ends itself | n/a |
| Extra machinery | Switch state plus a persistence exception | Plus a timer | None |
| What peers do | Spring, Envoy, HA: no timer | No peer found | AppDaemon: per-app config, applied on reload |

**Recommendation:** A: `hassette app debug <app> on|off` and a matching API route, covering all of the app's instances unless `--instance` narrows it, as on other commands. It sets the app's own logger and its owned framework loggers, including its bus logger, to DEBUG, and lets that app's lines past the persistence level. The state lives in memory and never touches config, so a restart ends it, and turning it off returns levels to what config says, not to INFO. An app configured at DEBUG stays at DEBUG; its lines just stop reaching the database. Turning it on logs a WARNING, and the app status read shows it's on, so a forgotten capture is visible. `hassette log` gains `--level`. Shared-service DEBUG stays out, including throttle and debounce lines; D3's rollups cover those drops on app listeners.
**Pick B instead if** a forgotten capture sitting at the size limit bothers you more than carrying a timer. **Pick C instead if** a restart to start capturing is acceptable and you want no new code.
**Reversibility:** easy
**Ratified:** Chose a per-app switch ended by off or restart, over adding a timer or documenting the existing endpoint, to capture one app's debug logs with one action, accepting that a forgotten capture sits at the size limit until it's turned off or Hassette restarts.

### D11: Where do the new evidence writers live?

**Situation:** near-misses need an in-memory aggregator with a periodic flush; they are the only buffered writer. API write and timeline rows are written one at a time, and the database write queue already counts its own drops. `BusService` already composes helpers such as its duration hold and event filter, and it stops before the database. `SessionManager` already holds the session id and a database reference, and it stops last. `PipelineCounters` is already the one registry for loss counts. Listeners on Hassette's own bus are removed before apps stop, and `SessionManager` starts before `BusService`.

**Deciding factor:** put each piece on the class that already owns the facts it needs, with the fewest new things.

| | A: `BusService` helper, `SessionManager`, direct writes | B: one new evidence service | C: three new pieces | D: extend `CommandExecutor` |
|---|---|---|---|---|
| New pieces | One helper class, one function | One service | Three | None |
| Fits the host's role | Yes: dispatch owns rejections, the session owns its lifecycle | Yes | Yes | No: it runs handlers |
| Loss accounting | `PipelineCounters` | `PipelineCounters` | `PipelineCounters` | `PipelineCounters` |
| Has session id and database already | Yes | Must get them | Must get them | Partly |
| Shutdown ordering | Inherited | New position to design | Two new positions | Inherited |
| Subscriber timing | Needs care: `SessionManager` starts before the bus | Natural | Natural | Natural |
| What peers do | unknown | unknown | unknown | unknown |

**Recommendation:** A. Near-miss rollups live in a helper class composed by `BusService`, flushed by a task in its bucket and once on the way down. Timeline rows go through a method on `SessionManager`, called directly by `OutageLog` and block reconciliation, and by an app state subscriber. API writes go through one small function that enqueues the row. Drops count as new `PipelineCounter` members, not bespoke fields. App stop rows must reach the timeline, so the subscriber can't be a listener on Hassette's own bus; the timeline pickup settles how it subscribes.
**Pick B instead if** the subscriber's timing proves awkward at pickup; even then, a small dedicated subscriber could feed `SessionManager`. **Pick C instead if** being able to delete each writer on its own, such as the lifecycle writer at #1446, is worth two more shutdown positions. **Pick D instead if** the near-miss work turns out to need `CommandExecutor`'s context, which nothing shows today.
**Reversibility:** easy (internal)
**Ratified:** Chose existing classes (a `BusService` helper, `SessionManager`, and one write function) over a new evidence service, separate pieces, or `CommandExecutor`, to put each writer where its facts already are with no new shutdown position, accepting care over when `SessionManager` can subscribe.

### D12: How are the new tables retained?

**Situation:** each new table needs an age limit and a place in the size failsafe. Today the failsafe deletes framework executions, then blocking events, then app executions. New settings need to earn their place.

**Deciding factor:** evidence that's cheap to lose goes first, with no new settings.

| | A: this order, existing age settings | B: A plus a shorter near-miss window | C: A plus a per-app row cap on API writes |
|---|---|---|---|
| New settings or mechanism | None | One shorter window, as a constant or setting | A cap and a drop counter |
| Rollups at the bound | D3's bound | Less, in proportion to the window | D3's bound |
| Pattern over days | Full retention window | Shorter | Full retention window |
| Tight periodic writer | Reaches the failsafe, which deletes API writes before app executions | Same | Bounded before it gets there |
| Answers "what did this run ask HA to do" | Always, within retention | Always, within retention | Not above the cap |
| What peers do | Temporal and n8n cap the container or prune by age and count | unknown | Kubernetes aggregates with counts |

**Recommendation:** A: the near-miss and API write tables age out on `database.retention_days`, with no new settings; the lifecycle table follows spec 132's D25 (D1), which makes it its own target on `retention_days` and adds it to the session delete's guard. Failsafe order: DEBUG log lines (D9), near-miss rollups, framework executions, blocking events, API writes, app executions. The lifecycle table is failsafe-exempt like other log records, because it explains the overage and stays small: at an estimated 150 bytes a row, 90 apps restarting daily add about 2 MB over 30 days, and one app crash-looping every minute adds about 25 MB. API writes add about 1 GB over 30 days per write a second, at an estimated average of 400 bytes a row, and about 5 GB if every row holds the full 2 KB, so a tight periodic writer reaches the size limit on its own; the failsafe then deletes API writes before app executions, and keeps up within its shared budget of 10,000 rows an hour, about 2.8 writes a second across all tables.
**Pick B instead if** rollups turn out to dominate the database. **Pick C instead if** you expect several apps writing faster than about 3 times a second to be common.
**Reversibility:** easy
**Ratified:** Chose this failsafe order, existing age settings and a stated API write estimate, over a shorter near-miss window or a per-app row cap on API writes, so evidence that's cheap to lose goes first with no new settings and no write record is dropped at the source, accepting about 25 MB of rollups expected and about 110 MB at the bound, and that a tight periodic writer can use the size limit until the failsafe deletes its rows.

### D13: How do the CLI and API present this?

**Situation:** the CLI has `listener`, `job`, `log`, `execution` and `status`. The incident pattern is "something happened around this time to this app", and today that takes several commands plus `docker logs`. Hassette also needs something like Home Assistant's Activity pane, which the later UI work would display. Terminal use matters: troubleshooting happens through Claude.

**Deciding factor:** one command that answers "what happened around T", on an API the later UI can reuse.

| | A: extend commands, plus a merged `timeline` | B: extend commands, with `timeline` showing framework events only | C: one new `hassette why` that explains an outcome |
|---|---|---|---|
| "What happened around T" | One command | Several commands, merged by hand | One command |
| Reusable by the UI | Yes: an activity-style feed | Partly | No: it encodes conclusions |
| Must infer causes | No | No | Yes, and can be wrong |
| Work | One merged read across four tables, plus session boundaries | Least | Most |
| What peers do | HA Activity: time-scoped, multi-source | Prefect: event feed | None found |

**Recommendation:** A: `hassette listener <id> --misses`; `hassette execution <id>` shows trigger detail, `caused_by` and API writes; `hassette timeline --around <time> [--window] [--app]` merges framework events, executions, near-misses and API writes in time order, with matching API routes and wire models. It reports evidence and doesn't draw conclusions, and it shows session boundaries and unclean ends (D2). Without `--app` it shows framework events plus executions, so it stays readable.
**Pick B instead if** the merged read proves slow on a large database and you'd rather defer it to the UI work. **Pick C instead if** you want a command that states a cause and accept that it can be wrong.
**Reversibility:** hard for names once released (a wire and CLI surface), though pre-V1 allows a clean break
**Ratified:** Chose extending existing commands plus a merged `hassette timeline` over a framework-only timeline or a `hassette why` that infers causes, to answer "what happened around T" in one command on an API the later UI can reuse, accepting a read across four tables.

## Assumed

- A trigger context id really is Home Assistant's context id: events set `event_id` from `context.id`, so the join key is valid. This resolves the question map's caveat. Evidence: `Event` base class in `hassette.events`.
- Home Assistant's `call_service` reply carries `{"context": ...}` on success, arrives after the handler finishes because the WebSocket handler hard-codes `blocking=True`, and error frames carry a code and no context. A caller can't supply a context, so Hassette can't make Home Assistant's Activity panel name the app. Evidence: `websocket_api/commands.py` and `connection.py` on HA core `dev`, quoted in the prior-art brief.
- State changes carry a call's context only for directly targeted entities, within 5 seconds (`CONTEXT_RECENT_TIME_SECONDS`). Evidence: `helpers/entity.py` on HA core `dev`, quoted in the prior-art brief.
- New tables identify an instance by name, and listener and job rows have `instance_name` once #3098 lands; these migrations chain after it. Evidence: #3098 and the milestone description.
- Job skips are already recorded as `skipped` executions, and the CLI job table shows them, so jobs need no near-miss table. Evidence: `SchedulerDispatch` skip recording; #1818 closed.
- Persisted app lines are already available per app and execution; the log-trust fixes come after this milestone. Evidence: question map's order of work.
- New seed scenarios and generated client types follow the repo's existing conventions for any telemetry table or wire change. Evidence: `CLAUDE.md` Workspace Packages section; the existing seed scenarios.

## Breakdown

**Done when:** for any listener or job within retention, the API and CLI answer these without app source or `docker logs`: which events reached a listener and were dropped, by which filter and with what values; which event triggered each execution; which service calls each execution made and how each ended, along with its other API writes; and which connection, restart and app lifecycle events happened around a given time. Full debug logs for one app can be captured at runtime, without a restart.

Applies to all: D11's homes, D12's retention rules and D13's naming and surface, each for its own evidence. Each issue ships its docs-site updates, docstrings, regenerated schemas and frontend types in the same PR. Showing this data in the web UI is deliberately excluded from this milestone, as an explicit exception to the design-completeness rule; the UI redesign that follows displays it. Each `After:` names only an issue's direct dependencies; #3099 and #3100 are expected to land first too, because they move the code these issues touch.

1. **Delete persisted DEBUG lines first when over the size limit**: a separate failsafe target for DEBUG lines, and corrected docs. Implements: D9. After: none; any index it needs chains after the latest migration when it lands. Issue: #3675
2. **Record trigger detail on executions**: the event summary columns and their CLI and API exposure. Implements: D6 (except `caused_by`). After: #3098. Issue: #3676
3. **Record near-misses per listener**: reason codes, filter attribution, rollups, and `listener --misses`. Replaces #1817's scope; its body is rewritten at filing to drop the dashboard criterion. Pickup settles how the `AllOf` walk tells selection filters from a user's `where` (D4), the flush interval (D3), the dispatch benchmark, and whether the failing filter joins the rollup key, since the Done-when asks "by which filter" and D3's row names only the latest one in an hour, against the higher size bound that key would bring. Implements: D3, D4, D5. After: #3098, #3675, #3676. Issue: #1817
4. **Record API writes and their outcomes**: background reply tracking, the rejected-call WARNING, write records, `caused_by`, and the execution view. Pickup settles the pending-entry cap (D7). Implements: D7, D8, D6's `caused_by`. After: #3098, #3675, #3676. Issue: #3677
5. **Record the framework timeline and add `hassette timeline`**: the lifecycle table, its writers, and the merged read. Pickup settles where the app state subscriber lives and how it subscribes (D11), where block reconciliation keeps the prior state its diffs need (D2), the default `--window` and `--around` format (D13), and how an hour-long near-miss row sits in a time-ordered merge, including misses not yet flushed (D3, D13). Implements: D1, D2, D13's timeline. After: #3098, #1817, #3677. Issue: #3678
6. **Add per-app debug capture**: the switch with `hassette app debug` and its API route, the persistence exception, reload behavior, the turn-on WARNING, the flag on the app status read, and `hassette log --level`. Implements: D10. After: #3675. Issue: #3679
Filed alongside, with no milestone because the Done-when doesn't need them: a stored event history table (D6, #3681), and stopping documenting `Api`'s raw methods as public API (D8, #3680).
