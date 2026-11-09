# Design: Record API writes and how each one ended

**Date:** 2026-11-09
**Status:** ratified
**Mode:** sketch
**Issues:** #3677
**Parent:** design/specs/142-diagnostic-evidence/design.md
**Prior art:** design/research/2026-11-01-diagnostic-evidence/prior-art.md

## Summary

By default `call_service` sends and returns. Home Assistant's reply finds no pending entry and is dropped, so a rejected call leaves no trace, and nothing records what a run asked Home Assistant to do. This change records one row per named `Api` write with how it ended, tracks fire-and-forget `call_service` replies in the background without changing handler timing, links each row to the execution that made it, and shows the writes and `caused_by` on the execution read. It implements the parent's D7, D8 and D6's `caused_by`, refined by the decisions below. The timeline (#3678) and any web UI are out of scope.

New pieces and their homes:

- **Write records:** a new `api_writes` table (migration `src/hassette/migrations_sql/024.sql`), a `PipelineCounter` member for write-queue drops and one for evicted background entries (`src/hassette/core/pipeline_counters.py`), an insert at send and an outcome update on the telemetry repository (`src/hassette/core/telemetry/`) (D8), a startup sweep of earlier sessions' `pending` rows in `SessionManager.mark_orphaned_sessions` (`src/hassette/core/session_manager.py`) (D9), and a retention target between blocking events and app executions (`src/hassette/core/retention_targets.py`, priorities after it shift by one). `sessions` deletion gains an `api_writes` guard (`src/hassette/core/database_retention.py`).
- **Recording point:** a new `ApiWriteRecorder` (`src/hassette/core/api_write_recorder.py`, D10) with one function that builds the row and enqueues its insert at send and one that enqueues its outcome update (the parent's D11, split by D8). The recorder also owns the drop counter's WARNING pacing; `PendingResponses` owns the background-entry running count and the eviction WARNING's pacing (D2). Each named write calls the insert once at send, from its async body; who calls the update is D1's rule (the entry's callback for WebSocket writes, the caller only for `not_sent` and for REST writes). The named writes: `_call_service` and `_fire_event` (`src/hassette/api/service_calls.py`), `_set_state` and `delete_entity` (`src/hassette/api/entity_data.py`), and `HelperClient.create`/`update`/`delete` (`src/hassette/api/helpers.py`). `turn_on`/`turn_off`/`toggle` and the counter helpers reach `_call_service`, so they record once, as `call_service`. Only an `Api` whose parent is an `App` records (`src/hassette/app/app.py` builds it). The framework's own `Api` (`Hassette._api`, `src/hassette/core/core.py`) and `RecordingApi` don't.
- **Background reply tracking:** `PendingResponses` (`src/hassette/core/websocket_responses.py`) gains entries that carry a resolve callback for every named WebSocket write, registered before sending and owning the row's resolution (D1); an entry with no one waiting on it is a background entry. Each entry records at registration whether its call is fire-and-forget, a flag fixed for its life; D1's table picks the reply's log line. `PendingResponses` receives `PipelineCounters` as a constructor argument for the eviction counter (D2). The callback is built by the recorder (D10) and closes over what D1 lists, so `PendingResponses` holds no telemetry repository or app references and resolves the row from the reply, in place of today's timed-out entries that only log (D1, D2, D8). `WebsocketService` gets a send path for fire-and-forget `call_service` that registers one before sending (`src/hassette/core/websocket_io.py`).
- **Read surface:** an `ApiWrite` wire model and `ExecutionTrigger.caused_by` (`wire/src/hassette_wire/telemetry.py`); `GET /api/executions/{id}` (`src/hassette/web/routes/executions.py`) returns a new `ExecutionDetail` in place of `LogsByExecutionResponse` (`wire/src/hassette_wire/logs.py`), with the client method renamed to match (`client/src/hassette_client/client.py`); `hassette execution` reads that one route and shows the writes (`src/hassette/cli/commands/log.py`); the `caused_by` subquery joins every `Execution` read and the writes-by-execution query sits beside them in `src/hassette/core/telemetry/execution_queries.py` (D5, D6).
- **Docs and generated files:** `docs/pages/core-concepts/database-telemetry.md` (table, outcomes, growth estimate, and that `data` is stored unredacted, naming alarm and lock `code` values, password-mode helper values and tokens as examples, so check `--json` output before sharing it), `docs/pages/core-concepts/api/methods.md` (what success means, the rejected-call WARNING, raw methods aren't recorded), `docs/pages/cli/commands.md`; regenerated schemas and frontend types; seed scenarios gain write rows.

Prerequisite: #3957 (transport exceptions split by delivery state) lands first; D1's caller-side `not_sent` and D4's mapping take its classes, whose exact names the build takes from #3957 as merged.

Out of scope: a write listing or timeline route, any web UI (the parent's milestone-wide exception), recording raw transport methods (parent D8), and KI-004's `execution_error` key from spec 147, which waits for a consumer that needs it.

## Posture

- **Failure handling:** recording is best-effort and never affects a handler. A dropped row or evicted entry is counted in `PipelineCounters`, with one WARNING per episode, where an episode is paced the way the execution pipeline paces its capacity WARNING (`_last_capacity_warn_ts` in `src/hassette/core/execution_pipeline.py`); nothing is retried (parent Posture).
- **Compatibility:** clean breaks are fine pre-V1. Wire changes go through the released-client compatibility check (`uv run nox -s client_compat`); they're additive except D6's execution detail read, whose break is listed in `tools/client_compat_ignore.txt`. The `hassette execution --json` object becomes that detail read.
- **Scope:** the Done-when slice only: write records, `caused_by`, and the writes on the execution read. No listing or timeline route; #3678 owns the merged read.
- **Rollout:** on by default, no flag. Migration 024 chains after 023.
- **Hardening:** project defaults, plus a fixed memory bound on background entries (D2) and the parent D12 growth estimate in the docs.
- **Altitude:** `build`; one session builds it.

## Decisions

### D1: How does an awaited write end up resolved when its caller stops waiting? (refines parent D8's "takes the same outcomes from what its call returns or raises")

**Situation:** writes that wait (`fire_event`, helper create/update/delete, `call_service` with `wait_for_ack` or `return_response`) send through `send_and_wait(retry_on_timeout=False)`. A caller can stop waiting in two ways. After 15 seconds (`RESPONSE_TIMEOUT_SECONDS`) it gets `ResponseTimeoutError`, and the entry stays in `PendingResponses` marked timed out (`mark_timed_out`), with a late reply only logged (`log_late_reply`). If the handler is cancelled instead (a handler timeout in `CommandExecutor`, or an app reload or shutdown mid-call), `CancelledError` skips `mark_timed_out` and the `finally` in `send_and_await_response` discards the entry, so the reply is ignored (`src/hassette/core/websocket_io.py`). Under D8 the row already exists as `pending`; the question is what resolves it. REST writes (`set_state`, `delete_entity`) have no pending entry and no later reply: an HTTP request that's cancelled mid-flight never gets an answer. The parent's outcome set has no timeout, and parent D7 rejected a timed-out outcome because Home Assistant always replies once its handler finishes.

**Deciding factor:** one owner per row, stated in the design, never storing an outcome a later reply could contradict.

| | A: the entry owns the row from registration; its reply or `fail_all` resolves it | D: the caller owns the row until it stops waiting, then converts the entry to a background entry | B: resolve the row as `connection_lost` when the caller stops waiting; late reply only logs | C: new `timed_out` outcome at the timeout; cancel left as is |
|---|---|---|---|---|
| Owners per WebSocket row | One: the entry (`not_sent` aside, which has no entry) | Two, handing off at a point the caller infers from the exception class | One: the caller | One: the caller |
| Slow call that succeeded | `success`, with the true reply time | Same | `connection_lost`, wrong in meaning | `timed_out`, though it applied |
| Reply delivered just before a cancel | Resolved at delivery | Lost unless a `fut.done()` branch is added | Recorded from the caller's view | Row stays `pending` |
| Timeout class overlapping the rejection class | Irrelevant: the caller maps only the not-sent class | Needs an ordered class list | Same as A | Same as A |
| Cancel during the socket write | `pending` until the connection ends, then `connection_lost` | Same, or a send/wait split | `connection_lost` at once | `pending` until D9's sweep |
| Outcome set | No new value | No new value | `connection_lost` also means "gave up" | One more value |
| Mechanism | Today's entry carries the resolve callback from registration; today's timed-out mark, extended to cancellation, records only that no one is waiting | A conversion step plus the guards above | Today's entry, plus an update when the caller stops | Same as B, for the timeout only |
| Caller | Still gets `ResponseTimeoutError` at 15 s, or its cancellation | Same | Same | Same |
| What peers do | LSP clients (vscode-jsonrpc) and home-assistant-js-websocket keep the entry until the peer answers or the connection closes, without a durable record | None found | NetDaemon, python-hass-client, AppDaemon: the caller owns the verdict; a late reply is dropped or only logged | Temporal records `TimedOut` only against a deadline the caller chose |

**Recommendation:** A, the pattern peers use when the remote side keeps working after the client gives up, which Home Assistant does: it has no per-command cancel and finishes `call_service` regardless (`design/research/2026-11-09-late-reply-ownership/prior-art.md`). Every named WebSocket write, awaited or fire-and-forget, registers its entry with the row's resolve callback before sending. When the reply arrives, `respond_if_necessary` runs the callback (`success` or `rejected`, with the context id) and removes the entry, and also sets the future if a caller is still waiting. When the connection ends, `fail_all` runs every remaining callback with `connection_lost` (Assumed). The caller writes an outcome only for #3957's not-sent class (`not_sent`), removing the entry, since no reply can come. On a timeout or cancellation it writes nothing: it marks the entry as having no one waiting, then raises `ResponseTimeoutError` or re-raises the cancellation. That mark replaces today's `mark_timed_out` and `discard`-on-cancel, and, with the fire-and-forget flag each entry carries from registration, it decides the reply's log line:

| Entry | Success reply | Rejection reply |
|---|---|---|
| Awaited, caller still waiting | None (the caller gets the result) | None (the caller gets the exception) |
| Awaited, caller stopped waiting | Today's late-reply INFO | Today's late-reply WARNING |
| Fire-and-forget | None | D7's WARNING only |

A fire-and-forget entry never takes the no-one-waiting mark; it's a background entry by its flag. A cancel during the socket write isn't told apart from one after it, as no peer does: the row reads `pending` until the connection ends, then `connection_lost`. A REST write has no entry, so its caller owns the row outright and maps every outcome per D4, cancellation included. The resolve callback closes over the row's `write_id`, execution id, app identity, kind and operation, the app's `Api` logger and the update function, never target or data.
**Pick D instead if** you want the caller to keep the row while it waits, and accept guards for the cases where its view is wrong. **Pick B instead if** you want the row resolved the moment the caller gives up, and accept `connection_lost` stretching to cover it. **Pick C instead if** you want a timeout recorded and are fine reopening parent D7's no-timed-out rule.
**Reversibility:** easy
**Ratified:** Chose having each WebSocket write's pending entry own its row from registration, resolved by its reply or by `fail_all`, with the caller recording only `not_sent`, over the caller owning the row and converting the entry when it stops waiting, resolving at timeout or cancellation, or a `timed_out` outcome, so each row has one owner and never stores an outcome a later reply contradicts, accepting that a call cancelled mid-write reads `pending` until its connection ends. Chosen by the user in the sketch re-challenge's convergence Finding 1 (`review-log.jsonl`), after a prior-art pass (`design/research/2026-11-09-late-reply-ownership/prior-art.md`), superseding the earlier conversion design; the REST rule and the late-reply logging carry over from the earlier sketch comb.

### D2: How many background entries can wait at once, and which one goes when the cap is hit?

**Situation:** parent D7 puts fire-and-forget calls in the existing pending-reply table with a cap and counts evictions, and left the cap to this pickup. Today's cap, `TIMED_OUT_WRITE_RECORD_CAP = 100`, covers only timed-out writes. Home Assistant usually replies in milliseconds, but its WebSocket handler waits for the service to finish, so a call to a long script (`script.my_script` called directly) waits for the whole script. An app that starts a five-minute script on every motion event, or loops over 200 lights with separate calls to a slow integration, can hold hundreds of entries for a while. Under D8 the row is already in the database, so an entry holds no target or data: just its resolve callback and the closure D1 lists, about 200 bytes. An evicted entry's row is resolved at once as `unresolved` (D9), through the entry's own resolve callback. An awaited write's live entry has a caller waiting on its future and must never be evicted.

**Deciding factor:** eviction practically never happens, with a stated memory bound.

| | A: 10,000 background entries, oldest evicted | B: 1,000, oldest evicted | C: no cap |
|---|---|---|---|
| Worst-case memory | About 2 MB | About 200 KB | Unbounded within one connection |
| 200 separate calls to a slow integration | All tracked | All tracked | All tracked |
| Burst of slow calls | Practically never evicts | Evicts after 1,000 at once | Never evicts |
| What an eviction costs | The row resolves as `unresolved`, and its reply is no longer recorded | Same, sooner | n/a |
| Awaited callers | Never evicted while a caller waits | Same | n/a |
| Meets parent D7's "with a cap" | Yes | Yes | No: reopens D7 |
| New number | One constant replaces `TIMED_OUT_WRITE_RECORD_CAP` | Same | None |
| Cost of the cap check near the cap | A running count, no rescan per registration | Same | None |
| What peers do | unknown | unknown | unknown |

**Recommendation:** A. Evict the earliest-sent background entry, since a call waiting longest is the one most likely still running a long script. Entries keep the order they were registered in, which is send order (D1 registers every entry before sending), and marking one as having no one waiting doesn't reorder it: unlike today's `mark_timed_out`, the mark never pops and re-inserts the entry. The cap check keeps a running count of background entries rather than rescanning the table on each registration (today's `mark_timed_out` rescans, which was cheap only at a cap of 100), so registering an entry costs the same with 10,000 outstanding as with none. When the connection ends, `fail_all` runs each entry's resolve callback under the same `suppress(Exception)` it already uses for `set_exception`, so one failing callback never stops the table from clearing; each eviction counts on a new `PipelineCounter` member, with one WARNING per eviction episode. An awaited entry with its caller still waiting doesn't count toward the cap and is never evicted; once D1 marks it as having no one waiting, it counts and can be evicted like any other.
**Pick B instead if** you want the smaller number and accept evictions in large bursts. **Pick C instead if** you trust that each connection's end clears the table often enough, and want to reopen D7's cap.
**Reversibility:** easy (a constant)
**Ratified:** Chose a cap of 10,000 background entries holding only a resolve callback over ids (no target or data), with the earliest-sent evicted and a cap check that doesn't rescan the table, over 1,000 or no cap, so eviction practically never happens within about 2 MB, accepting that an evicted call's reply goes unrecorded and its row reads `unresolved` (evictions resolve immediately per the sketch re-challenge's convergence Finding 2, chosen by the user). Revised from 1,000 full-row entries by the user through the sketch-time challenge finding 1 (`review-log.jsonl`) re-evaluation (D8). Eviction order and the no-rescan cap check chosen by the user in the sketch re-challenge's Finding 10.

### D3: What does a write row hold, and how is the target recorded?

**Situation:** parent D8 lists the row's contents (app key, instance name, execution id, kind, target, data cut at 2 KB, outcome, Home Assistant's returned context id, send and reply times) and left the table name, the column shapes and the target to this pickup. Home Assistant merges `target` into the service data, so `call_service("light", "turn_on", entity_id="light.x")` and `call_service("light", "turn_on", target={"entity_id": "light.x"})` do the same thing, but only the second has a `target`. "Who wrote this sensor?" needs the entity whichever way it was passed. Sibling spec 147 D2 settled how trigger values are stored: a display string (strings as-is, others as compact `json.dumps` with `ensure_ascii=False` and `default=str`) cut at a code-point limit with a trailing `…`.

**Deciding factor:** "who wrote this entity" answered by one column, however the caller passed it.

| | A: normalized target | B: target as passed |
|---|---|---|
| Table | `api_writes` | `api_writes` |
| `kind` | `call_service`, `fire_event`, `set_state`, `delete_entity`, `helper_create`, `helper_update`, `helper_delete` | Same |
| `operation` | `light.turn_on`; the event type; the helper domain; NULL for `set_state` and `delete_entity` | Same |
| `target` | JSON object of id lists. For `call_service`, HA's target keys (`entity_id`, `device_id`, `area_id`, `floor_id`, `label_id`), taken from `target` and those keys in the service data, merged the way Home Assistant merges them (a key in `target` replaces the same key in the service data) and with comma-separated strings split and stripped as Home Assistant's entity-id validator does, so the stored lists are what Home Assistant acts on; not cut, since ids are short and the call's own size bounds them; `{"entity_id": [id]}` for `set_state` and `delete_entity`; `{"helper_id": [id]}` for helper update and delete; NULL otherwise | `call_service`'s `target` argument as given; the entity id for `set_state`/`delete_entity`; the helper id; NULL otherwise |
| `data` | The rest of what the caller passed (service data without the lifted keys, event data, state and the caller's attributes, helper params), as a 147 D2 display string cut at 2,048 code points | Everything not in `target`, same format |
| `entity_id="light.x"` in service data | In `target` | Only in `data`, maybe cut off |
| Wire `target` type | `dict[str, list[str]] \| None` | `dict[str, Any] \| str \| None` |
| Matches what HA acts on | Yes | Only when the caller used `target` |
| What peers do | unknown | Temporal records activity input as given |

Both options also store `write_id` (D8), `outcome` (`pending`: not yet resolved; `success`: Home Assistant's handler returned, not that the device changed; `rejected`: Home Assistant answered with an error; `connection_lost`: sent, then the connection ended or the request was abandoned before a reply (a WebSocket connection ending; a REST request that timed out, dropped or was cancelled), outcome unknown; `unresolved`: sent, but how it ended wasn't recorded (evicted, or still `pending` at the next start), outcome unknown; `not_sent`: never reached Home Assistant; D1, D2, D4, D8 and D9 say when each applies), the rejection's `error_code` and `error_message`, `context_id` where Home Assistant returns one, `sent_ts` and `resolved_ts` (when the outcome was observed: the reply, the failure, `fail_all` or the cancellation; NULL for `pending` and `unresolved`), `app_key`, `instance_name`, `execution_id` (NULL outside a run) and `session_id` (nullable, as `try_session_id()` can return None), with a unique index on `write_id` and indexes on `execution_id`, `context_id`, `sent_ts` and `(app_key, sent_ts)`, plus a partial index on `sent_ts` `WHERE outcome = 'pending'` so D9's startup sweep reads only pending rows (the house pattern of `idx_lr_debug_time` in migration 022; the sweep's predicate must imply the index's).

**Recommendation:** A, because the target is what the row exists to answer, and HA treats both call styles the same.
**Pick B instead if** you'd rather store exactly what the caller wrote and accept missing targets for the `entity_id=` style.
**Reversibility:** easy (no data to migrate before release)
**Ratified:** Chose an `api_writes` table with a normalized target (HA target keys lifted from `target` and the service data, merged with `target` winning and comma-separated ids split as Home Assistant does, stored uncut) and 147 D2-style `data` cut at 2,048 code points, over storing the target as passed, so one column answers "who wrote this entity" exactly as Home Assistant acted on it whichever call style was used, accepting that `data` no longer shows where the caller put the target keys. Merge and split rules added at the sketch comb and re-ratified by the user. The partial index on pending rows was chosen by the user in the sketch re-challenge's Finding 12, over a full-table sweep or a sweep bounded by the previous session's start.

### D4: Does a write that never reached Home Assistant get a row?

**Situation:** `Api.ws_send_json` and `Api.ws_send_and_wait` raise `ConnectionClosedError` before sending when the connection isn't up, and the socket write itself can fail (`FailedMessageError`). A REST write can fail to connect at all. Either way the caller gets an exception and Home Assistant never saw the call. If the handler doesn't catch it, the execution row already records the error; many apps catch it. Reconnects and restarts interfered in 6 of the parent's 13 incidents, and parent D8 defines `connection_lost` as "the connection ended before a reply", meaning the outcome is unknown.

**Deciding factor:** "which calls did this run make, and how did each end" answered for runs during an outage, without implying a call might have applied when it couldn't have.

| | A: no row | B: row with a `not_sent` outcome | C: row as `connection_lost` |
|---|---|---|---|
| Run during an outage, exception caught | Nothing recorded | Recorded, clearly never applied | Recorded, but reads as "may have applied" |
| Outcome set | Unchanged | One more value | Unchanged, meaning muddied |
| Extra sites | None | The update function on the exception path, after the insert at send (two queue operations, like any write); `sent_ts` is the attempt time | Same as B |
| What peers do | unknown | Temporal records a failed schedule separately from a failed result | unknown |

**Recommendation:** B, because a call a run tried during an outage is exactly the evidence the reconnect incidents needed, and `not_sent` is the one outcome that's certain.
Every named write maps the same way over both transports. WebSocket: the caller records only #3957's not-sent class → `not_sent`; every other outcome comes from the entry D1 makes the row's owner: a success reply → `success`, an error reply → `rejected` with HA's `code` and message, and the connection ending first → `connection_lost` through `fail_all`. The caller writes nothing on a rejection, timeout or lost connection. REST (`set_state`, `delete_entity`): a failed connect → `not_sent`; an HTTP error status (`HttpRequestError`, or `EntityNotFoundError` for 404) → `rejected`, with `error_code` holding the status as a string (e.g. `"404"`) and `error_message` the reason; any other failure after the request went out (a timeout, a dropped connection, retries exhausted, or the caller's cancellation, which re-raises) → `connection_lost`. `_set_state`'s preliminary GET treats a missing entity (the 404 it already swallows) as normal, not a failure; any other failure of that GET records `not_sent`, since its POST never ran.
**Pick A instead if** you'd rather keep the outcome set to the parent's three and rely on uncaught exceptions showing on the execution row. **Pick C instead if** you want no new value and accept `connection_lost` covering a call that certainly didn't apply.
**Reversibility:** easy
**Ratified:** Chose recording a write that never reached Home Assistant with a `not_sent` outcome, over no row or `connection_lost`, so runs during an outage show what they tried without implying it might have applied, accepting an outcome beyond the parent's set (D3 holds the full list). Each outcome maps from exactly one failure class per transport, as listed above; the WebSocket side depends on #3957 splitting the transport exceptions by delivery state, which the user chose after the sketch-time challenge (finding 3, `review-log.jsonl`) showed today's classes can't separate a socket-write failure from a codeless rejection. The REST mapping was added at the sketch comb and re-ratified by the user.

### D5: What is `caused_by`, where does it sit, and when is it computed? (refines parent D6)

**Situation:** parent D6 says the execution read reports `caused_by` when its trigger context id matches a recorded write, described as "same Home Assistant context id, best-effort". Sibling 147 D1 put every trigger fact on a nested `trigger` object (`ExecutionTrigger`). Home Assistant fires the `state_changed` event during the service handler and sends the reply after it finishes. Under D8 the write row exists from send, but its `context_id` arrives only with the reply's update, so a listener can run, and its execution row be written, before the write's context id is known. A write made outside a run (`on_initialize`) has no execution id. The failsafe deletes API writes before app executions (parent D12), so a match can disappear while the run remains.

**Deciding factor:** a match that's found whichever of the context id and the execution row lands first, and that names the app even when the write had no run.

| | A: object on `trigger`, joined at read time | B: execution id string on `trigger`, joined at read time | C: object stored on the execution row at write time |
|---|---|---|---|
| Listener ran before the reply | Matched once the reply's update lands | Same | Missed: the write's context id isn't known yet |
| Write from `on_initialize` | Names the app and instance | Nothing to show | Names the app |
| Write row deleted by retention | `caused_by` disappears | Same | Kept |
| Shape | `{app_key, instance_name, execution_id, kind, operation}`, with `execution_id` None for a write outside a run and `operation` None for `set_state`/`delete_entity` | `str` | Same as A |
| Cost | A correlated subquery on the indexed `api_writes.context_id` taking at most one write (earliest `sent_ts`), so a repeated context id never duplicates execution rows | Same | A lookup on the execution write path |
| Fits 147 D1's one home for trigger facts | Yes | Yes | Yes |
| What peers do | unknown | unknown | unknown |

**Recommendation:** A, because only a read-time join matches when the listener runs before the reply, and the object still says which app wrote it when there's no run. Jobs and unmatched handler rows read `None`. A write still `pending`, or resolved without a context id (`rejected`, `connection_lost`, `unresolved`, `not_sent`, a dropped update), never matches. `caused_by` is computed on every read that returns an `Execution`: list reads, the record-only route and `ExecutionDetail`.
**Pick B instead if** you only care about run-to-run links. **Pick C instead if** keeping `caused_by` after its write row ages out matters more than matching listeners that beat the reply.
**Reversibility:** easy (read-time only, so nothing stored to migrate)
**Ratified:** Chose a `caused_by` object (`app_key`, `instance_name`, `execution_id`, `kind`, `operation`) on `ExecutionTrigger`, matched at read time to at most one write (earliest `sent_ts`) on every read that returns an `Execution`, over an execution-id string or a value stored at write time, so a listener that runs before the reply matches once the reply's update lands, a write outside a run still names its app, and a repeated context id never duplicates execution rows, accepting that `caused_by` disappears once its write row ages out, that a pending or context-less write never matches, and that only a direct context match counts: a write that sets off an HA automation is not reported on the automation's downstream runs (chain walking belongs to #3678's timeline). Re-ratified by the user after the sketch comb clarified the match rules.

### D6: How does the execution read return its writes? (refines parent D13)

**Situation:** one execution's detail is already split across two routes under two prefixes. `hassette execution <id>` reads the record from `GET /api/telemetry/execution/{id}` (an `Execution`, the model list reads also use) and the logs from `GET /api/executions/{id}` (`LogsByExecutionResponse`), and stitches them into `{"execution": ..., "logs": [...]}` with 147 D6's lenient contract: a failed record lookup reads `null`, the reason goes to stderr, exit 0. That contract exists because the record is written in batches and can lag the logs by seconds. Only the CLI and `client.get_execution_logs` use the logs route; the frontend's execution panel uses the record route (`getExecutionById`). Parent D13 says the command shows the writes. #3678 will do its own merged read across tables.

**Deciding factor:** one detail read per execution, rather than a third route stitched beside the existing two.

| | D: one detail read at `GET /api/executions/{id}` | A: third route `GET /api/telemetry/execution/{id}/api-writes` | E: sub-resources `/api/executions/{id}`, `/logs`, `/api-writes` | B: `api_writes` list on `Execution`, filled only by the single read |
|---|---|---|---|---|
| CLI calls | One | Three | Three | Two |
| Where the partial-result rule lives | Server, once: `execution: null` while the record lags | CLI, three keys | CLI, three keys | CLI, two keys |
| `Execution` in lists | Unchanged | Unchanged | Unchanged | Carries a field that's always `None` there |
| Wire and client | `LogsByExecutionResponse` becomes `ExecutionDetail`; `get_execution_logs` becomes `get_execution_detail`; one `tools/client_compat_ignore.txt` entry | New `get_execution_api_writes`, no break | Record route moves, logs route renamed | No break |
| Frontend | Record route untouched; types regenerate | Same | Panel's route changes | Same |
| Reusable by #3678 | The writes query | The writes query | The writes query | No |
| What peers do | unknown | unknown | unknown | unknown |

**Recommendation:** D, because one read answers "what happened in this run", the partial-result rule moves from the CLI to one place on the server, and the break is pre-V1 and limited to the CLI's own route. `ExecutionDetail` holds `execution` (`None` while the record lags), `api_writes` (ordered by `sent_ts`, capped by the route's existing `limit` parameter, which bounds each list separately with the same default and maximum as logs, `EXECUTION_LOGS_DEFAULT_LIMIT`/`EXECUTION_LOGS_LIMIT_CAP` in `src/hassette/web/routes/executions.py`), `api_writes_truncated`, `logs`, `logs_truncated` and `retention_expired`; `--json` prints it as served, and a failed request fails the command like any other. Human output shows the summary, a writes table (time sent, kind, operation, target, outcome, error code; `data` in `--json` only) with a notice of how many writes were omitted when truncated, then the logs. `GET /api/telemetry/execution/{id}` stays as the record-only read.
**Pick A instead if** you want no wire break in this PR and accept a third stitched call. **Pick E instead if** you want the split kept but named as sub-resources, and accept moving the frontend's route. **Pick B instead if** one fewer call matters more than an always-`None` field in lists.
**Reversibility:** easy pre-V1
**Ratified:** Chose one detail read at `GET /api/executions/{id}` returning `ExecutionDetail` (record, API writes, logs), over a third stitched route, sub-resources, or a field on `Execution`, so each execution has one detail read and the lagging-record rule lives once on the server, accepting a pre-V1 break of `LogsByExecutionResponse` and `client.get_execution_logs` with a client-compat ignore entry. Raised by the user, who found the stitched three-route shape Frankenstein-y. The writes list is ordered by `sent_ts` and capped like logs with an `api_writes_truncated` flag, chosen by the user at the re-challenge's sketch comb over returning every write.

### D7: Where does the rejected-call WARNING go? (refines parent D7)

**Situation:** parent D7 adds one framework WARNING when a background-tracked `call_service` is rejected, carrying the caller's execution id. The reply is handled on the WebSocket receive task, outside the run, so a log line written there has no execution id and doesn't show under `hassette execution <id>`. Log records take their execution id from `CURRENT_EXECUTION_ID` when they're emitted (`src/hassette/logging_.py`). The app's `Api` logger is a framework logger the app owns, so app log filters and per-app debug capture (spec 148) already include it.

**Deciding factor:** the warning shows up where someone looking at that run or that app will see it.

| | A: the app's `Api` logger, with the captured execution id set while it logs | B: the WebSocket service's logger, execution id in the message |
|---|---|---|
| Shows under `hassette execution <id>` | Yes | No |
| Shows in the app's logs | Yes | No: framework service lines |
| Message | Kind, operation, HA's code and message, execution id and `write_id`; no target, since entries hold no target or data (D1); the target is one `hassette execution` away | Same |
| Machinery | Set and reset the context var around one log call | None |
| What peers do | unknown | unknown |

**Recommendation:** A. The WARNING is for fire-and-forget calls only, since their callers never see an exception. Awaited calls already raise into the caller, and an awaited write whose caller stopped waiting (on timeout or cancellation, D1) logs only today's late-reply line, never this WARNING.
**Pick B instead if** you'd rather not attribute framework lines to a run after it ended.
**Reversibility:** easy
**Ratified:** Chose logging the rejected-call WARNING on the app's `Api` logger with the captured execution id set while it logs, over the WebSocket service's logger, so the warning shows in that run's and that app's logs, accepting a framework line attributed to a run after the run ended. One WARNING per rejected call, unpaced (sketch-time challenge finding 7 (`review-log.jsonl`), chosen by the user); the context var is set and reset in a `finally`, so the receive task never carries a dead execution id into later lines. The WARNING names kind, operation, HA's code and message, execution id and `write_id`, not the target, so entries stay id-only; the entry's resolve callback closes over the app's `Api` logger, so a reload before the reply still logs under the same logger name (chosen by the user at the sketch comb). The WARNING fires for fire-and-forget calls only; awaited writes whose caller stopped waiting log only the late-reply line (D1; chosen by the user at the sketch comb's run-3 gate).

### D8: When is a write's row written? (supersedes parent D7's "a call in flight has no row until it resolves")

**Situation:** parent D7, as amended by its sketch challenge, writes one row per call once its outcome is known, so a call in flight has no row and its pending entry holds the whole row in memory. Recording at send was weighed there only as one fix among three for the `no_reply` deadline bug, and lost on "least new machinery" and the risk of a row stuck at pending. This ledger's sketch challenge found three gaps with that one cause: a cancelled awaited write gets no row (Finding 4), an empty writes list can't be told from writes still pending, evicted or lost (Finding 5), and the memory bound ignores the uncut `target` (Finding 9). Every peer in the prior-art brief records an outbound call when it's scheduled, then its outcome (Temporal's `ActivityTaskScheduled`, Step Functions, n8n). The database write queue is FIFO with one writer, and drops are counted.

**Deciding factor:** "what did this run ask Home Assistant to do" is answered from the moment of asking, including for a call still running or cut off by a crash.

| | A: insert at send as `pending`, update on resolution | B: one row at resolution (parent D7 as ratified) |
|---|---|---|
| Call in flight | Visible as `pending` | No row |
| Crash with a call in flight | Row left, resolved `unresolved` at next start (D9) | Lost |
| Cancelled awaited write | Row exists; resolved per D1 | No row unless separately patched |
| Pending entry memory | Ids only, about 200 bytes (D2) | The whole row, `target` uncut |
| Writes per call | An insert and an update, both through the write queue | One |
| Dropped insert | Write lost, counted; the update matches nothing | Write lost, counted |
| Dropped update | Row stays `pending` until D9's sweep, counted | n/a |
| New machinery | An update statement keyed on a client-generated id | None |
| What peers do | Temporal, Step Functions and n8n record the scheduled call, then its outcome | None found |

**Recommendation:** A. Each row gets a client-generated `write_id` (UUIDv7, as `execution_id` is) at send, so the update needs nothing back from the insert, and FIFO order on the single writer guarantees the insert lands first, provided the insert is enqueued before the request is registered or sent, since a reply can arrive while `send_json` is still awaiting; each write function enqueues its insert first, and a test pins it with a reply that arrives during the send. Every named write records this way, awaited ones included, so there's one write lifecycle.
**Pick B instead if** one queue operation per write matters more than seeing calls in flight and surviving a crash.
**Reversibility:** easy pre-release (no stored rows to migrate)
**Ratified:** Chose inserting each write as `pending` at send and updating it on resolution, over one row at resolution, so a run's calls are on record from the moment they're made, including calls in flight or cut off by a crash, accepting an update path on the write queue, two queue operations per write, and rows left `pending` when an update is dropped. Raised by the sketch challenge's convergence finding (Finding 1, superseding findings 4, 5 and 9) and chosen by the user after reviewing why the parent declined it. The insert-before-send ordering was added by the sketch re-challenge's Finding 9 and re-confirmed by the user.

### D9: What does a row say once nothing will resolve it?

**Situation:** under D8 a row stays `pending` until something resolves it. Some rows lose that resolution: an entry evicted at D2's cap (its reply will be ignored, and the evicting code knows it at that moment), an outcome update the write queue drops (counted, not retried), and a process that ends before resolution (a crash, or a clean shutdown whose `fail_all` updates didn't reach the database). A row left by a dropped update usually did get an answer, often `success`, so labelling it `connection_lost` would claim a cause nobody observed. Nothing is waiting on such a call after a restart. `SessionManager.mark_orphaned_sessions` (`src/hassette/core/session_manager.py`) already runs once at startup to close out sessions an earlier process left open.

**Deciding factor:** each outcome claims only what was observed, and a row stops reading `pending` as soon as the code knows nothing will resolve it.

| | A: new `unresolved` outcome, written at eviction and by a startup sweep; `connection_lost` only from `fail_all` | C: eviction resolves at once as `connection_lost`; the sweep too; docs widen its meaning | D: `pending` until the startup sweep, then `connection_lost` | B: leave it `pending`; the reader combines it with the session's end |
|---|---|---|---|---|
| Evicted row during uptime | `unresolved` at once | `connection_lost` at once | `pending` until restart | `pending` |
| Dropped-update row | `pending` until restart, then `unresolved` | `pending`, then `connection_lost` | Same as C | `pending` |
| Connection fault told apart from a lost record | Yes | No, docs only | No | No |
| Crash evidence | Kept: the row exists, outcome unknown | Kept | Kept | Kept |
| Outcome set | One more value | Unchanged | Unchanged | Unchanged |
| Mechanism | One update in the existing orphaned-session step; eviction calls the entry's existing callback | Same | The startup update only | None |
| What peers do | unknown | unknown | unknown | unknown |

**Recommendation:** A, because the outcome column answers "how did this end", and for these rows the code doesn't know, so the value says so. Eviction calls the evicted entry's resolve callback with `unresolved`. The startup sweep sets every `pending` row to `unresolved` (`WHERE outcome = 'pending'`), in the same step as the orphaned-session update and before this process's session is created (`mark_orphaned_sessions` runs before `create_session` in `src/hassette/core/core.py`), so no row of this process exists yet and every `pending` row belongs to an earlier session, whether it ended cleanly or was orphaned. It reads through D3's partial index on pending rows. A test pins that pending rows from an earlier session, including one with a NULL `session_id`, are swept at startup. Evicted and swept rows keep `resolved_ts` and the error fields NULL, since no reply was observed. Rows from the current session are never swept: one left `pending` by a dropped update stays that way until the next start, and the drop is counted. `connection_lost` comes only from `fail_all`, when the connection ends before the reply.
**Pick C instead if** you want no new value and accept `connection_lost` covering lost records. **Pick D instead if** evictions and queue drops are rare enough that a `pending` row until restart is acceptable. **Pick B instead if** you'd rather add no startup write and read `pending` as "last known".
**Reversibility:** easy
**Ratified:** Chose a new `unresolved` outcome, written by the evicting code at once and by the startup sweep of every `pending` row (run before this process's session exists, so every such row is from an earlier session), with `resolved_ts` and the error fields left NULL and `connection_lost` kept for `fail_all` alone, over resolving lost rows as `connection_lost` at eviction or startup, or leaving them `pending`, so each outcome claims only what was observed and an evicted row stops reading `pending` at once, accepting one more outcome value and that a current-session row left `pending` by a dropped update stays that way until the next start. Chosen by the user in the sketch re-challenge's convergence Finding 2 (`review-log.jsonl`), superseding the earlier `connection_lost` sweep; the sweep predicate was corrected by the re-challenge's Finding 3. Also accepted, in the re-challenge's Finding 11 (chosen by the user): a reconnect with more entries outstanding than the write queue has free slots drops the excess `fail_all` updates (counted), with unrelated telemetry in that moment, and leaves those rows to this sweep.

### D10: Where does the write-recording code live? (refines parent D11)

**Situation:** the insert and update functions need a `TelemetryRepository`, the session id (`hassette.try_session_id()`), and a timestamp to pace the write-queue drop WARNING per episode (Posture). The only fire-and-forget telemetry writer today is `CommandExecutor.record_blocking_event`, and `CommandExecutor` owns a `TelemetryRepository` and the capacity WARNING's pacing, but its role is running handlers and jobs and `src/hassette/core/command_executor.py` is already at 770 lines. The eviction side's running count and WARNING pacing sit on `PendingResponses` either way, since it already holds a logger and the entries.

**Deciding factor:** the recorder lives with what changes for the same reasons, without pushing a large class past the size guideline.

| | A: a new `ApiWriteRecorder` | B: methods on `CommandExecutor` beside `record_blocking_event` |
|---|---|---|
| Home | `src/hassette/core/api_write_recorder.py`, one per process, created by `Hassette`; an app's `Api` reaches it through `hassette` | `src/hassette/core/command_executor.py` |
| Fits the host's role | Yes: one job, recording writes | Partly: execution plus telemetry rows |
| Host size after | A new file of about 100 lines | `command_executor.py` passes 800 lines |
| Repository | Its own `TelemetryRepository` (stateless, cheap) | Shared |
| What peers do | unknown | unknown |

**Recommendation:** A. It holds its own `TelemetryRepository` and the drop-episode timestamp, builds each WebSocket entry's resolve callback (D1), and records only for an `Api` whose parent is an `App` (Summary). A queue that isn't live drops the row as `record_blocking_event` does (Assumed).
**Pick B instead if** you'd rather keep every telemetry-row writer in one class and split `CommandExecutor` later.
**Reversibility:** easy
**Ratified:** Chose a new `ApiWriteRecorder` in `src/hassette/core/api_write_recorder.py`, one per process with its own repository and drop pacing, over methods on `CommandExecutor`, so write recording has one focused home and `CommandExecutor` doesn't grow past the size guideline for an unrelated job, accepting a second repository instance. Chosen by the user at the re-challenge's sketch comb.

## Assumed

- Parent D6's `caused_by` (its meaning and qualifying field description), D7 (background reply tracking, no deadline, no timed-out outcome, the rejected-call WARNING) and D8 (named writes only, app-owned `Api` only, `render_template` and raw methods excluded) hold, except where a decision here names the parent decision it refines or supersedes in its heading or Ratified sentence; D8 supersedes parent D7's "no row until it resolves", and D9 supersedes parent D7's "an evicted call leaves no row, only a count". The outcome values and their meanings live in D3. Evidence: parent ledger D6, D7, D8.
- Home Assistant's `call_service` and `fire_event` replies carry `{"context": {...}}` on success and error frames carry none; `set_state`'s REST response is the state object, whose `context.id` is the returned context id. Evidence: parent Assumed; prior-art brief, "HA Source Verification" (b) and (c).
- A call's execution id is captured when it's sent, from `CURRENT_EXECUTION_ID`, and reaches sync handlers' calls too: `SyncExecutor.submit` runs the handler in a copy of the caller's context (`src/hassette/core/sync_executor.py`), and `TaskBucket.run_sync` schedules the coroutine with `run_coroutine_threadsafe`, which copies the calling thread's context. A test pins both paths. Evidence: `src/hassette/context.py`, `src/hassette/task_bucket/task_bucket.py`.
- Rows enqueue through `DatabaseService.enqueue`, which drops on a full queue; a drop increments a new `PipelineCounter` member, and a `RuntimeError` from a queue that isn't live drops the row as `CommandExecutor.record_blocking_event` does. Evidence: `src/hassette/core/command_executor.py` `record_blocking_event`.
- Retention follows parent D12: `api_writes` ages out on `database.retention_days`, and the failsafe deletes it after blocking events and before app executions. Evidence: parent D12; `src/hassette/core/retention_targets.py`.
- New telemetry tables carry `session_id` referencing `sessions`, and session deletion guards on them. Evidence: `src/hassette/migrations_sql/005.sql`; `src/hassette/core/database_retention.py`.
- `fail_all` runs on reconnect cleanup and teardown, so every remaining entry resolves as `connection_lost` when its connection ends; an update dropped during shutdown leaves the row `pending` for D9's sweep, which records it as `unresolved`. Evidence: `PendingResponses.fail_all`.
- `data` is stored unredacted (D3's display string), credentials included, as parent D8 ratified and as Home Assistant's own traces do; Home Assistant's service schemas don't mark alarm or lock `code` fields as secret, so no schema-driven redaction is attempted. An explicit `SecretStr` marker is tracked separately: #3955 (accept it in write payloads) and #3956 (mask it in records and logs), from sketch-time challenge finding 2 (`review-log.jsonl`). Evidence: parent D8; `homeassistant/components/alarm_control_panel/services.yaml` and `lock/services.yaml` on HA core `dev`.
- Raw transport methods aren't recorded, and #3680 already stopped documenting them as public. Evidence: parent D8; commit `98d61316`.
- New seed scenarios and generated client types follow existing conventions. Evidence: parent Assumed; `scripts/seed_scenarios/`.

## Build

- [ ] Implementation and tests committed
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**
