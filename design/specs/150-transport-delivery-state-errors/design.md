# Design: Split transport exceptions by delivery state

**Date:** 2026-11-09
**Status:** built
**Mode:** sketch
**Issues:** #3957
**Prior art:** design/research/2026-11-09-transport-delivery-state-errors/prior-art.md

## Summary

Hassette's WebSocket and REST exceptions are named for the mechanism that failed, so neither a caller nor #3677's write records can tell whether a command reached Home Assistant. `FailedMessageError` covers an HA error reply, a failed socket write and (through `ResponseTimeoutError`) a timeout. `ConnectionClosedError` covers the closed send gate and (through `RetryableConnectionClosedError` → `ResponseLostError`) a drop after sending. `ClientConnectionResetError` escapes `send_json` raw, and REST doesn't separate a failed connect from a failure after the request went out.

This change regroups them by delivery state, as a pre-V1 break: **not sent** (certain it never reached HA), **rejected** (HA answered with an error), **outcome unknown** (sent, no answer). Every raise site, `except` site and retry predicate in `src/` moves to the new classes; docs pages that name the classes describe the three states; tests pin the raise and retry behavior below. #3677's ledger (`design/specs/149-api-write-records/`, on the `3677` branch) maps its WebSocket outcomes one-to-one onto these classes and its REST outcomes through its own rule (149 D4; REST status errors stay outside `CommandRejectedError`, D6), so this lands first.

Out of scope: #1820's full documented raise contract for the `Api` surface, `StateProxy`'s `ResourceNotReadyError` (cache not yet synchronized; unchanged), REST status errors' own classes beyond D6, and the harness gaining a way to simulate not-sent.

New pieces and their homes:

- **The class changes** (D1–D3, D7): `src/hassette/exceptions.py` (classes and `__all__`). `CommandNotSentError` is raised by `Api.ws_send_and_wait`/`Api.ws_send_json`'s readiness check (`src/hassette/api/api.py`), `WebsocketIoMixin.send_json`'s send gate and socket write (`src/hassette/core/websocket_io.py`, D4), and `ApiResource.rest_request`'s closed-session check and connect failure (`src/hassette/core/api_resource.py`, D6). Other sites that raise or catch the renamed classes: `src/hassette/core/websocket_responses.py` (`respond_if_necessary` raises the rejected class, `fail_all` sets `WebsocketClosedError`), `src/hassette/core/websocket_reconnect.py` (receive-loop end), `src/hassette/api/api.py` (`_ws_helper_call`), `src/hassette/testing/recording_api.py` (helper `not_found`), and `NOT_RETRYABLE` in `src/hassette/core/api_resource.py` (its vestigial `ConnectionClosedError` entry goes).
- **The retry rule** (D5): the two `retry_if_exception` predicates in `src/hassette/core/websocket_io.py` (`subscribe_events`, `send_and_wait`) share one module-level predicate function there. REST's rule (D8) stays in `is_retryable_rest_failure` in `api_resource.py`, which also takes the request method.
- **REST post-send mapping and connect bound** (D6): inside `ApiResource.rest_request`'s existing `except` chain; the connect-bound constant at the top of `src/hassette/core/api_resource.py`; the total-timeout caveat in `rest_request_timeout_seconds`'s docstring (`src/hassette/config/config.py`).
- **Tests:** existing tests that name the old classes (`tests/unit/test_exceptions.py`, `tests/unit/core/test_websocket_outcome_unknown.py`, `tests/integration/websocket/`, `tests/unit/test_recording_api_helpers.py`, `tests/integration/test_api_helpers.py` and the rest found by grep) move with the renames. New behavior to pin: D4's write-failure mapping, D5's retry/no-retry outcome per class on both WebSocket methods, D6's ordered REST mapping including the closed-session check and connect bound, and D8's per-method REST retry.
- **Docs:** `docs/pages/core-concepts/api/methods.md` (errors and unknown outcomes), `docs/pages/core-concepts/api/managing-helpers.md` and `docs/pages/core-concepts/api/snippets/managing-helpers/outcome_unknown.py`, `docs/pages/troubleshooting.md` (exception list and "HA unreachable" bullets), `docs/pages/operating/index.md` and `operating/snippets/catch_ha_unreachable.py`, `docs/pages/testing/harness.md` and `testing/snippets/testing_outcome_unknown.py`, `docs/pages/core-concepts/api/index.md`, `docs/pages/recipes/daily-notification.md`, and docstrings that name the classes (`api/sync.py`, `api/service_calls.py`, `api/entity_data.py` (add the REST transport errors to `delete_entity`'s `Raises:`), `models/helpers/input_number.py`, `input_text.py`), plus the review questions in `src/hassette/api/REVIEW.md` that name `FailedMessageError` and the rewrap.

## Posture

- **Failure handling:** loud; this reclassifies errors and adds no retries or fallbacks. Retry eligibility is D5 (WebSocket) and D8 (REST).
- **Compatibility:** break freely (pre-V1, no shims). The PR carries one `BREAKING CHANGE:` footer listing the renames and deletion (D2, D3), the re-parenting (D1, D7), the dropped codeless-rejection retry (D5), the REST mapping and its silent catch changes (D6), and the narrowed REST write retries (D8). Downstream apps (hautomate) update separately.
- **Scope:** minimal: the three delivery states and their raise/catch/retry sites in `src/`, plus the docs that name the classes. #1820's contract is out.
- **Rollout:** ships outright; no flag or deprecation.
- **Hardening:** project defaults.
- **Altitude:** `build`; one session builds it, and #3677's build waits on it.

## Decisions

### D1: Do the three delivery-state classes share a base class?

**Situation:** apps catch connection trouble today with a hand-built tuple (`docs/pages/operating/snippets/catch_ha_unreachable.py` catches `aiohttp.ClientError, TimeoutError, ConnectionClosedError`; hautomate's `RECOVERABLE_HA_ERRORS` falls back to all of `HassetteError`). After the split, "HA unreachable or didn't answer" is not-sent plus outcome-unknown, and "HA said no" is the rejected class. A shared base would give one `except` for a grouping; none gives three independent classes under `HassetteError`.

**Deciding factor:** a catch that matches what the caller means, without a base that lumps states with different retry safety.

| | A: three siblings under `HassetteError`, no shared base | B: a `TransportError` base over not-sent and outcome-unknown; rejected stays outside | C: one base over all three |
|---|---|---|---|
| "HA unreachable" catch | Two names: `except (NotSent, OutcomeUnknown)` | One name | One name, but it also catches rejections, which aren't "unreachable" |
| Retry-safety confusion | None: each class is one state | Low: base mixes "safe to retry" and "might have applied", but its name says transport | Higher: mixes all three |
| What peers do | NetDaemon: separate classes, no shared base | hass-client `TransportError` (`CannotConnect`, `ConnectionFailed`) with `FailedCommand` outside; aiohttp `ClientConnectionError` vs `ClientResponseError` | No peer found |
| Public surface | Smallest | One more class | One more class |

**Recommendation:** A, because the issue exists to make the delivery state explicit and a two-name tuple is short; a base whose name doesn't say which state you're in reintroduces the ambiguity. The docs snippet shows the tuple.
**Pick B instead if** you expect most apps to want one "HA connectivity" catch and are fine with that base not telling them whether the command applied. **Pick C instead if** you want a single "the command didn't succeed" catch (callers already have `HassetteError` for that).
**Reversibility:** easy (adding a base later is additive)
**Ratified:** Chose three sibling classes directly under `HassetteError` over a `TransportError` base or a base over all three, so each class names exactly one delivery state, accepting that an "HA unreachable" catch names two classes.

### D2: What are the classes named?

**Situation:** the rejected class today is `FailedMessageError`. Narrowing it to HA error replies under the same name is a *silent* break: an app that wrote `except FailedMessageError` to catch timeouts or socket failures still imports fine and simply stops catching them. A rename turns that into an `ImportError` at load. The not-sent class is new. `OutcomeUnknownError`, `ResponseTimeoutError` and `ResponseLostError` already name their states and keep their names.

**Deciding factor:** the break is loud where meaning changes.

| | A: `CommandNotSentError` + rename `FailedMessageError` → `CommandRejectedError` | B: `NotSentError` + keep `FailedMessageError` | C: `CommandNotSentError` + keep `FailedMessageError` |
|---|---|---|---|
| App catching `FailedMessageError` for timeouts | Fails at import, fixed once | Silently stops catching | Silently stops catching |
| Names read as a set | Yes: not sent / rejected / outcome unknown | Mixed | Mixed |
| Churn | Every `FailedMessageError` site, docs, harness (`RecordingApi` raises it for `not_found`), hautomate | Not-sent sites only | Not-sent sites only |
| `from_error_response`, `code`, `original_data` | Move to `CommandRejectedError` unchanged | Unchanged | Unchanged |

**Recommendation:** A, because a narrowed meaning under an old name is exactly the silent break the posture's "break freely" shouldn't produce, and the three names then match the three states.
**Pick B instead if** the shorter name matters more than the parallel naming and you accept the silent narrowing of `FailedMessageError`. **Pick C instead if** you want the descriptive new name but no rename churn.
**Reversibility:** hard (public names; a second rename is another break)
**Ratified:** Chose `CommandNotSentError` and renaming `FailedMessageError` to `CommandRejectedError` over a shorter new name or keeping `FailedMessageError`, so the changed meaning fails loudly at import and the three names read as a set, accepting rename churn across docs, the harness and downstream apps.

### D3: What happens to `ConnectionClosedError` and `RetryableConnectionClosedError`?

**Situation:** after the split, no app-facing path raises either: the closed gate becomes not-sent, and `ResponseLostError` stops inheriting from `RetryableConnectionClosedError`. `RetryableConnectionClosedError` (with `close_code`) still has an internal job: `raw_recv` raises it to end the receive loop, `recv_loop` and the reconnect loop (`websocket_reconnect.py`) catch it, and `PendingResponses.fail_all` sets it on waiting futures for `send_and_wait` to convert into `ResponseLostError`. After the split, `ConnectionClosedError` is only its parent, plus a vestigial entry in REST's `NOT_RETRYABLE` (REST never raises it).

**Deciding factor:** no public name keeps an old meaning it no longer has.

| | A: delete `ConnectionClosedError`; `RetryableConnectionClosedError` becomes a direct `HassetteError` child, internal-only | A′: A, with the internal class renamed `WebsocketClosedError` | B: merge into one internal class named `ConnectionClosedError` (with `close_code`) | C: keep both unchanged |
|---|---|---|---|---|
| App catching `ConnectionClosedError` for "not connected" | Fails at import | Fails at import | Silently stops catching | Silently stops catching |
| Internal signal | Unchanged behavior | Renamed at every internal site; "Retryable", which meant the connection and not the command, is gone | Renamed at every internal site | Unchanged |
| Classes left | One | One | One | Two, one unused |

**Recommendation:** A′, because no public name keeps an old meaning (the same loud-break reason as D2), and the internal signal is named for its transport without the misleading "Retryable", which meant the connection and not the command.
**Pick A instead if** you want the least internal churn and don't mind the long name. **Pick B instead if** you prefer the shorter name for the internal signal and accept the silent change for apps that catch it. **Pick C instead if** you want no change beyond re-parenting.
**Reversibility:** easy
**Ratified:** Chose deleting `ConnectionClosedError` and renaming `RetryableConnectionClosedError` to `WebsocketClosedError` (a direct `HassetteError` child, internal-only, keeping `close_code`) over keeping the long name, merging under `ConnectionClosedError`, or keeping both, so no public name keeps an old meaning and the internal signal names its transport, accepting a rename at every internal site.

### D4: Which socket-write failures count as not sent?

**Situation:** `send_json` re-raises `ClientConnectionResetError` raw and wraps every other exception as `FailedMessageError`. Hassette's WebSocket runs uncompressed (`ws_connect` without `compress`, aiohttp's default `compress=0`), so the frame write is synchronous and its failures come in two classes. `ClientConnectionResetError` is raised only by the closing-transport checks before the write (`send_frame` and `_write_websocket_frame` in `aiohttp/_websocket/writer.py`): certainly not sent. After the write, a paused transport makes `send_frame` await the drain wait, and a connection lost during that wait fails it with a plain `ConnectionError("Connection lost")` (`aiohttp/base_protocol.py`, `connection_lost` → drain waiter); the frame is then in the transport buffer and, if another task's frame is queued behind it, may have been fully sent. Asyncio routes socket and TLS write errors to `connection_lost` rather than raising them, so these are the only two connection failures `send_json` can see. Other exceptions are mostly caller bugs: a payload `json.dumps` can't serialize raises `TypeError` before anything is sent, and today that becomes `FailedMessageError` with `code=None` and is retried. No peer models a write failure on an open socket as never-sent (prior-art brief).

**Deciding factor:** the not-sent class is trustworthy for #3677's `not_sent` row and for retry safety, without detection machinery peers don't build.

| | A: connection errors (`ClientConnectionResetError` and other `ConnectionError`s, caught as `ConnectionError`) → not sent, drain case documented; other exceptions, `OSError`s such as `TimeoutError` included, propagate unwrapped | B: every exception → not sent | C: connection errors → outcome unknown; others unwrapped | D: tell the closing-transport check from the drain by message text | E: `ClientConnectionResetError` → not sent; any other `ConnectionError` from the write (the drain wait) → `ResponseLostError`; other exceptions unwrapped |
|---|---|---|---|---|---|
| Accuracy | Wrong only in the rare drain case with a frame behind it | Same, plus caller bugs filed as transport | Never wrong, but most real "not sent" cases read as "may have applied" | Exact, while aiohttp's messages hold | Exact on hassette's uncompressed path |
| Unserializable payload | Raw `TypeError` naming the bug | Not-sent, looks like an outage | Raw `TypeError` | Raw `TypeError` | Raw `TypeError` |
| #3677's `not_sent` row | Recorded for the closed-transport case | Also for caller bugs | Never from a write | Recorded, exactly | Recorded, exactly; the drain case resolves through `fail_all` as `connection_lost`, with no second writer |
| Machinery | None | None | None | String matching on a dependency's messages | One more `except` clause keyed on aiohttp's exception class |
| Peers | None treat it as never-sent | None | aiohttp/botocore group post-connect writes with lost responses | None | aiohttp/botocore group post-connect write failures with lost responses |

**Recommendation:** A, because the drain case needs an over-limit send buffer *and* a frame queued behind ours, and treating every connection error from the write alike keeps hassette independent of which exception class aiohttp happens to raise where (E's split holds only on today's uncompressed path). The `CommandNotSentError` docstring states the edge case: a connection lost while waiting for the send buffer to drain is reported as not sent although the frame may have gone out. `send_json` keeps its existing log lines with the command label, both for the not-sent case and for an exception it lets propagate unwrapped.
**Pick E instead if** an exact not-sent is worth depending on aiohttp's class split on the uncompressed path. **Pick B instead if** you want `send_json` to keep one catch-all. **Pick C instead if** every write-time connection error should read as outcome unknown. **Pick D instead if** exactness matters more than depending on aiohttp's message text.
**Reversibility:** easy
**Ratified:** Chose mapping every connection error from the socket write (`ClientConnectionResetError` and other `ConnectionError`s) to `CommandNotSentError`, letting other exceptions propagate unwrapped with `send_json`'s labelled log lines kept, over E's class-based split of the drain case, a catch-all, outcome-unknown for all, or message-text splitting, so hassette doesn't depend on aiohttp's internal exception choices, accepting that a connection lost during the drain wait with a frame queued behind ours is reported as not sent (documented on the class; #3677's `not_sent` and `fail_all`'s `connection_lost` may both write that row, the caller's landing last). Re-ratified after the sketch-time challenge.

### D5: Which WebSocket failures does `send_and_wait` (and `subscribe_events`) retry?

**Situation:** both retry when the error is `FailedMessageError` with `code is None`. With today's classes that retries: a timeout (when `retry_on_timeout`), an HA error reply that lacks a code, and a non-reset socket-write exception (in practice a caller bug like an unserializable payload). It does not retry a closed gate, `ClientConnectionResetError`, a lost response, or a coded rejection. The issue asks to keep current behavior, but the `code is None` rule is the thing being removed: no peer retries an error reply for lacking a code, and D4 makes the caller-bug case raise unwrapped. Retry budget: `MAX_RETRY_ATTEMPTS = 5` with `wait_exponential_jitter()` (about 15 s of backoff). `Api.ws_send_*` already fails fast with not-sent when the connection isn't CONNECTED, so a not-sent inside `send_and_wait` means the connection dropped in the last moment and reconnect, not a retry, is the recovery.

**Deciding factor:** retry only what is safe and has a chance of succeeding, decided by delivery state.

| | A: retry outcome-unknown timeouts (if `retry_on_timeout`) only; never not-sent, rejected or lost | B: also retry not-sent | C: reproduce today exactly (timeouts, codeless rejections, non-reset write failures) |
|---|---|---|---|
| Codeless HA rejection | Raised at once (change) | Raised at once (change) | Retried, re-sending a command HA refused |
| Closed gate / reset mid-call | Raised at once (as today) | Up to ~15 s of retries, then not-sent, usually still disconnected (change) | Raised at once |
| Timeout on a read | Retried (as today) | Retried | Retried |
| Rule keyed on | Class (`ResponseTimeoutError`) | Classes | Class plus `code`, plus a not-sent subtype to tell reset from other writes |
| Peers | gRPC A6 doesn't retry unknown outcomes by default, but hassette already opts reads in | gRPC A6: never-sent always retried | No peer |

**Recommendation:** A, because it keeps every realistic case's current behavior except the codeless-rejection retry, which re-sends a command HA explicitly refused. `subscribe_events` follows the same rule: its own timeout raises `ResponseTimeoutError` instead of a bare `FailedMessageError`. A connection lost while `subscribe_events` waits still raises the internal `WebsocketClosedError`, not `ResponseLostError`: its only caller is the connect sequence in `WebsocketService`, whose reconnect loop treats any `HassetteError` as expected churn, so the class stays internal as D3 says. REST retry eligibility is D8. Tests pin each class's retry/no-retry outcome on both methods. The `send_and_wait` and `Api.ws_send_and_wait` docstrings state that after retries the raised class describes the last attempt, so a not-sent after an earlier timeout doesn't prove the command never reached HA, and that writes pass `retry_on_timeout=False`.
**Pick B instead if** you want a mid-call disconnect to wait out a short reconnect before failing. **Pick C instead if** the issue's "keep current behavior" should hold literally, quirks included.
**Reversibility:** easy
**Ratified:** Chose retrying only `ResponseTimeoutError` (when `retry_on_timeout` allows) in `send_and_wait` and `subscribe_events`, never `CommandNotSentError`, `CommandRejectedError` or `ResponseLostError`, over also retrying not-sent or reproducing today's `code is None` rule, so retry follows delivery state, accepting that an HA error reply without a code is no longer retried (a deliberate change from the issue's "keep current behavior"). The last-attempt docstring sentence was added at the sketch-time challenge, chosen by the user.

### D6: How do REST failures map onto the delivery states?

**Situation:** `ApiResource.rest_request` turns a 404 into `EntityNotFoundError` and other statuses into `HttpRequestError`, and lets every other `aiohttp.ClientError` and `TimeoutError` escape raw. The issue requires a connect failure to be not-sent: `aiohttp.ClientConnectorError` (DNS, refused and TLS failures) and `aiohttp.ConnectionTimeoutError` (connect phase ran out of time; a `ServerTimeoutError` subclass, so it is matched before its parent). Everything else after the request went out (other `ServerTimeoutError`s and `TimeoutError`, `ServerDisconnectedError`, `ClientOSError`) is outcome-unknown in meaning, and #3677 records it as `connection_lost` either way. Which of these REST retries is D8's question.

**Deciding factor:** one delivery-state model across both transports, at the least new surface.

| | A: connect failure → not-sent; other aiohttp errors stay raw | B: A, plus post-send timeouts → `ResponseTimeoutError` and dropped connections → `ResponseLostError`; status errors stay `HttpRequestError`/`EntityNotFoundError` | C: B, plus `HttpRequestError` re-parented under the rejected class |
|---|---|---|---|
| `except OutcomeUnknownError` around a REST write (`set_state`) | Misses REST timeouts | Catches them | Catches them |
| `except aiohttp.ClientError` in apps | Still catches post-send, misses connect | Misses all connection and timeout failures (break) | Same as B |
| New classes | None | None: reuses the WebSocket classes (docstrings widen to cover REST; `close_code` is `None`) | None |
| "Rejected" across transports | Separate | Separate | One catch, but `code` (string) vs `status` (int) differ |
| Peers | NetDaemon keeps REST status and connection errors separate | Same | No peer unifies them |

Two sub-choices settled after the table, at the sketch-time challenge and comb:

| | 10 s `REST_CONNECT_TIMEOUT_SECONDS` constant | Reuse `websocket.connection_timeout_seconds` | No connect bound (total only) |
|---|---|---|---|
| Silently dropped connect | Not-sent, unless the total is ≤ 10 s | Not-sent, unless the total is ≤ the WebSocket setting | Outcome-unknown |
| New surface or coupling | One private constant | REST timing tied to a WebSocket setting | None |

| | Closed-session check raises `CommandNotSentError` | Keeps `ResourceNotReadyError` |
|---|---|---|
| Transport symmetry | Same class as WebSocket's readiness check | Asymmetric; #3677 needs a special case |
| Silent break | Apps catching `ResourceNotReadyError` around REST calls (footer) | None |

**Recommendation:** B, because the issue's point is that a caller can tell what happened from the class, and half-converting REST leaves `except OutcomeUnknownError` silently blind to REST. Status errors stay separate, as peers keep them. The full rule, matched in this order: `ClientConnectorError` and `ConnectionTimeoutError` → `CommandNotSentError`; any other `ServerTimeoutError` or `TimeoutError` → `ResponseTimeoutError`; any other `ClientConnectionError` (`ServerDisconnectedError`, `ClientConnectionResetError`, a non-connect `ClientOSError`) → `ResponseLostError`; every other `ClientError` (`InvalidURL`, redirect and payload errors) stays raw, as a caller bug or a response HA already sent. A caller-supplied `timeout=` without a connect bound can let a connect-phase total timeout surface as `ResponseTimeoutError` although nothing was sent; that stays as is, since the caller chose the timeout. `rest_request`'s default per-request `ClientTimeout` gains a connect bound: `sock_connect=REST_CONNECT_TIMEOUT_SECONDS` (10 s, a module-level constant in `api_resource.py`, not a config field). It fires before the 30 s default total; a user who sets `rest_request_timeout_seconds` to 10 s or less lets the total fire first, so a hung connect then reads as `ResponseTimeoutError`, the safe direction, stated in the config field's docstring, because today's `ClientTimeout(total=...)` replaces aiohttp's default and leaves the connect phase unbounded: a host that silently drops packets would otherwise end in a plain total-timeout `TimeoutError` and never reach `ConnectionTimeoutError` (sketch-time challenge, `review-log.jsonl`). A caller-supplied `timeout=` is used as given. The closed-session check at the top of each attempt, which raises `ResourceNotReadyError` before any I/O today, raises `CommandNotSentError` instead, so a REST call made while the session is down reads the same as a WebSocket call made while disconnected; `StateProxy`'s own `ResourceNotReadyError` is a different raise site and is unchanged.
**Pick A instead if** you want REST changed only where the issue's acceptance criteria require. **Pick C instead if** one "HA rejected it" catch across transports is worth mismatched attributes.
**Reversibility:** easy
**Ratified:** Chose mapping REST connect failures (`ClientConnectorError`, `ConnectionTimeoutError`) to `CommandNotSentError`, post-send timeouts to `ResponseTimeoutError` and dropped connections to `ResponseLostError`, with status errors staying `HttpRequestError`/`EntityNotFoundError`, over converting only the connect failure or also unifying status errors under the rejected class, so one delivery-state model covers both transports with no new classes, accepting that apps catching `aiohttp.ClientError`, builtin `OSError` or builtin `TimeoutError` around REST calls silently stop matching and must switch to hassette's classes; the `BREAKING CHANGE:` footer names all three, and the rewritten `catch_ha_unreachable.py` snippet shows the replacement catch (the builtin catches were added to this accepted cost at the sketch-time challenge, `review-log.jsonl`). Adding the REST connect bound was chosen at the sketch-time challenge, so a silently dropped connect is not-sent as this mapping states, accepting that a hung connect now fails at the constant instead of the 30 s total. Mapping the closed-session check to `CommandNotSentError` was also chosen at the sketch-time challenge, accepting that apps catching `ResourceNotReadyError` around REST calls stop matching (named in the footer). Also accepted at the sketch-time challenge as a known limitation: the mapping covers failures up to the response headers, so a failure while a caller reads the body (`response.json()`, after HA already answered with a status) still raises raw `aiohttp`/`TimeoutError`. Re-ratified after the sketch comb with the full ordered mapping, accepting that a caller-supplied `timeout=` without a connect bound can report a connect-phase timeout as `ResponseTimeoutError`. The bound's value (a 10 s constant over reusing `websocket.connection_timeout_seconds`) was chosen at the sketch comb, accepting that a configured total of 10 s or less makes a hung connect read as outcome-unknown.

### D7: What do the not-sent and outcome-unknown classes carry?

**Situation:** `ResponseTimeoutError` inherits `code` (always `None`) and `original_data` (the outgoing payload) from `FailedMessageError`; `ResponseLostError` inherits `close_code` from `RetryableConnectionClosedError`. Re-parenting under `OutcomeUnknownError` alone drops those unless they move. The not-sent class is new. Messages already name only the command type and id, since payloads can hold secrets (`command_label`).

**Deciding factor:** keep debugging information that exists today, add none nobody reads.

**Recommendation:** `ResponseTimeoutError` keeps `original_data` (set to the WebSocket payload, `None` on REST) and drops `code`; `ResponseLostError` keeps `close_code` (`None` on REST); the not-sent class carries only its message (command label, or REST method and URL) and the chained cause. #3677 builds its row from the caller's own arguments, so it needs nothing more. Each raise site's message names its own deadline: REST timeouts cite the configured `rest_request_timeout_seconds`, not `RESPONSE_TIMEOUT_SECONDS`.
**Pick instead** "add `original_data` to the not-sent class too" if you want the payload inspectable on every transport failure.
**Reversibility:** easy
**Ratified:** Chose keeping `original_data` on `ResponseTimeoutError` (dropping `code`), `close_code` on `ResponseLostError`, and only a message plus chained cause on `CommandNotSentError`, with each raise site's message naming its own transport's deadline, over adding `original_data` to the not-sent class, so today's debugging information survives the re-parenting without new attributes, accepting that a not-sent payload is inspectable only from the caller's own arguments (re-ratified after the sketch-time challenge).

### D8: Which REST failures does `rest_request` retry?

**Situation:** `rest_request` wraps every call in a tenacity loop (`MAX_RETRY_ATTEMPTS = 5`, `reraise=True`) that retries anything outside `NOT_RETRYABLE` plus 5xx/408/429 statuses (`is_retryable_rest_failure`), whatever the method. Under D6's classes that loop re-sends a write after an outcome-unknown attempt (contradicting D5's rule), re-sends a write HA already processed and answered with a 5xx, and reports only the last attempt's class: a `set_state` whose first attempt timed out after sending, followed by refused connects while HA restarts, ends as `CommandNotSentError`, which #3677 records as a certain `not_sent`. A re-sent `delete_entity` that already applied gets a 404 and is recorded as `rejected`. Non-GET REST calls today: `set_state` (POST), `delete_entity` (DELETE), `render_template` (POST, a read), plus the public `rest_request`/`post_rest_request`/`delete_rest_request`. Raised at the sketch-time challenge (`review-log.jsonl`, findings 1–3).

**Deciding factor:** retry follows delivery state on both transports (writes never re-sent after an unknown outcome or a rejection), with no new parameters or cross-attempt state.

| | A: GETs retry as today; other methods retry only not-sent | B: as A, but non-GETs also keep retrying 5xx/408/429 | C: keep the loop; track the furthest state across attempts and raise that | D: keep the loop; document both symptoms |
|---|---|---|---|---|
| Write never re-sent after it may have applied | Yes | No: a 5xx re-sends a processed write | No: up to 5 sends | No |
| #3677 `not_sent` exact | Yes: every retried attempt was not-sent | No | Yes | No |
| Same rule as WebSocket (writes never retry unknown or rejected) | Yes; REST also retries not-sent, which WebSocket doesn't (D5), because REST has no `Api`-level fast-fail and a refused connect during an HA restart can succeed on a later attempt | Partly | No | No |
| New machinery | None: the predicate also takes the method | None | State carried across tenacity attempts | None |
| Behavior change | A write slower than `rest_request_timeout_seconds`, dropped after sending, or answered 5xx/408/429 fails at once; `render_template` timeouts are no longer retried | Smaller | None | None |
| What peers do | gRPC A6: never-sent always retried, unknown not by default; Stripe: no unknown-outcome retry without an idempotency key | Mixed | No peer found | botocore retries everything transient |

**Recommendation:** A, because it is D5's rule applied by HTTP method, adds no state, and makes REST `not_sent` exact. A GET keeps today's retries (connect failures, outcome-unknown, 5xx/408/429). Any other method retries only `CommandNotSentError`, so the class a write raises after retries describes the whole call.
**Pick B instead if** HA returns transient 5xx on writes that retries rescue. **Pick C instead if** REST writes must keep retrying through slow responses. **Pick D instead if** this PR should leave REST behavior alone.
**Reversibility:** easy
**Ratified:** Chose retrying GETs as today and retrying non-GET requests only on `CommandNotSentError`, over keeping status retries for writes, tracking the furthest state across attempts, or documenting the old loop, so REST follows the same delivery-state rule as WebSocket and a write's final class describes the whole call, accepting that a slow, dropped or 5xx/408/429-answered write (and a timed-out `render_template`) now fails on the first such attempt.

## Assumed

- `ClientConnectionResetError` subclasses both `ClientConnectionError` and the builtin `ConnectionResetError`, so D4's single `except ConnectionError` catches it along with the drain wait's plain `ConnectionError`. Evidence: `aiohttp/client_exceptions.py` (`class ClientConnectionResetError(ClientConnectionError, ConnectionResetError)`).
- Hassette is pre-V1 and takes clean breaks. Evidence: issue #3957 ("a clean pre-V1 break"); project memory "Pre-V1: no compat shims".
- `Api.ws_send_and_wait`/`ws_send_json` check `is_connected` (external readiness) before sending, so a closed connection fails fast at the `Api` layer before reaching `send_and_wait`'s retry loop. Evidence: `src/hassette/api/api.py` `ws_send_and_wait`, `ws_send_json`.
- An HA error reply resolves the future through `PendingResponses.respond_if_necessary` with `FailedMessageError.from_error_response`; that is the only producer of HA-reply errors. Evidence: `src/hassette/core/websocket_responses.py` (`respond_if_necessary`).
- `_ws_helper_call` rewraps rejections with field names only and must keep re-raising outcome-unknown errors unwrapped; once outcome-unknown classes no longer inherit from the rejected class, the guarding `except OutcomeUnknownError: raise` is no longer needed. Evidence: `src/hassette/api/api.py` `_ws_helper_call`.
- `RecordingApi` raises the rejected class with `code="not_found"` for unseeded helpers; it follows D2's name. Evidence: `src/hassette/testing/recording_api.py` (helper `update`/`delete`).
- On hassette's uncompressed WebSocket, `send_json` sees `ClientConnectionResetError` in practice only from the closing-transport checks before the write (`_drain_helper` also raises it when `transport is None`, which the pre-write `is_closing()` check makes unreachable right after a write), and a plain `ConnectionError` from the drain wait after it; asyncio routes socket/TLS write errors to `connection_lost` instead of raising them. A future change that enables WebSocket compression must recheck this, since the compressed path writes from a shielded background task. Evidence: `aiohttp/_websocket/writer.py` (`send_frame`, `_write_websocket_frame`), `aiohttp/base_protocol.py` (`connection_lost`, `_drain_helper`'s `transport is None` branch), `aiohttp/client.py` (`ws_connect` `compress=0`), `src/hassette/core/websocket_service.py` (`ws_connect` call), stdlib `asyncio/selector_events.py` (`_SelectorSocketTransport.write`) (aiohttp 3.14.5 in the lockfile).
- `ClientConnectorError` subclasses cover TLS and certificate failures at connect (`ClientConnectorSSLError`, `ClientConnectorCertificateError`), so mapping the base covers them; `ClientConnectorError` is itself a `ClientOSError`, and `ConnectionTimeoutError` is a `ServerTimeoutError`, raised only when `connector.connect` exceeds a configured connect bound (`ClientTimeout.connect`/`sock_connect`); a total-timeout expiry during connect raises a plain `TimeoutError` instead. Both must be matched before their parents. Evidence: `aiohttp/client_exceptions.py`, `aiohttp/client.py` (`_connect_and_send_request`, `DEFAULT_TIMEOUT`), `aiohttp/connector.py` (`ceil_timeout(timeout.connect, ...)`); `src/hassette/core/api_resource.py` (`ClientTimeout(total=...)` per request).
- REST never raises `ConnectionClosedError`; its `NOT_RETRYABLE` entry is vestigial. Evidence: `src/hassette/core/api_resource.py` (no raise site).
- #3677 needs: one not-sent class on both transports, the rejected class only for HA error replies, outcome-unknown classes no longer subclassing the rejected class. Evidence: `design/specs/149-api-write-records/design.md` D4 (branch `3677`).

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**
- REST mapping lives in a module-level `delivery_state_error(exc, method, url, deadline)` in `api_resource.py`, called from `rest_request`'s single `except (aiohttp.ClientError, TimeoutError)`: one place for D6's ordered rule, unit-testable without a server.
- `rest_request` now logs a raw `TimeoutError` the same way it logged `ClientError`s (respecting `suppress_error_message`): the mapped classes share one handler, and a timeout is a failure the caller sees.
- The WebSocket retry predicate is `is_retryable_ws_failure` at the bottom of `websocket_io.py` (D5's "one module-level predicate"), placed below the class like `is_retryable_rest_failure`.
- `subscribe_events`'s `ResponseTimeoutError` carries the subscribe payload as `original_data`, matching `send_and_wait`'s (D7).
- A REST timeout message names "the caller's timeout" when the caller passed `timeout=`, otherwise the configured `rest_request_timeout_seconds` value (D7).
- `sock_connect` bounds each socket connect attempt but not DNS resolution, so a hung DNS lookup still ends at the total timeout and reads as `ResponseTimeoutError`; that is the safe direction D6 already accepts for a short total, so no extra bound was added.
- `CommandNotSentError`'s docstring carries the "unreachable" two-class catch in prose rather than a code example, to keep `exceptions.py` within the 800-line file-size gate.
- PR footer (ship-time challenge finding 4): the single `BREAKING CHANGE:` footer is written at PR creation from the Posture list, plus two items the list doesn't name: `ResponseTimeoutError.code` is gone (`e.code` now raises `AttributeError` at runtime), and a non-GET REST request on a keep-alive connection the server just closed is no longer retried by Hassette (D8).
