# Design: Stream declared entity state over `/ws`, with WebSocket streams in hassette-client

**Date:** 2026-11-22
**Status:** ratified
**Mode:** sketch
**Issues:** #4220
**Parent:** design/specs/155-hacs-app-entities/design.md
**Prior art:** design/research/2026-11-22-python-ws-client-subscriptions/prior-art.md

## Summary

hass-hassette learns about app-declared entity state only from its 30 s poll of `GET /api/apps`. A sensor an app
sets, or a switch after its handler finishes, can take up to 30 s to reach Home Assistant. This change pushes each
entity state change on hassette's `/ws` stream, tagged with the listing's `boot_id` and `revision`. It also gives
`hassette-client` its first WebSocket API, which hass-hassette's #73 will use. The poll stays as the resync and repair
path (parent D3).

Where each new piece lives:

- **Wire message:** a new `WsServerMessage` member and its data model in `wire/src/hassette_wire/ws.py`, exported from
  `hassette_wire` (D1).
- **Publishing:** `IntegrationService.set_job` (`src/hassette/core/integration_service.py`) hands the committed state
  to a new `RuntimeQueryService` method (`src/hassette/core/runtime_query_service.py`), which builds the message and
  puts it on every client queue (D2, D3). Declaration commits publish nothing (D4).
- **`/ws` route:** `src/hassette/web/routes/ws.py` gains no subscription logic (D3), but rejects a failed handshake with
  REST's 401 problem response and counts it with the failed-auth tracker (D9).
- **Client:** a new `listen()` method on `HassetteClient` (`client/src/hassette_client/client.py`), with the socket handling
  in a new module beside `transport.py`, reusing the transport's session, base URL and bearer header (D5, D6), with
  caller-requested type filtering (D8) and the handshake and stream-end error mapping (D9). `listen` recognizes the
  server's first message by its `connected` type tag, outside the caller's `types`; any other first message, or the
  socket closing before `connected`, raises `HassetteConnectionError` (Posture: loud failure).
- **Frontend:** a no-op case in `frontend/src/hooks/use-websocket.ts`, plus regenerated `frontend/ws-schema.json` and
  `frontend/src/api/ws-types.ts` (D7).
- **Docs:** a streaming section in `docs/pages/web-ui/python-client.md` covering `revision`'s apply semantics for
  consumers: its ordering scope (spec 158 D4), that it skips values (D4), and that only a listing repairs a lost delta
  (D1, parent D3).

Out of scope: hass-hassette's subscription, reconnect loop and apply logic (NodeJSmith/hass-hassette#73). Closing slow
`/ws` clients (#4217). A monitoring UI for declared entities (#4387). Any change to the 30 s poll.

## Posture

- **Failure handling:** loud failure, and the client never retries (as today). A delta lost to a full client queue is
  repaired by the next poll (parent D3), so the drop policy is unchanged. A known message type that fails to parse
  ends the stream with a client error instead of being skipped.
- **Compatibility:** hassette's Python API may break freely (pre-V1). The wire change is additive: a new `/ws` message
  type, which the WS compat check's forward run allows. The `hassette-client` API is new.
- **Scope:** minimal. Entity-state messages on `/ws` and one client `listen()` API. No slow-client policy (#4217) and no UI
  beyond the case the exhaustive switch requires.
- **Rollout:** ships outright, likely in the same release as #4392. No flag. No API schema floor bump: an older server
  sends no entity messages, and the poll still covers it.
- **Hardening:** project defaults.
- **Altitude:** build. One session builds it against the current code.

## Decisions

### D1: What does an entity state message carry?

**Situation:** `set_job` changes one entity's state and bumps the hassette-wide `revision`. hass-hassette applies a
listing for an instance when its revision is equal to or newer than the last it applied, and a pushed delta only when
strictly newer (spec 158 D4, parent D3). The listing already describes an entity as a flat `DeclaredEntity` (spec 158
D6). Peers push a per-entity value: ESPHome state messages, zwave-js value events, MQTT state topics. Some instances
declare many sensors (one real-corpus app publishes about 25).

**Deciding factor:** HA gets the new state at the least new wire surface, with apply rules hass-hassette already has.

| | A: One message per changed entity, carrying its full `DeclaredEntity` | B: One message per instance, carrying all its entities (a mini-listing) | C: A signal-only hint; the client refetches `GET /api/apps` |
|---|---|---|---|
| Fields | `boot_id`, `revision`, `app_key`, `instance_name`, `entity: DeclaredEntity` | `boot_id`, `revision`, `app_key`, `instance_name`, `entities: list[DeclaredEntity]` | none (like `apps_changed`) |
| Apply rule in hass-hassette | Parent D3's strictly-newer delta rule, unchanged | The listing's equal-or-newer rule, per instance | The listing's rule |
| A dropped message | Stale until the next poll (accepted, parent D3) | Healed by the instance's next message | Healed by the next hint |
| Message size | One entity | All the instance's entities, on every `set()` (25 entities for the busy corpus app) | Tiny, but each hint costs a full `/api/apps` fetch |
| Latency | One hop | One hop | Two hops: message, then a REST round trip |
| Reuses wire models | `DeclaredEntity` | `DeclaredEntity` | `AppsChangedData` shape |
| Peers | ESPHome, zwave-js, MQTT | none found | hassette's own `log_hint`/`apps_changed` (UI only) |

**Recommendation:** A, because it is what every peer pushes, matches parent D3's delta rule as ratified, and reuses
`DeclaredEntity`, so hass-hassette can parse a pushed entity with its listing code. The type is
`entity_state_changed`.
The message follows the existing envelope and the `hassette_wire` naming rule: `EntityStateChangedWsMessage` with
`type: "entity_state_changed"`, `data: EntityStateChangedData` and `timestamp`, where `EntityStateChangedData` carries
`boot_id`, `revision`, `app_key`, `instance_name` and `entity: DeclaredEntity`.
**Pick B instead if** you'd rather a dropped delta heal on the instance's next change than on the next poll, at the
cost of resending the whole instance on every `set()`. **Pick C instead if** you want no new data model and accept two
hops and a full listing fetch per change.
**Reversibility:** easy before hass-hassette#73 ships. After that the message is wire contract.
**Ratified:** Chose one `entity_state_changed` message per changed entity (`EntityStateChangedWsMessage` carrying `EntityStateChangedData` with `boot_id`, `revision`, `app_key`, `instance_name` and the entity's full `DeclaredEntity`) over per-instance snapshots or a signal-only hint, to push what peers push under parent D3's delta rule with the listing's entity model, accepting that a dropped delta stays stale until the next poll and that the client can't detect the drop (sketch challenge, Finding 9); #4217, closing slow clients so they reconnect and resync, is the fix for that.

### D2: How does a committed state change get onto the `/ws` queues?

**Situation:** `set_job` runs on the single database writer: it commits, updates memory, then bumps `revision`, so
writes are serialized in commit order (spec 157 D10). `RuntimeQueryService` owns the client queues and already reads
`IntegrationService` for the listing. Its other `/ws` messages come from bus listeners (`app_status_changed`,
`service_status`), but the bus spawns a task per delivery, so two events published back to back are not guaranteed to
reach the queues in order. Under D1's strictly-newer rule an out-of-order pair loses the older delta until the next
poll: an app that sets sensor `a` (revision 5) and then sensor `b` (revision 6) would leave `a` stale whenever `b`
arrives first.

**Deciding factor:** messages reach each client in revision order, after the commit.

| | A: `set_job` calls a `RuntimeQueryService` publish method directly, after the revision bump | B: `set_job` sends a hassette event; a `RuntimeQueryService` bus listener broadcasts it |
|---|---|---|
| Order on the wire | Revision order: the single writer runs the jobs in order and the queue put is part of the job | Not guaranteed: one task per delivery |
| Committed before published | Yes, the call follows the commit in the same job | Yes |
| Matches existing `/ws` sources | No: the first message not driven by the bus | Yes, like `app_status_changed` |
| Coupling | `IntegrationService` knows `RuntimeQueryService` (the reverse link already exists) | Through a new event topic; apps could also listen |
| Cost on the writer | One short lock and a `put_nowait` per client, inside the write job | One event publish |
| Web API disabled | The publish finds no clients and does nothing | The listener isn't registered; the event goes nowhere |

**Recommendation:** A, because order on the wire is what keeps D1's strictly-newer rule from losing deltas, and only
the single writer gives that order for free.
The order holds only while the publish method takes the already-built `boot_id`, `revision`, instance key and entity
as arguments, is awaited inline in `set_job` right after the revision bump (never spawned as a task), and reads no
service state after its first await. A test pins that two back-to-back `set()` calls reach a registered client queue in
revision order.
The publish has no expected failure (sketch challenge, Finding 4): it builds the message from the committed entity
through the validated wire model, and when `RuntimeQueryService` isn't wired (the app-testing harness, which runs no
web server) it finds no clients and does nothing, without going through the raising `runtime_query_service`
accessor. There is no catch: an exception left is a bug and propagates out of `set()` (Posture). The publish path is
tested in hassette's own integration tests against a real `RuntimeQueryService`, not through the app-testing harness.
**Pick B instead if** you'd rather keep every `/ws` message bus-driven and accept an occasional out-of-order drop that
the next poll repairs (or pair B with D1's option B, whose snapshots don't mind order).
**Reversibility:** easy; internal only.
**Ratified:** Chose `set_job` calling a `RuntimeQueryService` publish method directly, awaited inline after the revision bump with the already-built values and finding no clients when that service isn't wired, over a bus event with a listener, so each client receives entity messages in guaranteed revision order after the commit (the bus promises no order between deliveries to one `PARALLEL` framework listener) and `set()` raises only on a genuine publish bug, accepting the first `/ws` message not driven by the bus and a short broadcast inside the write job. The bus-driven `app_status_changed` keeps its coincidental ordering and no sequence number; #4147 owns that and now notes hass-hassette #73 as a second consumer.

### D3: Which `/ws` clients receive entity messages?

**Situation:** every `/ws` client gets every broadcast, except `log_hint`, which goes only to clients that sent
`subscribe` with `logs: true`. That filter runs when a message leaves the client's queue, and the route sends no
acknowledgement for `subscribe`. hass-hassette has to start receiving before it fetches the listing (parent D3). The
server registers the queue before it sends `connected` (`websocket_endpoint`), so a client that waits for `connected`
is already receiving everything broadcast after that point. The web UI shows no declared entities (#4387) and sends
`subscribe` only for logs. Every client shares a 256-message queue.

**Deciding factor:** subscribe-before-fetch holds with no new protocol.

| | A: Every client, like `app_status_changed` | B: Opt-in through `subscribe`, with a new `subscribed` acknowledgement the client waits for | C: Opt-in through `subscribe`, no acknowledgement |
|---|---|---|---|
| Subscribe-before-fetch | Holds once `connected` arrives | Holds once the acknowledgement arrives | Broken: a message dequeued before the server reads `subscribe` is dropped, and the client can't tell when it's safe to fetch |
| New protocol | None | A client flag, an ack message type, and `subscribe` semantics (today each `subscribe` replaces the previous one) | A client flag |
| Web UI traffic | Receives and ignores entity messages | None | None |
| Queue pressure on UI tabs | Entity messages share the UI's 256 slots | None | None |
| Peers | ESPHome streams every subscribed state after one subscribe | HA's `subscribe_events` returns a result before events | none |

**Recommendation:** A, because `connected` already marks the point after which nothing is missed, and the only cost is
UI tabs discarding messages they don't use.
**Pick B instead if** you expect apps that set sensors fast enough for entity messages to crowd UI tabs' queues.
**Pick C instead if** never: it loses the ordering the change exists for.
**Reversibility:** easy to move A → B later; B's ack becomes wire contract once a client waits for it.
**Ratified:** Chose sending entity messages to every `/ws` client over opt-in through `subscribe` with or without an acknowledgement, so waiting for `connected` is the subscribe-before-fetch point with no new protocol, accepting that web UI tabs receive and discard entity messages in their shared 256-slot queues. The underlying gap (`subscribe` has no acknowledgement, each one replaces the last, and its filter runs at dequeue) is #4418.

### D4: Does a declaration commit send anything on `/ws`?

**Situation:** `commit_job` replaces an instance's declared set when it reaches `running` and bumps `revision`. The
committed entities can carry new state: a value restored from the database, or a `set()` made during
`on_initialize`. The parent's Breakdown says declaration changes reach the integration through the listing, which D9's
diff reads. hass-hassette creates entities only from the listing, behind its trusted-list gate. The instance's status
change to `running` already goes out as `app_status_changed`, which #73 applies to availability.

**Deciding factor:** a newly running instance's entities show the right state soon, without a second path for
creating entities.

| | A: Nothing; the listing delivers it | B: One D1 message per committed entity | C: A per-instance "entities changed" hint |
|---|---|---|---|
| New entity reaches HA | Next poll, or a refresh #73 triggers on `running` | Ignored until the listing creates it (only the listing creates entities) | Refetch |
| Restored state on known entities | Next poll, or that refresh | Pushed | Refetch |
| A removed entity | Listing | Not expressed | Refetch |
| New wire surface | None | None beyond D1 | A second message type |
| Peers | ESPHome resends its full entity list on connect, not deltas | — | — |

**Recommendation:** A, because entity creation and removal already belong to the listing, and #73 can refetch on the
`running` status it already receives. A restored value is usually the value HA already shows.
**Pick B instead if** you want an `on_initialize` `set()` to reach HA without #73 refreshing on `running`. **Pick C
instead if** you want a server-side signal for "this instance's set changed" that the UI could use later.
**Reversibility:** easy; adding messages later is additive.
**Ratified:** Chose publishing nothing on `/ws` for a declaration commit over per-entity messages or a per-instance hint, so entity creation, removal and a newly running instance's state all reach the integration through the listing alone, accepting that a restored or `on_initialize` value waits for the next poll unless hass-hassette (#73) refetches on the `running` status.

### D5: What does the `hassette-client` stream API look like?

**Situation:** `hassette-client` is HTTP-only. It uses a caller-owned `aiohttp.ClientSession`, never retries, and raises
`HassetteClientError` subclasses. hass-hassette needs to open `/api/ws`, know when it may fetch the listing, read
parsed messages (entity states, and `app_status_changed` for availability), and run its own reconnect. Five of seven
peers leave reconnect to the caller (zwave-js, music-assistant-client, matter, aiounifi, python-hass-client), and every
peer logs and drops unknown types at debug. Peers expose a long-running `listen()` coroutine, `subscribe(cb) -> unsub`,
or both. None offers an async iterator (prior-art brief).

**Deciding factor:** subscribe-before-fetch is hard to get wrong, and the client stays reconnect-free like the rest of
`hassette-client`.

| | A: Async context manager and iterator: `async with client.stream() as stream:` enters after `connected`, then `async for message in stream` | B: `await client.listen(on_message, on_connected=...)` (plus D8's `types=`), run as a background task; awaits `on_connected` before dispatching | C: `client.subscribe(cb) -> unsubscribe`, with a library-owned reconnect task (aiohue's shape) |
|---|---|---|---|
| Subscribe-before-fetch | Structural: the caller can fetch only inside the block, which opens after `connected` | Through the `on_connected` hook | The library calls a resync hook on each (re)connect |
| Reconnect | Caller: a loop around the `async with` | Caller: restart `listen` | Library: new retry policy in a client that never retries |
| Errors from the caller's code | Raised in the caller's own loop | Raised out of `listen` | Swallowed into logs |
| Backpressure | Natural: the socket is read only as fast as the caller iterates | Callback runs inline | Callback runs inline |
| Close | Leaving the block closes the socket | Cancel the task | `unsubscribe()` and a stop method |
| Messages passed on | Originally every known `WsServerMessage`; narrowed by D8 to the caller's requested types, others skipped unvalidated at debug | Same | Same |
| Peers | none | zwave-js, music-assistant-client, matter (`start_listening`) | aiohue |

**Recommendation:** A, because the ordering hass-hassette needs falls out of the block's shape, and the caller's
reconnect loop is plain code with no callbacks. Peers use callbacks to fan out to many subscribers, and this client
has one consumer per stream. When the socket closes, iteration ends with a `HassetteConnectionError` (or the matching
existing subclass) instead of ending quietly, so a dropped stream is never mistaken for a finished one.
**Pick B instead if** you want hass-hassette's code to match the HA-core peers it sits beside. **Pick C instead if**
you'd accept retry logic in the client to keep hass-hassette's code to one call.
**Reversibility:** hard once a hass-hassette release depends on it: it's a published client API.
**Ratified:** Chose a `listen()` coroutine taking `on_message` and `on_connected` callbacks (its `types=` argument is D8), run by the caller as a background task, over an async context manager with an iterator or a library-owned `subscribe(cb)` with reconnect, to match the zwave-js, music-assistant-client and matter shape that HA integrations already use, accepting that subscribe-before-fetch depends on the caller putting its listing fetch in `on_connected` rather than on the code's shape. The user's answer after a clarification round: a departure from peers here wasn't worth the narrow gain. Its contract: `listen` opens `/api/ws` on the caller's session with the transport's bearer header, waits for `connected`, awaits `on_connected()` before it dispatches anything, then awaits `on_message` for each message of a type the caller requested (D8) in arrival order (never spawning a task, so order holds and the caller's exceptions propagate out of `listen`), skips every other type at debug without validating it, and raises `HassetteConnectionError` (or the matching existing subclass) when the socket closes; cancelling the task closes the socket. It never reconnects. Sketch challenge (Finding 12): `on_connected`'s docstring says to fetch the listing there on every connect, because a fetch made before `listen` (such as a coordinator's first refresh) can miss changes made before the stream opened; no docs-page example. Accepted limitation (sketch challenge, Finding 10): a hassette restart between `connected` and the listing fetch can let old-boot deltas still queued on the old socket overwrite the new boot's listing until that socket closes and the reconnect refetches; `connected` carries no `boot_id`, and peers avoid the window by returning the snapshot on the same socket rather than tagging the hello.

### D6: How does a stream notice a dead connection?

**Situation:** if hassette's host vanishes without closing the TCP connection, an open WebSocket can wait for the next
frame indefinitely, and hass-hassette's push would stay dead while its poll carried on. aiohttp's `ws_connect` has
`heartbeat=`, which sends protocol pings and closes the socket when no pong arrives. Uvicorn answers protocol pings
without app code. The server route also answers a JSON `{"type": "ping"}` with `pong`, which the web UI doesn't use for
liveness.

**Deciding factor:** a silent dead socket ends the stream within a bounded time, with no new knob unless one is
needed.

| | A: aiohttp `heartbeat` at a fixed client constant (30 s) | B: The same, as a keyword argument on `listen()` with that default | C: None; the caller adds its own timeout |
|---|---|---|---|
| Dead socket detected | Within about 1.5 heartbeat intervals | Same, tunable | Only if the caller builds it |
| New public surface | None | One parameter | None |
| Server change | None | None | None |
| Peers | HA core passes `heartbeat=` to `ws_connect` in several integrations (secondary: not opened for this brief) | — | zwave-js, matter (no heartbeat in the library) |

**Recommendation:** A, because it bounds the failure that would otherwise leave push dead with no symptom, and nobody
has asked to tune it.
**Pick B instead if** you expect a deployment (a slow reverse proxy, say) that needs a different interval. **Pick C
instead if** you'd rather keep the library free of liveness policy, as zwave-js does.
**Reversibility:** easy; A → B is additive.
**Ratified:** Chose aiohttp's protocol `heartbeat` at a fixed 30 s client constant over a tunable `listen()` parameter or no heartbeat, so a silently dead socket makes `listen` raise within about 1.5 intervals and the caller's reconnect runs, accepting liveness policy in the library that zwave-js and matter leave out and no way to tune it until someone needs to. Accepted limitation (sketch challenge, Finding 11): on aiohttp releases that reset the heartbeat only on frames `receive()` returns (3.10 does; the installed 3.14 resets on received data), a `listen` callback that blocks for about 45 s ends a healthy stream, and the caller's reconnect handles it.

### D7: What does the web UI do with an entity message?

**Situation:** `use-websocket.ts` ends its message `switch` with a `never` check, so a new union member fails the
frontend typecheck until it gets a case. The UI shows no declared entities (#4387).

**Deciding factor:** the typecheck passes and the UI does no wasted work.

**Recommendation:** an explicit no-op case, with a comment that #4387 adds a consumer.
**Pick invalidating `queryKeys.manifests()` instead if** any current page renders entity data, which none does today.
**Reversibility:** easy.
**Ratified:** Chose an explicit no-op case in the UI's message switch, with a comment pointing to #4387, over invalidating the manifests query, so the exhaustive typecheck passes and open tabs don't refetch `/api/apps` on every sensor `set()`, accepting that the UI ignores entity messages until #4387 adds a consumer.

### D8: Which `/ws` message types does `listen()` parse?

**Situation:** added by the sketch challenge (Finding 1, converging Findings 2 and 3). D5 originally had `listen` parse
every `WsServerMessage` type. hass-hassette needs two: `entity_state_changed` for state and `app_status_changed` for
availability (#73). The rest (`connected`, `log_hint`, `connectivity`, `service_status`, `execution_completed`,
`apps_changed`) are web-UI traffic, and `execution_completed` arrives in frequent batches. Under the Posture a parse
failure of a parsed type ends the stream, so parsing everything lets a bad change to an ignored message kill push on
every reconnect. `WsServerMessage` is a strict discriminated union (`Field(discriminator="type")` in
`wire/src/hassette_wire/ws.py`), so validating a message with an unknown `type` raises: "skip unknown types" needs
"known" decided before validation. The wire-compat check's forward run already blocks breaking shape changes to every
message type (`WS_CONTRACT` in `tools/check_wire_compat.py`); nothing tests the released client's parse of WS messages
(`client_compat` replays HTTP fixtures only).

**Deciding factor:** the stream fails only on messages its caller uses, and unknown types are told from malformed ones
with no new wire surface.

| | A: Caller passes the types it wants: `listen(on_message, *, types=(...), on_connected=...)` | B: A fixed client-owned set (`entity_state_changed`, `app_status_changed`), exported as a constant | C: Parse the full union; fix the tag check and compat coverage separately |
|---|---|---|---|
| A type the caller ignores breaks the stream | Never: skipped by its `type` tag, unvalidated | Never | Yes |
| How "known" is decided | The `type` Literal of each requested class, read before validating | Same, from the fixed set | A tag-set export, or catching pydantic's tag error |
| Client contract | Whatever a caller requests | Exactly two types | The whole union |
| Adding a type later (#4387's UI) | Caller passes one more class | Client release | Already included |
| New public surface | One required parameter | One constant | None |
| `execution_completed` parse cost for hass-hassette | None | None | Every batch |
| Peers | Subscribe filters by event type (music-assistant-client, matter, aiohue; prior-art brief Pattern B) | none found | none found |

**Recommendation:** A, because it is the peers' subscribe-with-filter shape, settles both gaps in one move, and the
stream can break only on a message its caller asked for.
**Pick B instead if** you want the client's contract to be exactly two named messages and accept a client release
whenever a consumer needs another type. **Pick C instead if** you want `listen` to be a general `/ws` client and will
build a tag-set export and WS compat fixtures for it.
**Reversibility:** hard once a hass-hassette release depends on it (published client API).
**Ratified:** Chose a required `types=` argument naming the `WsServerMessage` member classes the caller wants over a fixed client-owned set or parsing the full union, so a message type the caller ignores (or one newer than the client) is skipped by its `type` tag without validation and can never end the stream, accepting one more required parameter and no client-side parse check for WS messages beyond the existing shape check. `listen` reads each message's `type` first, compares it with the `type` Literal of each requested class, validates leniently only a match, and passes `on_message` an instance of one of the requested classes; a requested type that fails to parse ends the stream (Posture).

### D9: How does `/ws` reject a bad token, and which errors does `listen()` raise?

**Situation:** added by the sketch challenge (Finding 5). `websocket_endpoint` rejects an unauthorized handshake with
`websocket.close(WS_POLICY_VIOLATION_CLOSE_CODE)` before `accept()`, which Starlette sends as a bare HTTP 403 with no
body. REST answers the same bad token with a 401 `problem_response(ProblemCode.NOT_AUTHENTICATED, ...)` from
`DefaultDenyMiddleware` (`src/hassette/web/middleware.py`), and only those 401s reach `_FailedAuthTracker`, so
repeated bad-token handshakes on `/ws` are never counted or warned about. The web UI already works around the missing
signal (`confirmAuthRejection` in `use-websocket.ts`, whose comment still mentions a 1008 close no client sees).
`hassette-client` maps HTTP failures with `error_class_for(status, problem)`, where a 401 is `AuthenticationError`
and a bodyless 403 is `ForbiddenError`. `HassetteConnectionError`'s docstring describes only a request that never got a
complete HTTP response, not a stream that opened and later ended. Starlette 1.3 provides
`WebSocket.send_denial_response` (the ASGI WebSocket Denial Response extension), falling back to a 403 close when the
server lacks the extension.

**Deciding factor:** a bad token fails the same way on `/ws` as on REST, at the server, so the client needs no special
case.

| | A: Server rejects with REST's 401 problem response via `send_denial_response` and records it with the failed-auth tracker; client maps it through `error_class_for`; stream ends raise `HassetteConnectionError` with a widened docstring | B: Leave the server; client maps the bodyless 403 to `ForbiddenError` (documented) and widens `HassetteConnectionError` | C: As B, plus a new `StreamClosedError(HassetteConnectionError)` for a stream that ends |
|---|---|---|---|
| Bad token on `/ws` in the client | `AuthenticationError`, same as REST | `ForbiddenError`, unlike REST | `ForbiddenError` |
| Failed-auth tracker covers `/ws` | Yes | No | No |
| Server change | About ten lines in the route | None | None |
| New public class | None | None | One |
| Web UI | Unchanged (browsers can't read the handshake status); stale comment corrected | Unchanged | Unchanged |
| Peers | aiounifi sends auth as handshake headers and maps HTTP errors (prior-art brief) | — | zwave-js: `ConnectionClosed` vs `ConnectionFailed` |

**Recommendation:** A, because it fixes the inconsistency where it starts, closes the tracker's gap on `/ws`, and
lets hass-hassette's reauth key off the same exception for REST and the stream.
**Pick B instead if** you want this change to leave the server's handshake untouched. **Pick C instead if**
hass-hassette needs to tell "never connected" from "connected, then ended".
**Reversibility:** easy on the server; the client's exception mapping is published API once #73 depends on it.
**Ratified:** Chose rejecting an unauthorized `/ws` handshake with REST's 401 `NOT_AUTHENTICATED` problem response through `send_denial_response`, recorded by the failed-auth tracker, over mapping the bare 403 to `ForbiddenError` or adding a `StreamClosedError`, so a bad token raises `AuthenticationError` from `listen` exactly as from REST and repeated `/ws` failures are counted, accepting a server-side change beyond the streaming work. In `listen`, a handshake rejection maps through `error_class_for` like any HTTP failure (no raw aiohttp exception escapes), and a stream that opened and then ended (server close, heartbeat timeout, reset) raises `HassetteConnectionError`, whose docstring is widened to cover it. The build verifies uvicorn delivers the 401 (Starlette's fallback is a 403 close) and corrects the stale 1008 comment in `use-websocket.ts`.

## Assumed

- Parent D3 holds: push lowers latency, the 30 s poll keeps applying entity state, hass-hassette subscribes before it
  fetches on every (re)connect, and it skips message types it doesn't know with a debug log. Its "counter per
  instance" was superseded by spec 158 D4: one hassette-wide `revision` and one `boot_id`, read from
  `IntegrationService.boot_id` / `.revision`. Evidence: parent D3; `design/specs/158-app-entities-web-api/design.md`
  D4.
- Parent D6 holds: a state write is committed before its value is published, and a failed write publishes nothing.
  Evidence: parent D6; `IntegrationService.set_job` bumps `revision` only after `persist_state` returns.
- A `set()` whose state equals the current state writes nothing and bumps nothing (spec 157 D13), so it publishes
  nothing. Evidence: the early return in `set_job`.
- The server registers a client's queue before it sends `connected`, so every broadcast after `connected` reaches that
  client unless its queue is full. Evidence: `websocket_endpoint` in `src/hassette/web/routes/ws.py` calls
  `register_ws_client()` before sending `connected`.
- `/ws` authorizes the handshake's `Authorization: Bearer` header, and the client already builds that header.
  Evidence: `authorize_ws` in `src/hassette/web/auth/__init__.py`; `Transport.headers` in
  `client/src/hassette_client/transport.py`.
- The WS route is mounted at `/api/ws`. Evidence: `app.include_router(ws_router, prefix=API_PREFIX)` in
  `src/hassette/web/app.py`.
- A WS client must ignore a message whose `type` it doesn't know, and the compat check allows adding a message type in
  the forward run. Evidence: the `hassette_wire` package docstring; `WS_BASE_LACKS_MESSAGE_TYPE_CHECK_ID` in
  `tools/check_wire_compat.py`.
- `aiohttp>=3.10` is already a `hassette-client` dependency, so a WebSocket needs no new dependency. Evidence:
  `client/pyproject.toml`.
- The app-testing harness runs `IntegrationService` through an in-memory subclass (`HarnessIntegrationService`) and
  never calls `Hassette.wire_services()`, so `_runtime_query_service` is unset there. Evidence:
  `src/hassette/testing/_harness_resources.py`; `src/hassette/core/core.py` (`wire_services` is the only assignment).

## Build

- [ ] Implementation and tests committed
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**
