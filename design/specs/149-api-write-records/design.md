# Design: Record API writes and how each one ended

**Date:** 2026-11-09
**Status:** draft
**Mode:** sketch
**Issues:** #3677
**Parent:** design/specs/142-diagnostic-evidence/design.md
**Prior art:** design/research/2026-11-01-diagnostic-evidence/prior-art.md

## Summary

By default `call_service` sends and returns. Home Assistant's reply finds no pending entry and is dropped, so a rejected call leaves no trace, and nothing records what a run asked Home Assistant to do. This change records one row per named `Api` write with how it ended, tracks fire-and-forget `call_service` replies in the background without changing handler timing, links each row to the execution that made it, and shows the writes and `caused_by` on the execution read. It implements the parent's D7, D8 and D6's `caused_by`, refined by the decisions below. The timeline (#3678) and any web UI are out of scope.

New pieces and their homes:

- **Write records:** a new `api_writes` table (migration `src/hassette/migrations_sql/024.sql`), a `PipelineCounter` member for write-queue drops and one for evicted background entries (`src/hassette/core/pipeline_counters.py`), an insert at send and an outcome update on the telemetry repository (`src/hassette/core/telemetry/`) (D8), a startup sweep of earlier sessions' `pending` rows in `SessionManager.mark_orphaned_sessions` (`src/hassette/core/session_manager.py`) (D9), and a retention target between blocking events and app executions (`src/hassette/core/retention_targets.py`, priorities after it shift by one). `sessions` deletion gains an `api_writes` guard (`src/hassette/core/database_retention.py`).
- **Recording point:** one write function that builds the row and enqueues its insert at send, and one that enqueues its outcome update (the parent's D11, split by D8). Each named write calls the insert once at send and the update once at resolution, from its async body: `_call_service` and `_fire_event` (`src/hassette/api/service_calls.py`), `_set_state` and `delete_entity` (`src/hassette/api/entity_data.py`), and `HelperClient.create`/`update`/`delete` (`src/hassette/api/helpers.py`). `turn_on`/`turn_off`/`toggle` and the counter helpers reach `_call_service`, so they record once, as `call_service`. Only an `Api` whose parent is an `App` records (`src/hassette/app/app.py` builds it). The framework's own `Api` (`Hassette._api`, `src/hassette/core/core.py`) and `RecordingApi` don't.
- **Background reply tracking:** `PendingResponses` (`src/hassette/core/websocket_responses.py`) gains background entries that carry a resolve callback (built by the recording function, closing over the row's `write_id`, execution id, app identity, kind and operation, the app's `Api` logger and the update function; no target or data), so `PendingResponses` holds no telemetry or app references and resolves the row from the reply, in place of today's timed-out entries that only log (D1, D2, D8). `WebsocketService` gets a send path for fire-and-forget `call_service` that registers one before sending (`src/hassette/core/websocket_io.py`).
- **Read surface:** an `ApiWrite` wire model and `ExecutionTrigger.caused_by` (`wire/src/hassette_wire/telemetry.py`); `GET /api/executions/{id}` (`src/hassette/web/routes/executions.py`) returns a new `ExecutionDetail` in place of `LogsByExecutionResponse` (`wire/src/hassette_wire/logs.py`), with the client method renamed to match (`client/src/hassette_client/client.py`); `hassette execution` reads that one route and shows the writes (`src/hassette/cli/commands/log.py`); the `caused_by` subquery joins every `Execution` read and the writes-by-execution query sits beside them in `src/hassette/core/telemetry/execution_queries.py` (D5, D6).
- **Docs and generated files:** `docs/pages/core-concepts/database-telemetry.md` (table, outcomes, growth estimate, and that `data` is stored unredacted, naming alarm and lock `code` values, password-mode helper values and tokens as examples, so check `--json` output before sharing it), `docs/pages/core-concepts/api/methods.md` (what success means, the rejected-call WARNING, raw methods aren't recorded), `docs/pages/cli/commands.md`; regenerated schemas and frontend types; seed scenarios gain write rows.

Prerequisite: #3957 (transport exceptions split by delivery state) lands first; D4 maps outcomes from its classes, whose exact names the build takes from #3957 as merged.

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

**Deciding factor:** never store an outcome a later reply could contradict, reusing the mechanism that already waits for that reply.

| | A: the entry becomes a background entry on timeout or cancel; its reply resolves the row | B: resolve the row as `connection_lost` when the caller stops waiting; late reply only logs | C: new `timed_out` outcome at the timeout; cancel left as is |
|---|---|---|---|
| Slow call that succeeded | `success`, with the true reply time | `connection_lost`, wrong in meaning | `timed_out`, though it applied |
| Cancelled handler mid-call | Resolved from the reply (REST: `connection_lost` at once) | `connection_lost` | Row stays `pending` until D9's sweep |
| Outcome set | No new value | No new value, but `connection_lost` now also means "gave up" | One more value |
| Mechanism | Replaces today's timed-out entry with the same background entry fire-and-forget calls use (D2's cap covers both) | Today's entry, plus an update when the caller stops | Same as B, for the timeout only |
| Caller | Still gets `ResponseTimeoutError` at 15 s, or its cancellation | Same | Same |
| Late-reply log line | Today's line (INFO on success, WARNING on rejection), now for timeout and cancel alike; never the D7 WARNING | Kept for timeout; cancel logs nothing | Same as B |
| What peers do | Temporal records `TimedOut` only against a deadline the caller chose | unknown | Temporal: same note |

**Recommendation:** A, because it applies parent D7's reasoning to both ways an awaited caller stops waiting, and folds today's timed-out entry into the same background entry, so there is one kind of entry waiting for a reply and one cap. The cancellation is re-raised after the entry is converted. A cancelled REST write resolves as `connection_lost` at once, then re-raises, since no reply can ever arrive for it. A converted WebSocket entry logs only today's late-reply line when its reply arrives, whether it converted on timeout or cancellation; D7's rejected-call WARNING is for fire-and-forget calls only.
**Pick B instead if** you want the row resolved the moment the caller gives up, and accept `connection_lost` stretching to cover it. **Pick C instead if** you want a timeout recorded and are fine reopening parent D7's no-timed-out rule.
**Reversibility:** easy
**Ratified:** Chose turning an awaited write's entry into a background entry whenever its caller stops waiting, by timeout or cancellation, so the reply resolves the row, over resolving it as `connection_lost` or adding a `timed_out` outcome, to never store an outcome a later reply contradicts while reusing the entry that already waits for it, accepting that the row reads `pending` between the caller stopping and the reply. Widened to cancellation by sketch-time challenge finding 4 (`review-log.jsonl`) through the Finding 1 re-evaluation (D8), chosen by the user. A cancelled REST write resolves as `connection_lost` immediately, since nothing can answer it later (chosen by the user at the sketch comb). A converted entry logs only today's late-reply line, for timeout and cancellation alike, never D7's WARNING (fix chosen by the user at the sketch comb's run-3 gate).

### D2: How many background entries can wait at once, and which one goes when the cap is hit?

**Situation:** parent D7 puts fire-and-forget calls in the existing pending-reply table with a cap and counts evictions, and left the cap to this pickup. Today's cap, `TIMED_OUT_WRITE_RECORD_CAP = 100`, covers only timed-out writes. Home Assistant usually replies in milliseconds, but its WebSocket handler waits for the service to finish, so a call to a long script (`script.my_script` called directly) waits for the whole script. An app that starts a five-minute script on every motion event, or loops over 200 lights with separate calls to a slow integration, can hold hundreds of entries for a while. Under D8 the row is already in the database, so an entry holds no target or data: just its resolve callback, whose closure holds what resolving needs (`write_id`, execution id, app identity, kind and operation for the D7 WARNING, the app's `Api` logger and the update function), about 200 bytes. An evicted entry leaves its row `pending` until D9's sweep. An awaited write's live entry has a caller waiting on its future and must never be evicted.

**Deciding factor:** eviction practically never happens, with a stated memory bound.

| | A: 10,000 background entries, oldest evicted | B: 1,000, oldest evicted | C: no cap |
|---|---|---|---|
| Worst-case memory | About 2 MB | About 200 KB | Unbounded within one connection |
| 200 separate calls to a slow integration | All tracked | All tracked | All tracked |
| Burst of slow calls | Practically never evicts | Evicts after 1,000 at once | Never evicts |
| What an eviction costs | A `pending` row until the next start, then `connection_lost` | Same, sooner | n/a |
| Awaited callers | Never evicted | Never evicted | n/a |
| Meets parent D7's "with a cap" | Yes | Yes | No: reopens D7 |
| New number | One constant replaces `TIMED_OUT_WRITE_RECORD_CAP` | Same | None |
| What peers do | unknown | unknown | unknown |

**Recommendation:** A. Evict the oldest, since a call waiting longest is the one most likely still running a long script; each eviction counts on a new `PipelineCounter` member, with one WARNING per eviction episode. An awaited entry with its caller still waiting doesn't count toward the cap and is never evicted; once D1 converts it to a background entry, it counts and can be evicted like any other.
**Pick B instead if** you want the smaller number and accept evictions in large bursts. **Pick C instead if** you trust that each connection's end clears the table often enough, and want to reopen D7's cap.
**Reversibility:** easy (a constant)
**Ratified:** Chose a cap of 10,000 background entries holding only ids, with the oldest evicted, over 1,000 or no cap, so eviction practically never happens within about 2 MB, accepting that an evicted call's row stays `pending` until the next start. Revised from 1,000 full-row entries by the user through the sketch-time challenge finding 1 (`review-log.jsonl`) re-evaluation (D8).

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
| What peers do | Temporal records activity input as given | Same |

Both options also store `write_id` (D8), `outcome` (`pending`: not yet resolved; `success`: Home Assistant's handler returned, not that the device changed; `rejected`: Home Assistant answered with an error; `connection_lost`: sent, no answer will come, outcome unknown; `not_sent`: never reached Home Assistant; D1, D4, D8 and D9 say when each applies), the rejection's `error_code` and `error_message`, `context_id` where Home Assistant returns one, `sent_ts` and `resolved_ts`, `app_key`, `instance_name`, `execution_id` (NULL outside a run) and `session_id`, with a unique index on `write_id` and indexes on `execution_id`, `context_id`, `sent_ts` and `(app_key, sent_ts)`.

**Recommendation:** A, because the target is what the row exists to answer, and HA treats both call styles the same.
**Pick B instead if** you'd rather store exactly what the caller wrote and accept missing targets for the `entity_id=` style.
**Reversibility:** easy (no data to migrate before release)
**Ratified:** Chose an `api_writes` table with a normalized target (HA target keys lifted from `target` and the service data, merged with `target` winning and comma-separated ids split as Home Assistant does, stored uncut) and 147 D2-style `data` cut at 2,048 code points, over storing the target as passed, so one column answers "who wrote this entity" exactly as Home Assistant acted on it whichever call style was used, accepting that `data` no longer shows where the caller put the target keys. Merge and split rules added at the sketch comb and re-ratified by the user.

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
Every named write maps the same way over both transports. WebSocket: #3957's not-sent class → `not_sent`, the rejection class as #3957 leaves it (today `FailedMessageError`) → `rejected` with HA's `code` and message, `OutcomeUnknownError` → `connection_lost` unless D1 turns the entry into a background entry. REST (`set_state`, `delete_entity`): a failed connect → `not_sent`; an HTTP error status (`HttpRequestError`, or `EntityNotFoundError` for 404) → `rejected`, with `error_code` holding the status as a string (e.g. `"404"`) and `error_message` the reason; any other failure after the request went out (a timeout, a dropped connection, retries exhausted) → `connection_lost`. `_set_state`'s preliminary GET failing records `not_sent`, since its POST never ran.
**Pick A instead if** you'd rather keep the outcome set to the parent's three and rely on uncaught exceptions showing on the execution row. **Pick C instead if** you want no new value and accept `connection_lost` covering a call that certainly didn't apply.
**Reversibility:** easy
**Ratified:** Chose recording a write that never reached Home Assistant with a `not_sent` outcome, over no row or `connection_lost`, so runs during an outage show what they tried without implying it might have applied, accepting a fourth outcome beyond the parent's three. Each outcome maps from exactly one failure class per transport, as listed above; the WebSocket side depends on #3957 splitting the transport exceptions by delivery state, which the user chose after the sketch-time challenge (finding 3, `review-log.jsonl`) showed today's classes can't separate a socket-write failure from a codeless rejection. The REST mapping was added at the sketch comb and re-ratified by the user.

### D5: What is `caused_by`, where does it sit, and when is it computed?

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

**Recommendation:** A, because only a read-time join matches when the listener runs before the reply, and the object still says which app wrote it when there's no run. Jobs and unmatched handler rows read `None`. A write still `pending`, or resolved without a context id (`rejected`, `connection_lost`, `not_sent`, a dropped update), never matches. `caused_by` is computed on every read that returns an `Execution`: list reads, the record-only route and `ExecutionDetail`.
**Pick B instead if** you only care about run-to-run links. **Pick C instead if** keeping `caused_by` after its write row ages out matters more than matching listeners that beat the reply.
**Reversibility:** easy (read-time only, so nothing stored to migrate)
**Ratified:** Chose a `caused_by` object (`app_key`, `instance_name`, `execution_id`, `kind`, `operation`) on `ExecutionTrigger`, matched at read time to at most one write (earliest `sent_ts`) on every read that returns an `Execution`, over an execution-id string or a value stored at write time, so a listener that runs before the reply matches once the reply's update lands, a write outside a run still names its app, and a repeated context id never duplicates execution rows, accepting that `caused_by` disappears once its write row ages out, that a pending or context-less write never matches, and that only a direct context match counts: a write that sets off an HA automation is not reported on the automation's downstream runs (chain walking belongs to #3678's timeline). Re-ratified by the user after the sketch comb clarified the match rules.

### D6: How does the execution read return its writes?

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

**Recommendation:** D, because one read answers "what happened in this run", the partial-result rule moves from the CLI to one place on the server, and the break is pre-V1 and limited to the CLI's own route. `ExecutionDetail` holds `execution` (`None` while the record lags), `api_writes`, `logs`, `logs_truncated` and `retention_expired`; `--json` prints it as served, and a failed request fails the command like any other. Human output shows the summary, a writes table (time sent, kind, operation, target, outcome, error code; `data` in `--json` only), then the logs. `GET /api/telemetry/execution/{id}` stays as the record-only read.
**Pick A instead if** you want no wire break in this PR and accept a third stitched call. **Pick E instead if** you want the split kept but named as sub-resources, and accept moving the frontend's route. **Pick B instead if** one fewer call matters more than an always-`None` field in lists.
**Reversibility:** easy pre-V1
**Ratified:** Chose one detail read at `GET /api/executions/{id}` returning `ExecutionDetail` (record, API writes, logs), over a third stitched route, sub-resources, or a field on `Execution`, so each execution has one detail read and the lagging-record rule lives once on the server, accepting a pre-V1 break of `LogsByExecutionResponse` and `client.get_execution_logs` with a client-compat ignore entry. Raised by the user, who found the stitched three-route shape Frankenstein-y.

### D7: Where does the rejected-call WARNING go?

**Situation:** parent D7 adds one framework WARNING when a background-tracked `call_service` is rejected, carrying the caller's execution id. The reply is handled on the WebSocket receive task, outside the run, so a log line written there has no execution id and doesn't show under `hassette execution <id>`. Log records take their execution id from `CURRENT_EXECUTION_ID` when they're emitted (`src/hassette/logging_.py`). The app's `Api` logger is a framework logger the app owns, so app log filters and per-app debug capture (spec 148) already include it.

**Deciding factor:** the warning shows up where someone looking at that run or that app will see it.

| | A: the app's `Api` logger, with the captured execution id set while it logs | B: the WebSocket service's logger, execution id in the message |
|---|---|---|
| Shows under `hassette execution <id>` | Yes | No |
| Shows in the app's logs | Yes | No: framework service lines |
| Message | Kind, operation, HA's code and message, execution id and `write_id`; no target, since entries hold only ids (D2); the target is one `hassette execution` away | Same |
| Machinery | Set and reset the context var around one log call | None |
| What peers do | unknown | unknown |

**Recommendation:** A. The WARNING is for fire-and-forget calls only, since their callers never see an exception. Awaited calls already raise into the caller, and an awaited entry D1 converts (on timeout or cancellation) logs only today's late-reply line, never this WARNING.
**Pick B instead if** you'd rather not attribute framework lines to a run after it ended.
**Reversibility:** easy
**Ratified:** Chose logging the rejected-call WARNING on the app's `Api` logger with the captured execution id set while it logs, over the WebSocket service's logger, so the warning shows in that run's and that app's logs, accepting a framework line attributed to a run after the run ended. One WARNING per rejected call, unpaced (sketch-time challenge finding 7 (`review-log.jsonl`), chosen by the user); the context var is set and reset in a `finally`, so the receive task never carries a dead execution id into later lines. The WARNING names kind, operation, HA's code and message, execution id and `write_id`, not the target, so entries stay id-only; the entry's resolve callback closes over the app's `Api` logger, so a reload before the reply still logs under the same logger name (chosen by the user at the sketch comb). The WARNING fires for fire-and-forget calls only; converted awaited entries log only the late-reply line (D1; chosen by the user at the sketch comb's run-3 gate).

### D8: When is a write's row written? (supersedes parent D7's "a call in flight has no row until it resolves")

**Situation:** parent D7, as amended by its sketch challenge, writes one row per call once its outcome is known, so a call in flight has no row and its pending entry holds the whole row in memory. Recording at send was weighed there only as one fix among three for the `no_reply` deadline bug, and lost on "least new machinery" and the risk of a row stuck at pending. This ledger's sketch challenge found three gaps with that one cause: a cancelled awaited write gets no row (Finding 4), an empty writes list can't be told from writes still pending, evicted or lost (Finding 5), and the memory bound ignores the uncut `target` (Finding 9). Every peer in the prior-art brief records an outbound call when it's scheduled, then its outcome (Temporal's `ActivityTaskScheduled`, Step Functions, n8n). The database write queue is FIFO with one writer, and drops are counted.

**Deciding factor:** "what did this run ask Home Assistant to do" is answered from the moment of asking, including for a call still running or cut off by a crash.

| | A: insert at send as `pending`, update on resolution | B: one row at resolution (parent D7 as ratified) |
|---|---|---|
| Call in flight | Visible as `pending` | No row |
| Crash with a call in flight | Row left, resolved `connection_lost` at next start (D9) | Lost |
| Cancelled awaited write | Row exists; resolved per D1 | No row unless separately patched |
| Pending entry memory | Ids only, about 200 bytes (D2) | The whole row, `target` uncut |
| Writes per call | An insert and an update, both through the write queue | One |
| Dropped insert | Write lost, counted; the update matches nothing | Write lost, counted |
| Dropped update | Row stays `pending` until D9's sweep, counted | n/a |
| New machinery | An update statement keyed on a client-generated id | None |
| What peers do | Temporal, Step Functions and n8n record the scheduled call, then its outcome | None found |

**Recommendation:** A. Each row gets a client-generated `write_id` (UUIDv7, as `execution_id` is) at send, so the update needs nothing back from the insert, and FIFO order on the single writer guarantees the insert lands first. Every named write records this way, awaited ones included, so there's one write lifecycle.
**Pick B instead if** one queue operation per write matters more than seeing calls in flight and surviving a crash.
**Reversibility:** easy pre-release (no stored rows to migrate)
**Ratified:** Chose inserting each write as `pending` at send and updating it on resolution, over one row at resolution, so a run's calls are on record from the moment they're made, including calls in flight or cut off by a crash, accepting an update path on the write queue, two queue operations per write, and rows left `pending` when an update is dropped. Raised by the sketch challenge's convergence finding (Finding 1, superseding findings 4, 5 and 9) and chosen by the user after reviewing why the parent declined it.

### D9: What happens to a row still `pending` after its session ends?

**Situation:** under D8 a row stays `pending` when its update is dropped, when its entry is evicted (D2), or when the process ends before resolution: a crash, or a clean shutdown whose `connection_lost` updates from `fail_all` didn't reach the database. Nothing is waiting on such a call after a restart. `SessionManager.mark_orphaned_sessions` (`src/hassette/core/session_manager.py`) already runs once at startup to close out sessions an earlier process left open.

**Deciding factor:** a reader never sees `pending` on a call nothing is waiting on anymore.

| | A: at startup, set every `pending` row from an earlier session to `connection_lost` | B: leave it `pending`; the reader combines it with the session's end |
|---|---|---|
| Meaning after restart | Correct: D3's `connection_lost` | "Pending" for a call no one is waiting on |
| Crash evidence | Kept: the row exists, outcome unknown | Kept |
| Mechanism | One update in the existing orphaned-session step | None |
| What peers do | unknown | unknown |

**Recommendation:** A, because it reuses an existing startup step and never shows a stale state. The sweep covers every row whose `session_id` isn't the current session's, whether that session ended cleanly or was orphaned; swept rows keep `resolved_ts` and the error fields NULL, since no reply was observed. Rows from the current session are never swept: one left `pending` by a dropped update stays that way until the next start, and the drop is counted.
**Pick B instead if** you'd rather add no startup write and read `pending` as "last known".
**Reversibility:** easy
**Ratified:** Chose resolving every earlier session's `pending` rows as `connection_lost` in the startup orphaned-session step, whether that session ended cleanly or was orphaned, with `resolved_ts` and the error fields left NULL, over leaving them `pending`, so no row claims a wait nothing is doing, accepting one more statement at startup and that a current-session row left `pending` by a dropped update stays that way until the next start. Chosen by the user in the Finding 1 re-evaluation; sweep scope and swept-row fields re-ratified after the sketch comb.

## Assumed

- Parent D6's `caused_by` (its meaning and qualifying field description), D7 (background reply tracking, no deadline, no timed-out outcome, the rejected-call WARNING) and D8 (named writes only, app-owned `Api` only, `render_template` and raw methods excluded) hold, except where this ledger refines or supersedes them: D1 (awaited writes whose caller stops waiting), D2 (the cap), D3 (row shape and `data` format), D4 (`not_sent` and the outcome mapping) and D8 (row written at send, superseding parent D7's "no row until it resolves"). The outcome values and their meanings live in D3. Evidence: parent ledger D6, D7, D8.
- Home Assistant's `call_service` and `fire_event` replies carry `{"context": {...}}` on success and error frames carry none; `set_state`'s REST response is the state object, whose `context.id` is the returned context id. Evidence: parent Assumed; prior-art brief, "HA Source Verification" (b) and (c).
- A call's execution id is captured when it's sent, from `CURRENT_EXECUTION_ID`, and reaches sync handlers' calls too: `SyncExecutor.submit` runs the handler in a copy of the caller's context (`src/hassette/core/sync_executor.py`), and `TaskBucket.run_sync` schedules the coroutine with `run_coroutine_threadsafe`, which copies the calling thread's context. A test pins both paths. Evidence: `src/hassette/context.py`, `src/hassette/task_bucket/task_bucket.py`.
- Rows enqueue through `DatabaseService.enqueue`, which drops on a full queue; a drop increments a new `PipelineCounter` member, and a `RuntimeError` from a queue that isn't live drops the row as `CommandExecutor.record_blocking_event` does. Evidence: `src/hassette/core/command_executor.py` `record_blocking_event`.
- Retention follows parent D12: `api_writes` ages out on `database.retention_days`, and the failsafe deletes it after blocking events and before app executions. Evidence: parent D12; `src/hassette/core/retention_targets.py`.
- New telemetry tables carry `session_id` referencing `sessions`, and session deletion guards on them. Evidence: `src/hassette/migrations_sql/005.sql`; `src/hassette/core/database_retention.py`.
- `fail_all` runs on reconnect cleanup and teardown, so every background entry resolves as `connection_lost` when its connection ends; an update dropped during shutdown leaves the row `pending` for D9's sweep. Evidence: `PendingResponses.fail_all`.
- `data` is stored unredacted (D3's display string), credentials included, as parent D8 ratified and as Home Assistant's own traces do; Home Assistant's service schemas don't mark alarm or lock `code` fields as secret, so no schema-driven redaction is attempted. An explicit `SecretStr` marker is tracked separately: #3955 (accept it in write payloads) and #3956 (mask it in records and logs), from sketch-time challenge finding 2 (`review-log.jsonl`). Evidence: parent D8; `homeassistant/components/alarm_control_panel/services.yaml` and `lock/services.yaml` on HA core `dev`.
- Raw transport methods aren't recorded, and #3680 already stopped documenting them as public. Evidence: parent D8; commit `98d61316`.
- New seed scenarios and generated client types follow existing conventions. Evidence: parent Assumed; `scripts/seed_scenarios/`.

## Build

- [ ] Implementation and tests committed
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**
