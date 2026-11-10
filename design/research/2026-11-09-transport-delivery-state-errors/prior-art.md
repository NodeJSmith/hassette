---
topic: "Classifying transport failures by delivery state (not sent / rejected / outcome unknown)"
date: 2026-11-09
status: Draft
---

# Prior Art: Transport exceptions by delivery state

## The Problem

A client that sends commands to a remote system has three answers to "did my command run?": it never left (safe to retry), the server answered with an error (it ran, or was refused, and the reply says which), or nobody knows (timed out, or the connection dropped after sending). Retry safety and audit records both depend on telling these apart. Most exception hierarchies are organized by mechanism instead (connect error, socket error, timeout, HTTP status), so callers have to reconstruct the delivery state from mechanism classes.

## How We Do It Today

Hassette's classes mix the states (`src/hassette/exceptions.py`). `FailedMessageError` covers HA error replies (with or without `code`), a failed socket write (`send_json` wraps non-reset exceptions), and, through `ResponseTimeoutError`, a timeout. `ConnectionClosedError` covers the closed send gate and, through `RetryableConnectionClosedError` → `ResponseLostError`, a drop after sending. `ClientConnectionResetError` escapes `send_json` raw. REST raises `HttpRequestError`/`EntityNotFoundError` for statuses and raw `aiohttp.ClientError`/`TimeoutError` otherwise, with no connect-vs-after-send split. WebSocket retries key on `FailedMessageError` with `code is None`, which merges write failures, timeouts, and codeless HA rejections. `OutcomeUnknownError` (#2468) is the one class named for a delivery state.

## Sources Found

### hass-client (music-assistant/python-hass-client)
- **URL**: https://github.com/music-assistant/python-hass-client (hass_client/exceptions.py, client.py)
- **Type**: reference implementation (HA WS client)
- **Opened**: yes (cloned, read exceptions.py and client.py send/receive paths)
- **Key takeaway**: Has `TransportError` base with `CannotConnect` (never connected) and `ConnectionFailed` (established connection died). `NotConnected` (send gate, raised before sending) sits OUTSIDE TransportError under BaseHassClientError. `FailedCommand` (HA error reply) is a sibling, no shared base with transport errors. No timeout or outcome-unknown class; no retry logic.
- **Relevance**: closest HA peer; splits transport vs rejected, but not "sent vs not sent".

### home-assistant-js-websocket
- **URL**: https://github.com/home-assistant/home-assistant-js-websocket (lib/errors.ts, lib/connection.ts)
- **Type**: reference implementation (official HA client)
- **Opened**: yes
- **Key takeaway**: Numeric constants `ERR_CANNOT_CONNECT=1, ERR_INVALID_AUTH=2, ERR_CONNECTION_LOST=3`. `sendMessage` throws `ERR_CONNECTION_LOST` when not connected (never sent); the same code is also used to reject in-flight commands on close, so "not sent" and "lost after send" are one code. HA error replies are separate result objects with `error.code`. `isConnectionLost()` helper is used to decide whether subscription resubscribe errors are fatal. Reconnect retries forever except `ERR_INVALID_AUTH`.
- **Relevance**: HA's own client conflates not-sent and outcome-unknown; no timeout class.

### AppDaemon hass plugin
- **URL**: https://github.com/AppDaemon/appdaemon (appdaemon/plugins/hass/exceptions.py, hassplugin.py ~L400-510, L574)
- **Type**: reference implementation
- **Opened**: yes
- **Key takeaway**: Flat exceptions (`HAConnectionFailure`, `HassConnectionError`, `HAEventsSubError(code,msg)`), all directly under `AppDaemonException`. REST path catches `ClientResponseError` and *returns* it, logs timeouts and `ServerDisconnectedError` and returns None. Sends re-raise `ConnectionResetError` unless stopping. No delivery-state taxonomy; per-call retry does not exist (only connection-level reconnect with `retry_secs`).
- **Relevance**: "they don't bother" finding.

### NetDaemon HassClient
- **URL**: https://github.com/net-daemon/netdaemon (src/Client/NetDaemon.HassClient/Common/Exceptions/)
- **Type**: reference implementation
- **Opened**: yes (exception files only)
- **Key takeaway**: Two exceptions: `HomeAssistantApiCallException` (carries HttpStatusCode) and `HomeAssistantConnectionException` (carries `DisconnectReason`). No not-sent/unknown split. Retry code not read.
- **Relevance**: confirms HA peers have a rejected-vs-connection split at most.

### aiohttp client_exceptions
- **URL**: https://github.com/aio-libs/aiohttp/blob/master/aiohttp/client_exceptions.py
- **Type**: reference implementation
- **Opened**: yes (class list)
- **Key takeaway**: `ClientError` -> `ClientResponseError` (server replied with a status; `raise_for_status`) vs `ClientConnectionError` -> {`ClientConnectorError` (connect failed, never sent: also DNS/SSL/proxy subclasses), `ServerDisconnectedError`, `ServerTimeoutError` (`ConnectionTimeoutError`, `SocketTimeoutError`), `ClientConnectionResetError`}. So never-sent (connector) and may-have-sent (disconnected/timeout/reset) share `ClientConnectionError` but the connect-phase class is distinct. Rejected is a separate branch.
- **Relevance**: the structure hassette would be mirroring when it does REST.

### botocore exceptions + retries/standard.py
- **URL**: https://github.com/boto/botocore (botocore/exceptions.py L110-156; botocore/retries/standard.py L492-535, L635-665)
- **Type**: reference implementation
- **Opened**: yes
- **Key takeaway**: `ConnectionError` (EndpointConnectionError, ConnectTimeoutError, SSLError, ProxyConnectionError: never reached server) is separate from `HTTPClientError` (ConnectionClosedError "closed before we received a valid response", ReadTimeoutError: possibly sent). Standard retry policy's `TransientRetryableChecker` retries BOTH families, plus status 500/502/503/504 and codes RequestTimeout etc. It does not retry by idempotency; unknown-outcome is retried by default. Default max attempts 3. 4xx (except throttling/modeled retryable codes) are not retried.
- **Relevance**: class split exists but retry policy treats not-sent and unknown identically.

### gRFC A6 client retries
- **URL**: https://github.com/grpc/proposal/blob/master/A6-client-retries.md ; https://grpc.io/docs/guides/retry/
- **Type**: standard
- **Opened**: yes (via exa-search contents of the page)
- **Key takeaway**: Four failure stages; failures that never left the client are transparently retried (unlimited until deadline); reached the server library but not application logic (REFUSED_STREAM / GOAWAY with lower last-stream-id) retried once; after the app logic saw it, only the configured retry policy (status-code allowlist, default none) applies. Transparent retries don't count toward maxAttempts or throttling. Once response headers arrive the RPC is "committed" (no more retries).
- **Relevance**: the canonical "delivery state drives retry" design; the only peer where retry eligibility is a hard function of delivery state, independent of user policy.

### gRPC status codes
- **URL**: https://grpc.io/docs/guides/status-codes/
- **Type**: documentation
- **Opened**: no (search hit only, not read)
- **Key takeaway**: UNAVAILABLE (transient, usually safe to retry w/ backoff) vs DEADLINE_EXCEEDED (outcome unknown, server may have done the work) are separate codes; secondary basis only.
- **Relevance**: naming precedent for "outcome unknown" as a distinct class.

### Stripe low-level error handling
- **URL**: https://docs.stripe.com/error-low-level
- **Type**: documentation
- **Opened**: yes (excerpt via exa-search)
- **Key takeaway**: Network errors = outcome unknown; retry only with the same idempotency key within 24h, else reconcile. 500 treated as indeterminate too. `Stripe-Should-Retry` header lets server override. Rejections (4xx before execution) are retriable after fixing; do not generate a new key blindly.
- **Relevance**: unknown-outcome writes retry only when idempotent; otherwise reconcile.

### Kafka producer configs
- **URL**: https://kafka.apache.org/44/configuration/producer-configs/
- **Type**: documentation
- **Opened**: no (found, not read)
- **Key takeaway**: [secondary, not verified by reading] delivery.timeout.ms / retries with enable.idempotence is the Kafka answer to unknown-outcome retries (server dedup). Not relevant to hassette since HA WS has no dedup.

## Patterns Found

### Pattern 1: Three-way split by delivery state with a retry rule bound to the state (gRPC)
**Used by**: gRPC (A6).
**How it works**: Classify by how far the request got: never left client -> always retry; reached server transport but not app -> retry once; seen by app -> retry only by explicit policy (status codes). Unknown-outcome (DEADLINE_EXCEEDED) is not retryable by default.
**Strengths**: Safety is structural, not per-call-site; user can't accidentally retry a possibly-executed write.
**Weaknesses**: Needs transport-level knowledge of exactly how far the request got.
**Example**: https://github.com/grpc/proposal/blob/master/A6-client-retries.md
**Read**: gRFC A6 text (via exa contents) and grpc-java issue #10533 maintainer comments on MISCARRIED vs REFUSED.

### Pattern 2: Connect-phase vs post-send transport errors under one connection base, rejected as a separate branch (aiohttp, botocore, hass-client)
**Used by**: aiohttp, botocore, hass-client (`TransportError` -> `CannotConnect`/`ConnectionFailed`; `FailedCommand` separate).
**How it works**: Exceptions are hierarchies by *phase* (connect vs mid-flight) and by *rejected* (response received). "Server rejected" never shares an ancestor with transport failures except the library root. The not-sent vs sent split is approximated by connect-phase vs established-connection.
**Strengths**: `except ClientConnectionError` vs `except ClientResponseError` is easy to write; mirrors reality.
**Weaknesses**: No library models "write failed on the socket" or "send gate closed" as never-sent, and a post-connect write failure lands in the same bucket as a lost response.
**Example**: https://github.com/aio-libs/aiohttp/blob/master/aiohttp/client_exceptions.py ; https://github.com/boto/botocore/blob/develop/botocore/exceptions.py
**Read**: client_exceptions.py class list; botocore exceptions.py and retries/standard.py.

### Pattern 3: Retry everything transient, ignore delivery state (botocore standard mode)
**Used by**: botocore (ConnectionError + HTTPClientError + 5xx), AppDaemon (reconnect only).
**How it works**: One transient allowlist covers never-sent and unknown-outcome. Safety relies on AWS APIs being mostly idempotent.
**Strengths**: Simple.
**Weaknesses**: Wrong for non-idempotent writes like HA `call_service` (turn_on is idempotent; `lock.unlock`/`script.run`/`counter.increment` are not).
**Read**: botocore/retries/standard.py L492-535.

### Pattern 4: Unknown-outcome retried only with idempotency token or reconciliation (Stripe)
**Used by**: Stripe, Kafka idempotent producer (secondary).
**How it works**: Network errors/500s are "indeterminate"; retry only with same key; otherwise read back state.
**Strengths**: Honest about unknown. **Weaknesses**: needs server dedup; HA WS has none, so equivalent is "don't retry, or read state first".
**Read**: Stripe docs excerpt; Kafka secondary.

### Pattern 5: Single code for not-sent and lost-after-send (js-websocket)
**Used by**: home-assistant-js-websocket (`ERR_CONNECTION_LOST`).
**How it works**: send() when disconnected throws the same code used to reject pending commands on close; reconnect handles recovery, not callers.
**Weaknesses**: callers cannot tell if a write ran. Accepted limitation; no issue found about it [no source found for a won't-fix issue].
**Read**: lib/errors.ts, lib/connection.ts L275-335.

## Anti-Patterns
- Returning/logging errors instead of raising (AppDaemon REST swallows timeout, disconnect; returns `ClientResponseError` as a value).
- Keying retry on "no error code" (hassette today): absence of a code is not a delivery-state signal; it merges write-failed, timeout, and malformed HA replies.
- Using a connection-lost code for both never-sent and in-flight (js-websocket) loses the information that decides retry safety.

## Gaps
- NetDaemon retry/reconnect code not read (only exception classes); Kafka and gRPC status-codes pages not opened (hits only).
- No GitHub issue found where an HA client deliberately closed a not-sent/unknown distinction as won't-fix; I did not search issue trackers exhaustively. Tried: reading the exception modules only.
- No library read that shares a "rejected" base across REST status and WS error replies. NetDaemon's two exceptions are separate (REST: HomeAssistantApiCallException; connection: HomeAssistantConnectionException); hass-client has only the WS FailedCommand.

## Relevance to Us

- **No HA peer distinguishes not-sent from outcome-unknown.** hass-client, home-assistant-js-websocket, AppDaemon and NetDaemon either merge them (js-websocket's `ERR_CONNECTION_LOST`) or split by phase only. Hassette's #3677 write records need the distinction, so this goes further than peers, on purpose; the justification is the audit record and retry safety, not peer practice.
- **Rejected never shares a base with transport failures** below the library root (aiohttp `ClientResponseError` vs `ClientConnectionError`, hass-client `FailedCommand` vs `TransportError`). That supports keeping `FailedMessageError` (rejected) out of any transport base.
- **No peer unifies REST status errors and WebSocket error replies** under one "rejected" class. NetDaemon keeps them separate.
- **No peer treats a failed write on an established socket as certainly never sent.** aiohttp itself can raise `ClientConnectionResetError` from its drain step after the frame was handed to the transport (`aiohttp/_websocket/writer.py` `send_frame` → `protocol._drain_helper()`), so "write failed ⇒ not sent" holds for the pre-write closing check but is not airtight for the drain case.
- **Keying retry on "no code" is an anti-pattern** the brief found nowhere else; no peer retries a server error reply without a code. gRPC A6 is the only design that derives retry eligibility from delivery state: never-sent always retryable, unknown-outcome not by default.

## Recommendation

Split by delivery state as #3957 proposes (gRPC A6 is the model), keep "rejected" as its own branch with no shared transport base (aiohttp/hass-client), and derive retry eligibility from the class rather than from `code is None`. Keep REST status errors as their own class rather than merging them into `FailedMessageError`, matching NetDaemon. Document the drain-time edge case for socket-write failures rather than building machinery to detect it: no peer detects it at all.
