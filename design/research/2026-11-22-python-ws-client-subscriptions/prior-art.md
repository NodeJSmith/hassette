---
topic: "How async Python clients used by HA integrations shape WebSocket push subscriptions"
date: 2026-11-22
status: Draft
---

# Prior Art: Python WebSocket subscription clients for HA integrations

## The Problem

`hassette-client` needs its first WebSocket API so hass-hassette can receive declared-entity state pushed over
hassette's `/ws` (spec 155 D3, #4220). The consumer must subscribe before it fetches the REST listing on every
(re)connect, skip message types it doesn't know, and resync. The open questions are the API's shape, who owns
reconnect, how the resync point is expressed, unknown-type handling, and close/auth.

## How We Do It Today

`hassette-client` is HTTP-only: `HassetteClient` takes a caller-owned `aiohttp.ClientSession`, never retries, and
sends `Authorization: Bearer <token>` when given a token. Server side, `/ws` authorizes the handshake header
(`authorize_ws`), registers the client's broadcast queue *before* sending the `connected` message, then streams
broadcasts; the client may send `ping` and `subscribe` (`logs` only today). `hassette_wire` already states that a
WS client must ignore a message whose `type` it doesn't know. hassette's own HA WebSocket client
(`WebsocketService`) owns its reconnect loop, but it is an application service, not a library. The web UI's
`use-websocket.ts` reconnects with jittered backoff and invalidates its caches on reconnect.

## Patterns Found

### Pattern A: connect + long-running `listen()`/`start_listening()` coroutine, caller owns reconnect (reload entry)
- **Used by:** zwave-js-server-python, music-assistant-client, python-matter-server, python-hass-client, aiounifi (consumer variants: zwave_js, music_assistant, matter, unifi in HA core).
- **How it works:** Library exposes `connect()` and one coroutine that runs the read loop until the socket closes. HA integration wraps it in `entry.async_create_background_task`, awaits an `init_ready` event (or equivalent) with a timeout during setup, then when the task returns outside shutdown it reloads the entry (zwave_js, music_assistant, matter) or runs its own backoff (unifi). Disconnect is signaled by the coroutine returning or raising (`ConnectionClosed`, `ConnectionFailed`, `WebsocketError`).
- **Strengths:** Library stays small; reconnect policy lives where HA lifecycle (unload, `hass.is_stopping`, reauth, `ConfigEntryNotReady`) is known; no hidden tasks in the lib; one code path for "resync" (rebuild from scratch).
- **Weaknesses:** Every consumer re-implements the supervisor; reload-on-disconnect is heavy (tears down entities); unifi's version needed ~300 lines to get backoff, jitter, stable-reset, and rate-limit handling right.
- **Example:** https://github.com/home-assistant/core/blob/dev/homeassistant/components/zwave_js/__init__.py (`client_listen`)
- **Read:** zwave-js `zwave_js_server/client.py` L151-323 (connect/listen), L433-530 (receive/handle); HA core `zwave_js/__init__.py` L1229-1265; MA `music_assistant_client/client.py` L446-565; HA `music_assistant/__init__.py` L159-185, L313-335; matter `client/client.py` L609-700 and HA `matter/__init__.py` L356-377; aiounifi `interfaces/connectivity.py` L698-770; HA `unifi/hub/websocket.py`, `unifi/hub/connection.py` L105-340; `hass_client/client.py` L406-495.

### Pattern B: callback registration returning an unsubscribe function
- **Used by:** music-assistant-client, python-matter-server, aiohue EventStream, python-hass-client, aioesphomeapi (`subscribe_states`, returns unsub in newer APIs; callback-style).
- **How it works:** `subscribe(cb, event_filter=None, id_filter=None) -> Callable[[], None]`. Subscribers are kept in a list/dict; dispatch checks filters, then calls sync callbacks directly (or `call_soon_threadsafe`) and wraps coroutine callbacks in a task whose exceptions are logged (MA `_log_subscriber_error`). Registration is independent of connection state, so subscribers survive reconnects when the same client object is reused (aiohue); in zwave/MA/matter the client is rebuilt via entry reload.
- **Strengths:** Fits HA's `async_on_unload(unsub)` idiom directly; filters keep consumers small; the pattern is already the HA convention.
- **Weaknesses:** Callback exceptions are swallowed into logs; ordering between callbacks and the initial fetch is not expressed by the API; `list.remove` in unsubscribe raises if called twice (MA, aiohue).
- **Example:** https://github.com/music-assistant/client/blob/main/music_assistant_client/client.py (`subscribe`)
- **Read:** MA `client.py` L244-267, L538-565; matter `client.py` L80-123; aiohue `events.py` L119-163; `hass_client/client.py` L257-290; aioesphomeapi `client.py` L772-778.

### Pattern C: the subscribe call returns (or is followed by) the full state, with `init_ready` signaling readiness
- **Used by:** zwave-js-server-python, python-matter-server (snapshot in the `start_listening` result); music-assistant-client (events stream while a concurrent `fetch_initial_state` task runs; `init_ready` set after fetch).
- **How it works:** zwave/matter: server-side `start_listening` command atomically registers the client for events and returns the current full state; the client builds its model from the result and only then starts dispatching events, so nothing is missed between snapshot and stream (this is a server guarantee, the library just expresses it by making the snapshot the command's return). MA: the read loop starts first; the initial fetch runs as a separate task so events can be handled during it; no explicit guarantee, but subscribe-before-fetch holds because events start at connect. In all three, `init_ready` (asyncio.Event) tells the caller setup may proceed. zwave_js also makes a server-sent `driver ready` event trigger an entry reload.
- **Strengths:** Directly gives the "subscribe first, then fetch" ordering; caller needs no on-connect hook because (re)connect means rebuild.
- **Weaknesses:** Needs server support for atomic subscribe+snapshot (hassette's server does not have this per the brief; you'd get MA's looser shape). `asyncio.Event` as handshake is clumsy; MA's concurrent fetch means events can apply to a model that is not yet populated (MA's `_handle_event` only updates providers inline).
- **Example:** https://github.com/home-assistant-libs/python-matter-server/blob/main/matter_server/client/client.py (`start_listening`)
- **Read:** zwave `client.py` L228-301; matter `client.py` L620-651; MA `client.py` L446-480.

### Pattern D: library-owned reconnect, in-band lifecycle events (aiohue) or opt-in helper (aioesphomeapi)
- **Used by:** aiohue (`EventStream`), aioesphomeapi (`ReconnectLogic`).
- **How it works:** aiohue's background reader loops forever, sleeping `min(2*attempts, 600)` s, resumes with `last-event-id`, and emits `CONNECTED` / `RECONNECTED` / `DISCONNECTED` through the same `subscribe` channel; consumers resync on `RECONNECTED`. aioesphomeapi keeps `APIClient` reconnect-free and ships `ReconnectLogic(client, on_connect=..., on_disconnect=..., on_connect_error=...)`: the library schedules backoff (and mDNS-triggered early retry) while the caller's `on_connect` coroutine does the "subscribe + list entities" resync every time; `on_connect` failure => `cli.disconnect()` so the logic retries.
- **Strengths:** Caller gets one place (`on_connect` or `RECONNECTED`) for resync; backoff correctness (reset-on-success, auth errors back off to max) is written once; opt-in helper (aioesphomeapi) keeps the core client simple.
- **Weaknesses:** More surface and more states (aioesphomeapi's state machine, locks, ~700 lines). aiohue gives no resync data itself; caller must still refetch. Lifecycle events share a channel with data events, so filter types leak.
- **Example:** https://github.com/esphome/aioesphomeapi/blob/main/aioesphomeapi/reconnect_logic.py
- **Read:** aioesphomeapi `reconnect_logic.py` L308-330, L408-447, L528-600; HA `esphome/manager.py` L599-613, L673-700, L854; aiohue `events.py` L101-118, L164-247.

### Pattern E: unknown message types are ignored, with debug log (or warn-once)
- **Used by:** zwave-js-server-python (debug log, return), music-assistant-client (debug log; unknown error codes -> generic error), python-matter-server (debug log), python-hass-client (debug log), aioesphomeapi (debug "Skipping unknown message type"), aiounifi (enum `_missing_` -> `UNKNOWN`, one `warning` per distinct key), aiohue (warning for unparsable payload; debug for unexpected SSE field).
- **How it works:** Dispatcher branches on known `type`; anything else is logged and dropped; no exception. Dropped payloads are not logged above debug where they may contain credentials (aiounifi comment: "Unknown keys are logged once, their data can hold credentials").
- **Strengths:** Newer server never breaks older client.
- **Weaknesses:** Silent skip hides upgrade need; matter's `ERROR_MAP[...]` (KeyError) shows the failure mode when this is not applied uniformly; aiohue raising `InvalidEvent` inside parse is caught by the broad except and warned.
- **Example:** https://github.com/home-assistant-libs/zwave-js-server-python/blob/master/zwave_js_server/client.py (`_handle_incoming_message`)
- **Read:** zwave `client.py` L473-530; MA `client.py` L492-536; matter `client.py` L661-693 (and `ERROR_MAP[msg.error_code]` at ~L685); hass_client L464-494; aioesphomeapi `connection.py` L1205-1222; aiounifi `models/message.py` L8-18, L120-135; aiohue `events.py` L249-275.

### Pattern F: push into a DataUpdateCoordinator without `update_method` (HA docs)
- **Used by:** documented HA pattern. [no source found] for a specific integration that does *both* push and a periodic poll on one coordinator in the peers read; the docs state that `async_set_updated_data` on a polling coordinator resets the poll timer.
- **How it works:** background listen task calls `coordinator.async_set_updated_data(...)`.
- **Strengths:** Matches hass-hassette's existing coordinator; the poll becomes a safety net.
- **Weaknesses:** Docs are silent on resync ordering.
- **Example:** https://developers.home-assistant.io/docs/integration_fetching_data/#pushing-api-endpoints
- **Read:** `docs/integration_fetching_data.md` L180-184 in developers.home-assistant clone.

## Anti-Patterns
- **Hard lookup on server-provided codes/types** (matter `ERROR_MAP[msg.error_code]`): an unknown code from a newer server raises KeyError inside the read loop. MA's `ERROR_MAP.get(code, MusicAssistantError)` with the comment "unknown codes (newer server) degrade to the generic error" is the fix.
- **Reconnect by reloading the whole config entry** (zwave_js, music_assistant, matter): works but discards entities/state; acceptable only because each rebuilds from a full snapshot.
- **Logging unknown payloads above debug** (aiounifi warns once per key but withholds data; data can hold credentials).

## Emerging Trends
- Newer code (MA client, hass_client) adds a lifecycle lock and `_shutdown` flag so a late `start_listening` cannot reopen a connection `disconnect()` is closing (hass_client `_connect`).
- Backoff with jitter plus "reset only after stable period" in HA-core's own unifi connection manager (RETRY_DELAYS 15/30/60 s, jitter 0.2), versus aiohue's linear-to-600 s.

## Comparison Table

| Project | Q1 shape | Q2 reconnect owner / disconnect signal | Q3 resync exposure | Q4 unknown types | Q5 close/stop, auth |
|---|---|---|---|---|---|
| zwave-js-server-python | `listen(driver_ready)` coroutine run as task | Caller (HA reloads entry); `listen` returns/raises | `start_listening` result = full state, then events; `driver_ready` Event | debug log, drop | `disconnect()` closes WS and awaits listen's completion event; no auth |
| music-assistant-client | `subscribe(cb, filters) -> unsub` + `start_listening(init_ready)` | Caller (HA reloads); coroutine returns | Read loop runs first; concurrent `fetch_initial_state` task; `init_ready` set after | debug log; unknown error codes degrade to generic error | `disconnect()` sets stop flag, cancels futures; token via `auth` command after the first server-info message |
| python-matter-server | `subscribe_events(cb, filters) -> unsub` + `start_listening(init_ready)` | Caller (HA reloads) | `start_listening` result = full node dump | debug log (but KeyError on unknown error code) | same as MA; no auth |
| aioesphomeapi | `subscribe_states(cb)` callbacks | Library helper `ReconnectLogic` (opt-in); `on_disconnect`/`on_connect_error` hooks | Caller's `on_connect` hook does list + subscribe each time | debug "Skipping unknown message type" | `stop()`/disconnect; noise PSK/password in connect |
| aiohue v2 EventStream | `subscribe(cb, event_filter, resource_filter) -> unsub`; `initialize()` spawns tasks | Library (linear backoff to 600 s, `last-event-id`); in-band CONNECTED/RECONNECTED/DISCONNECTED events | Caller refetches on RECONNECTED | warning/debug, continue | `stop()` cancels tasks; app key header |
| aiounifi | `await start_websocket()` with sync `callback(str)` | Caller, documented ("should be implemented by the consumer"); exception on drop | HA's recovery callback refetches after reconnect | enum `UNKNOWN`, warn once per key | `async with ws_connect(headers=...)`; cancel task |
| python-hass-client | `subscribe_events(cb) -> unsub` + `start_listening()` | Caller; raises ConnectionFailed | Caller calls `get_states` itself | debug log | `disconnect()` w/ lifecycle lock; token in-message auth |

## Gaps
- go2rtc and frigate client libraries: not read. I did not locate a WebSocket subscription client for either; no claim made.
- No peer expresses a "subscribe before fetch" ordering *in the API* beyond zwave/matter's server-side atomic `start_listening` (snapshot-in-reply). MA is the nearest to the client-driven shape (stream first, fetch concurrently), and it states no guarantee. ESPHome actually fetches before subscribing. [no source found] for an explicit ordering contract in a client-side-only design.
- Handshake `Authorization: Bearer` header on the WS handshake: only aiounifi (`ws_connect(headers=...)`) and aiohue (headers on the SSE request) do something like it; zwave/matter send no auth; MA and hass_client authenticate in-band after connect. Not verified in detail for aiohue's header name.
- Source SHAs are not pinned; URLs point to default branches as of 2026-11-22. exa-search was used for one query (returned irrelevant results), the rest was direct reading.

## Relevance to Us

- **Reconnect belongs to the caller.** Five of seven peers keep reconnect out of the library, and aiounifi says so
  in its docs. hass-hassette already has a 30 s polling coordinator that keeps working when the stream drops
  (spec 155 D3), so a library reconnect loop would duplicate a supervisor the integration needs anyway for HA's
  lifecycle (unload, `hass.is_stopping`). This matches `hassette-client`'s existing "never retries" stance.
- **Subscribe-before-fetch can be expressed without server changes.** zwave-js and matter get it from a server
  call that returns the snapshot. hassette's server registers the queue before it sends `connected`, so a client
  that waits for `connected` before returning control has a real ordering guarantee: anything broadcast after
  that point reaches the queue. That is stronger than music-assistant-client's unstated ordering and needs no
  new server command.
- **Unknown types: debug log and drop**, as every peer does and `hassette_wire` already requires. Don't log the
  payload above debug.
- **Shape:** the peers split between a `listen()` coroutine run as a background task (Pattern A) and
  `subscribe(cb) -> unsub` (Pattern B), usually both. None offers an async iterator. hass-hassette would run
  either one as `entry.async_create_background_task`.
- **Auth:** a handshake `Authorization` header (aiounifi's shape) reuses `Transport.headers`; in-band auth
  messages (MA, hass_client) would need a server change for no gain.

## Recommendation

Keep the client small, as the HA-core peers do: one connection call that opens `/ws` on the caller's session with
the existing bearer header, returns only after the server's `connected` message (the subscribe-before-fetch point),
delivers known messages parsed as `hassette_wire` models, logs and drops unknown types at debug, and ends by
returning or raising when the socket closes. Reconnect, backoff and the REST resync stay with the caller
(hass-hassette's coordinator), as in zwave_js, music_assistant, matter and unifi. Callback versus a
`listen()`-style loop is a taste call the peers don't settle; reload-the-whole-entry on disconnect is the
anti-pattern to avoid on the hass-hassette side, since its poll already covers a dropped stream.

## Sources

### Reference implementations

| # | Source (URL) | Type | Opened | Key takeaway | Relevance |
|---|---|---|---|---|---|
| 1 | https://github.com/home-assistant-libs/zwave-js-server-python/blob/master/zwave_js_server/client.py | lib code | yes | `connect()` (WS handshake, reads first `version` message) then `listen(driver_ready: asyncio.Event)` coroutine. `listen` sends `start_listening`, whose *result* is a full state dump; sets `driver_ready`, then loops receiving until closed. No reconnect. Unknown top-level `type` logged at debug and dropped. | Closest analogue: server sends a first message, subscribe+full state in one round trip. |
| 2 | https://github.com/home-assistant/core/blob/dev/homeassistant/components/zwave_js/__init__.py (`client_listen`, `async_setup_entry`) | consumer | yes | Integration runs `client.listen` as `entry.async_create_background_task`, waits on `driver_ready` vs listen_task, raises `ConfigEntryNotReady` if listen ended first. When `listen` returns after setup, it calls `hass.config_entries.async_schedule_reload` ("a new driver state will be acquired on reconnect"). Caller owns reconnect = reload entry. | Shows caller-owned reconnect with "resync = rebuild everything". |
| 3 | https://github.com/music-assistant/client/blob/main/music_assistant_client/client.py and `connection.py` | lib code | yes | `subscribe(cb, event_filter, id_filter) -> unsubscribe` plus `start_listening(init_ready: Event)`. On start, spawns `fetch_initial_state()` as a task *while the read loop is already running*, so events can arrive while the REST-like fetches are in flight (events-first, then fetch). Auth is a post-connect `auth` command with token (schema >= 28), not a header. Unknown message parse falls to a debug log; unknown error codes degrade to generic error ("newer server"). No reconnect. | Callback subscription + subscribe-before-fetch ordering; the most similar to hassette's need. |
| 4 | https://github.com/home-assistant/core/blob/dev/homeassistant/components/music_assistant/__init__.py | consumer | yes | Same shape as zwave_js: background-ish listen task, `init_ready` wait with timeout -> `ConfigEntryNotReady`; on listen end and not stopping: `async_reload`. Comment: dashboard device registration is "connection-scoped" so state may be empty after reconnect. | Caller owns reconnect via reload. |
| 5 | https://github.com/home-assistant-libs/python-matter-server/blob/main/matter_server/client/client.py, `connection.py` | lib code | yes | `subscribe_events(callback, event_filter, node_filter, attr_path_filter) -> unsubscribe`; `start_listening(init_ready)` sends `start_listening` command whose result is full node dump, sets `init_ready`, then read loop. Unknown messages debug-logged. `ERROR_MAP[msg.error_code]` is a hard lookup (KeyError on unknown code; contrast MA). No reconnect. | Same as zwave-js; shows subscribe-with-snapshot. |
| 6 | https://github.com/home-assistant/core/blob/dev/homeassistant/components/matter/__init__.py | consumer | yes | `_client_listen` identical pattern: on end, `async_reload` the entry. | Caller-owned reconnect. |
| 7 | https://github.com/esphome/aioesphomeapi/blob/main/aioesphomeapi/reconnect_logic.py and `connection.py`, `client.py` | lib code | yes | Library ships an optional `ReconnectLogic(client, on_connect, on_disconnect, on_connect_error)` helper with exponential backoff (+ zeroconf wake). It is separate from `APIClient`; caller supplies async hooks. `subscribe_states(on_state)` is a callback registration. Unknown protobuf message type: `Skipping unknown message type` at debug (connection.py ~L1214). Not a WebSocket (native API TCP socket), but same push problem. | Only peer where the library offers reconnect, as an opt-in helper with `on_connect` hook. |
| 8 | https://github.com/home-assistant/core/blob/dev/homeassistant/components/esphome/manager.py (`on_connect`/`_on_connect`) | consumer | yes | Resync lives in `on_connect`: `device_info_and_list_entities()` (fetch) then `subscribe_home_assistant_states_and_services(...)`; failures -> `cli.disconnect()` so ReconnectLogic retries. Here fetch comes *before* subscribe (entity infos define what states mean); no ordering guarantee between them is claimed. | Shows on-connect hook doing both steps every (re)connect. |
| 9 | https://github.com/home-assistant-libs/aiohue/blob/master/aiohue/v2/controllers/events.py | lib code | yes | `EventStream.initialize()` spawns reader/processor/keepalive tasks; `subscribe(cb, event_filter, resource_filter) -> unsubscribe`. Library owns reconnect: loop with `min(2*attempts, 600)` s sleep, SSE `last-event-id` resume header, and emits synthetic `EventType.CONNECTED` / `RECONNECTED` / `DISCONNECTED` events to subscribers. Malformed event: warning log; unexpected SSE key: debug. (SSE over HTTP, not WS.) | Only peer that surfaces (re)connect as an in-band event; caller resyncs on `RECONNECTED`. |
| 10 | https://github.com/Kane610/aiounifi/blob/master/aiounifi/interfaces/connectivity.py (`websocket`), `models/message.py`, `controller.py` | lib code | yes | `await controller.start_websocket()` is one long-running coroutine passed a sync `callback(str)`. Docstring: "Reconnection logic is not handled here and should be implemented by the consumer. On disconnect or error, an exception is raised." Headers passed at `ws_connect(headers=self.headers)`. Unknown message keys map to `MessageKey.UNKNOWN` via `_missing_`, warned once per key. | Documented deliberate non-handling of reconnect. Handshake headers precedent. |
| 11 | https://github.com/home-assistant/core/blob/dev/homeassistant/components/unifi/hub/websocket.py and `hub/connection.py` | consumer | yes | `_websocket_runner` task; on any end -> `connection.report_failure()` -> retry delays (15, 30, 60 s, +/-20% jitter), reconnect task logs in if needed then runs `recovery_callback` (full refetch) before marking available again; backoff reset only after the connection stays up (`CONNECTION_STABLE_PERIOD`). | Caller-owned reconnect with jitter + stable-period reset; resync = refetch after reconnect. |
| 12 | https://github.com/music-assistant/python-hass-client/blob/main/hass_client/client.py | lib code | yes | HA WebSocket client: `subscribe_events(cb, event_type) -> unsub`, `subscribe_entities`, and `start_listening()` loop. Errors raise `ConnectionFailed`/`InvalidMessage`; no reconnect. Unknown id: debug log. Callbacks scheduled with `call_soon` / background task. | Another caller-owned-reconnect example. |
| 13 | https://github.com/home-assistant/developers.home-assistant/blob/master/docs/integration_fetching_data.md (section "Pushing API endpoints") | official docs | yes | Push APIs can use `DataUpdateCoordinator` without `update_method`/`update_interval`; call `coordinator.async_set_updated_data(data)`. On a polling coordinator it also resets the poll timer. Docs say nothing about reconnect or subscribe-before-fetch. | Official basis for mixing push + coordinator. |
| 14 | https://github.com/home-assistant/developers.home-assistant/blob/master/blog/2024-03-13-deprecate_add_run_job.md and docs/integration_setup_failures.md | official docs | yes | Coroutines started from a config entry should use `entry.async_create_background_task` / `async_create_task`. `ConfigEntryNotReady` makes HA retry setup with its own backoff; the integration shouldn't log non-debug about retries. | Where the caller's listen task lives. |
