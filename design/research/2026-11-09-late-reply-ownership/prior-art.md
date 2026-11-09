---
topic: "Who owns a correlated call's outcome when the caller stops waiting before the reply"
date: 2026-11-09
status: Draft
---

# Prior Art: Late-reply ownership in request/response correlators

## The Problem

A client that correlates requests and replies over one connection keeps a pending table keyed by message id. When the awaiting caller times out or is cancelled before the reply arrives, someone has to decide the call's outcome: the caller (from what it saw), or the reply (whenever it comes). Hassette's write records (spec 149, sketch-challenge convergence Finding 1) need one owner per row, and three edge cases (a timeout whose class overlaps with rejection, a reply delivered just before a cancel, a cancel during the socket write) keep attracting separate guards.

## How We Do It Today

`PendingResponses` (`src/hassette/core/websocket_responses.py`) registers a future per message id before `send_json`; `send_and_await_response` (`src/hassette/core/websocket_io.py`) waits 15 s. On timeout a non-retried write's entry is marked timed out and kept (cap 100), so a late reply is logged; on cancellation the `finally` discards the entry and the reply is ignored. No durable record exists. Spec 149 D1 (as ratified) converts the entry to a background entry with a resolve callback when the caller stops waiting.

## Patterns Found

### Pattern 1: Caller owns the entry and the verdict; late reply dropped/logged
**Used by**: NetDaemon (awaited calls), python-hass-client, OpenTelemetry spans, Temporal (with a separate arbiter).
**How it works**: The caller registers, sends, waits. On timeout or cancel it removes the entry (and records TimedOut/Cancelled). A reply arriving later finds no entry: debug log or silent drop. NetDaemon also republishes it on a message stream.
**Strengths**: One writer per outcome, no races between reply and cancel handling, no leaked entries.
**Weaknesses**: The actual server outcome is lost; for a write that HA still executes, the record permanently says "timed out" while the light turned on.
**Example**: https://github.com/net-daemon/netdaemon/blob/HEAD/src/Client/NetDaemon.HassClient/Internal/HomeAssistantConnection.cs
**Read**: NetDaemon HomeAssistantConnection.cs L196-325 and ResultMessageHandler.cs; python-hass-client hass_client/client.py L230-245, ~L466; OTel/Temporal secondary (docs highlights only).

### Pattern 2: Entry outlives the caller's wait; late reply logged (Hassette's current shape)
**Used by**: AppDaemon.
**How it works**: Timeout/cancel just stops waiting (the future is cancelled by `wait_for`); the map entry stays, together with the request context. The late reply pops the entry and logs "Request already timed out". Cleared on reconnect.
**Strengths**: A late reply still carries information and can be attributed to its request.
**Weaknesses**: Outcome only in a log line, never in a durable record; entries leak if the reply never comes (HA lost or restarted) until reconnect; cancel is converted to a return value and the cancel is swallowed (a bug-shaped choice).
**Example**: https://github.com/AppDaemon/appdaemon/blob/HEAD/appdaemon/plugins/hass/hassplugin.py
**Read**: hassplugin.py L205-225, L277-300, L395-440.

### Pattern 3: Correlator owns resolution; the peer's reply is the one outcome
**Used by**: vscode-jsonrpc / LSP (by protocol), home-assistant-js-websocket (by omission).
**How it works**: Entry lives until the peer answers or the connection dies. Caller cancel is expressed to the peer (`$/cancelRequest`) and the reply (possibly a RequestCancelled error) resolves the entry. The caller's await is a view on the entry, not the owner.
**Strengths**: Exactly one outcome per id, late reply always lands, no unattributed replies.
**Weaknesses**: Needs a peer that always replies; HA does not cancel and a lost reply leaves the entry open, so a connection-loss sweep is mandatory (js-websocket `_rejectWaiting`; vscode `responsePromises` flushed on close, connection.ts L1551).
**Example**: https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/
**Read**: vscode-jsonrpc connection.ts L908-945, L1425-1475; js-websocket connection.ts L311-335, L420-480. No project found that attaches a durable-record callback to the correlator entry; [no source found] for that exact hybrid.

### Pattern 4: Distinguish "not sent" (write failure) from "sent, no answer"
**Used by**: vscode-jsonrpc (`MessageWriteError`), NetDaemon (entry removed + exception on write failure), js-websocket (removes entry on sync send error).
**How it works**: Registration precedes the write; failure of the write, and only that, removes the entry and surfaces a distinct error. Everything after a completed write is "sent, outcome unknown". vscode also handles cancel-before-write-completes by sending the cancel after the write.
**Strengths**: Gives the record a truthful "not sent" state.
**Weaknesses**: A task cancelled mid-`await write` is ambiguous (frame may be partially/fully on the wire). None of the clients I read classify that case separately: NetDaemon passes the token into `SendMessageAsync` and removes the entry; AppDaemon does not handle cancel at the write at all; python-hass-client leaks the entry. [no source found] for a client that records "cancelled during write, sent state unknown".
**Read**: all four files named above.

### Pattern 5: Don't bother
**Used by**: Node-RED (via js-websocket: no per-call timeout, no cancel handling), python-hass-client (debug log, no timeout), home-assistant-js-websocket.
**How it works**: Unknown/late replies are ignored with a debug/warn log or nothing; callers apply their own timeouts. gRPC docs state the same stance explicitly: client and server verdicts "may not match" and pre-cancel changes are not rolled back.
**Strengths**: Minimal state.
**Weaknesses**: No audit of writes; late success invisible.
**Read**: js-websocket connection.ts; python-hass-client client.py; gRPC docs (secondary: highlights).

## Anti-Patterns
- Registering before the write but putting the write outside the cleanup scope: python-hass-client leaks the entry on write failure (client.py L239-244).
- Swallowing `CancelledError` and returning a status dict (AppDaemon L430-433): hides cancel from the caller's task machinery.
- A span/row that is created at send and never ended when the owner is cancelled or killed (Elixir OTel report: https://elixirforum.com/t/how-to-solve-opentelemetry-and-timeouts/62409). Applies directly to a `pending` row: some owner must always resolve it, including at connection loss and process shutdown.

## Gaps
- Question 2 (reply set on the future just before the caller is cancelled): none of the sources handle it explicitly. Under asyncio semantics a task cancelled after the future completes but before the task resumes loses the result (reasoning from asyncio behavior, not a read source); NetDaemon removes the entry at reply time so nothing is logged and the result is dropped in `WaitAsync`; AppDaemon's `done()` check only covers the future being cancelled first. A correlator-owned record resolution (callback fired at `set_result` time) is the only structure that avoids this, and I found no project that does it.
- No project found with a durable per-call write record at all; AppDaemon's `ServiceCallStatus` and `ad_status` result is the nearest (in-memory, returned to caller).
- pyscript: not read. It calls HA in-process (hass.services), no websocket correlator, so not applicable.
- home-assistant-libs/hass-client: repo does not exist; used music-assistant/python-hass-client.
- Temporal and OTel were read through search highlights, not full pages or SDK source.

## Relevance to Us

Every peer keeps the outcome in one place, but none attaches a durable per-call record to the correlator: the HA clients drop or log late replies (patterns 1, 2, 5), and the protocols that care about the late reply (LSP, js-websocket) keep the entry until the peer answers or the connection closes (pattern 3). Home Assistant has no per-command cancel and finishes `call_service` after the client gives up, so a timeout is "outcome unknown" and the late reply is the only source of truth; that is pattern 3's premise. Hassette's D1 hand-off (caller owns, then converts) is a hybrid none of them use, and it is where the three guards accumulate. Only a callback fired at reply delivery avoids losing a reply set on the future just before a cancel; no peer does this, but no peer records outcomes either. "Not sent" is distinguished only for write failures (pattern 4), matching #3957's split; a cancel mid-write is treated by nobody as its own state.

## Recommendation

Pattern 3 with a single owner: the pending entry owns the row from registration, its reply resolves the row whenever it arrives (caller waiting or not), and `fail_all` on connection close resolves what's left (the flush js-websocket and vscode-jsonrpc do). The caller records only `not_sent`, from #3957's class. A cancel during the socket write is not special-cased by any peer; accept it as a documented limitation (the entry resolves at connection close). Accepting rather than guarding is consistent with patterns 1 and 5, which every HA client follows for its simpler non-recording case.

## Sources

See the Sources Found section above for each URL and whether it was opened.
## Sources Found

### home-assistant-js-websocket (HA frontend client; also what Node-RED uses)
- **URL**: https://github.com/home-assistant/home-assistant-js-websocket (lib/connection.ts, `sendMessagePromise` ~L311, `handleMessage` ~L420-480)
- **Type**: reference implementation
- **Opened**: yes
- **Key takeaway**: `commands: Map<id,{resolve,reject}>`. Entry is set before send; removed only on the reply, on connection loss (`_rejectWaiting`), or if `send` throws synchronously. There is NO per-call timeout and no cancel path. The reply handler comment says "No info is fine" for results with no entry. The reply handler owns resolution; the caller never removes anything.
- **Relevance**: closest "correlator owns the entry from registration" example, but only because there is no caller-side timeout to race with. No durable record exists.

### Node-RED contrib home-assistant-websocket
- **URL**: https://github.com/zachowj/node-red-contrib-home-assistant-websocket (package.json L53 depends on `home-assistant-js-websocket ^9.6.0`; src/homeAssistant/createSocket.ts)
- **Type**: reference implementation
- **Opened**: yes (grep + package.json; custom timeouts found only for handshake/auth/heartbeat/close-drain, not per call)
- **Key takeaway**: Delegates correlation to js-websocket, so inherits the same behavior. Its only timeouts are connect/auth/heartbeat.
- **Relevance**: confirms the "just don't bother with a per-call outcome" case.

### AppDaemon hass plugin
- **URL**: https://github.com/AppDaemon/appdaemon/blob/HEAD/appdaemon/plugins/hass/hassplugin.py (`websocket_send_json` ~L395-440, `receive_result` ~L277-300)
- **Type**: reference implementation
- **Opened**: yes
- **Key takeaway**: Sends first, then registers `_result_futures[id]`, then `asyncio.wait_for(future, ws_timeout)`. On timeout: returns `{"success": False, "ad_status": "TIMEOUT"}`, logs a warning; the dict entry is NOT removed, so the late reply finds a cancelled/done future and logs "Request already timed out for {id}" and pops the entry. On `CancelledError`: it swallows the cancel, returns `ad_status=TERMINATING`, entry also left in place; late reply logged the same way. Entries are cleared on reconnect (L592-595). `_request_context[id]` keeps the original request so the late-reply log can say what it was.
- **Relevance**: nearest match to Hassette's current design (timeout leaves entry so late reply is logged). Note ordering: send precedes registration, and a cancel during `send_json` is not distinguished from cancel while waiting. The late reply is only logged (log line, no durable outcome).

### NetDaemon HassClient
- **URL**: https://github.com/net-daemon/netdaemon/blob/HEAD/src/Client/NetDaemon.HassClient/Internal/HomeAssistantConnection.cs (L196-232 `SendCommandAsyncInternal`, L272-325 `WaitForPendingResultAsync`/`HandleIncomingMessage`/`CancelPendingResult`) and Internal/Helpers/ResultMessageHandler.cs
- **Type**: reference implementation
- **Opened**: yes
- **Key takeaway**: `ConcurrentDictionary<int, TaskCompletionSource>` registered BEFORE write, under an id+send semaphore. If the write throws, the entry is removed and the exception rethrown (a distinct "not sent" path). The wait is `WaitAsync(timeout, cancelToken)`; on timeout OR cancel the caller removes the entry (`TryRemove` + `TrySetCanceled`). A late reply then hits `_pendingResults.TryRemove` and misses, but `HandleIncomingMessage` still publishes every message to `_hassMessageSubject`, so a late result is visible to subscribers though never correlated. Fire-and-forget `SendCommandAsync` hands the task to `ResultMessageHandler`, a background tracker that logs failed results, timeouts ("did not get response in timely fashion") and swallows cancels as expected; the tracker is drained on dispose (5 s cap).
- **Relevance**: the "caller removes entry on timeout/cancel, late reply dropped" pattern, with a separate durable-ish owner (the background handler) only for fire-and-forget writes. Good model for "sent vs not sent" at the write.

### music-assistant python-hass-client
- **URL**: https://github.com/music-assistant/python-hass-client (hass_client/client.py L230-245 `send_command`, ~L466-476 reply handling)
- **Type**: reference implementation
- **Opened**: yes
- **Key takeaway**: `_result_futures[id]=future; await send; try: await future finally: pop(id)`. Caller owns removal. Late reply: `LOGGER.debug("Received result for unknown message with ID")` and dropped. Registration happens before the write but the write sits OUTSIDE the try/finally, so a failed write leaks the entry. No timeout inside the client. `send_command_no_wait` exists and never registers.
- **Relevance**: the "caller owns, late reply dropped with a debug log" pattern, and a pitfall (leak on write failure).

### vscode-jsonrpc (LSP client lib)
- **URL**: https://github.com/microsoft/vscode-languageserver-node/blob/main/jsonrpc/src/common/connection.ts (`sendRequest` ~L1425-1475, `handleResponse` ~L908-945)
- **Type**: reference implementation
- **Opened**: yes
- **Key takeaway**: `responsePromises` map entry is registered before `messageWriter.write`. Caller cancellation does NOT remove the entry; it sends a `$/cancelRequest` notification and keeps waiting for the server's reply, which resolves the promise (cancel = a protocol message, not a local abandon). Write failure deletes the entry and rejects with `ErrorCodes.MessageWriteError`, separating "not sent" from everything else. A cancel requested before the write finishes is sent right after the write (`tokenWasCancelled`). A reply with no entry is traced and ignored.
- **Relevance**: shows the correlator entry staying alive until the peer answers, and the sent/not-sent split.

### LSP specification, cancellation
- **URL**: https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/ (section "Cancellation Support")
- **Type**: standard
- **Opened**: yes (via exa-search contents/highlights)
- **Key takeaway**: "A request that got canceled still needs to return from the server and send a response back. It can not be left open / hanging", and may carry partial results; error code `RequestCancelled` (-32800) advised. So the peer's reply is the single authoritative outcome and the client always gets one.
- **Relevance**: protocol-level version of "reply always resolves the record". Home Assistant has no equivalent (see next entry), so Hassette cannot rely on a reply that signals cancellation.

### Home Assistant core websocket_api
- **URL**: https://github.com/home-assistant/core/blob/HEAD/homeassistant/components/websocket_api/commands.py (`handle_call_service` L325-345) and connection.py/http.py
- **Type**: reference implementation (server side)
- **Opened**: yes
- **Key takeaway**: `call_service` runs `hass.services.async_call(blocking=True)` in a handler task and sends a result when done. Nothing ties the handler to a client timeout; there is no per-command cancel message (only `unsubscribe_events` for subscriptions). Only a closed connection cancels the connection's handler tasks. So a client that timed out still has its service executed, and the result arrives later.
- **Relevance**: the timeout means "don't know", never "did not happen". The late reply is the only way to learn the real outcome, which is the argument for the correlator keeping the entry.

### gRPC deadlines and cancellation
- **URL**: https://grpc.io/docs/guides/deadlines/ ; https://grpc.io/docs/what-is-grpc/core-concepts/ ; https://grpc.io/docs/guides/cancellation/
- **Type**: documentation
- **Opened**: via exa-search highlights (not full page)
- **Key takeaway**: "both the client and server make independent and local determinations of the success of the call, and their conclusions may not match" (server succeeds, client sees DEADLINE_EXCEEDED). Cancellation notifies the server; "Changes made before a cancellation are not rolled back." The server is expected to stop work, so the client's local verdict is final for the client.
- **Relevance**: documented acceptance that the client record can say "deadline exceeded" while the server completed. Supports recording a distinct "timed out, outcome unknown" status.

### Temporal activity timeouts
- **URL**: https://docs.temporal.io/encyclopedia/detecting-activity-failures ; https://docs.temporal.io/troubleshooting/request-failures
- **Type**: documentation
- **Opened**: via exa-search highlights
- **Key takeaway**: The Temporal Service (a third party to caller and worker) owns the outcome and event history. A worker that finishes after StartToClose gets `NOT_FOUND` on `RespondActivityTaskCompleted`: "the Service discarded the in-flight task". The late result is rejected and the timeout recorded.
- **Relevance**: opposite design to what Hassette is considering: a late completion is deliberately discarded because the timeout already finalized the record. Only works because the record owner is separate from the worker and can reject late reports. Hassette's `api_writes` row has no such arbiter unless the correlator plays that role.

### OpenTelemetry client spans
- **URL**: https://opentelemetry.io/docs/specs/otel/trace/api/ ; https://elixirforum.com/t/how-to-solve-opentelemetry-and-timeouts/62409 ; https://oneuptime.com/blog/post/2026-02-06-fix-go-http-client-context-canceled-otelhttptrace/view
- **Type**: standard / experience reports
- **Opened**: via highlights only
- **Key takeaway**: "Any span that is created MUST also be ended. This is the responsibility of the user"; after end it is non-recording. In practice, when the caller is cancelled or killed the span often never ends (Elixir forum report), or ends with "context canceled" even if the response was in flight (Go report). Spans are caller-owned, and late data after end is dropped.
- **Relevance**: the standard answer for client spans is caller-owned and ended at caller cancel; a late reply cannot amend the span. Documented pitfall: an unended span on cancel (equivalent to a `pending` row stuck forever).

