# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A TimeoutError raised by the WebSocket write would be reported as a response timeout

Status: open
Recorded: 2026-11-10 (3957)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/websocket_io.py

Issue:
`send_and_await_response` calls `send_json` and then waits for the response inside one call, and its callers (`send_and_wait`, `subscribe_events`) turn any `TimeoutError` from that call into `ResponseTimeoutError` and retry it where timeouts are retried. D4 says write errors other than `ConnectionError` propagate unwrapped; a `TimeoutError` from the write itself would instead read as "no response" (outcome unknown) and be retried. aiohttp's uncompressed WebSocket write path raises no `TimeoutError` today.

Why deferred:
It never fires today, and if it did the result is outcome-unknown, the safe direction: a misleading message and a pointless retry on reads, never a double-applied write (writes pass `retry_on_timeout=False`). The fix is a restructure guarding a hypothetical aiohttp change.

Recommended follow-up:
Revisit if WebSocket compression is enabled or aiohttp's write path changes: convert only the response wait's timeout (raise `ResponseTimeoutError` inside `send_and_await_response`) and pin it with a test.

Acceptance criteria:
- A `TimeoutError` raised by `send_json` propagates unwrapped from `send_and_wait` and `subscribe_events`, pinned by a test.

## KI-002: A REST POST on a keep-alive connection the server just closed fails once as ResponseLostError

Status: open
Recorded: 2026-11-10 (3957)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/api_resource.py
- src/hassette/api/entity_data.py

Issue:
`delivery_state_error` maps any non-connector `ClientConnectionError` (`ServerDisconnectedError`, `ClientConnectionResetError`, a non-connect `ClientOSError`) to `ResponseLostError`, and D8 retries non-GET methods only on `CommandNotSentError`. On a reused keep-alive connection the server just closed, HA usually never read the request, but the POST is not retried by Hassette, and aiohttp doesn't re-send POST either. `render_template` (a read sent as POST) is the exposed call; `set_state` issues a GET first, which usually leaves a fresh connection.

Why deferred:
Rare with plain Home Assistant, loud, and in the safe direction with no data loss; the caller can retry. aiohttp makes the same choice for POST. A fix adds a second input (a read marker) to D8's deliberately method-only retry predicate.

Recommended follow-up:
If `render_template` (or another POST) is seen failing this way in practice, typically behind a proxy with short idle timeouts, mark it as a read so it follows GET retry rules.

Acceptance criteria:
- A `render_template` call whose first attempt hits a server-closed keep-alive connection succeeds on retry, pinned by a test.
