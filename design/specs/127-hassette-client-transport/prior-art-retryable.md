---
topic: "How client libraries tell callers whether to retry a failure, and what hassette-client's `retryable` should promise"
date: 2026-10-07
status: Draft
---

# Prior Art: Retry Signaling in HTTP/RPC Clients, Applied to hassette-client

## Bottom line

Keep the `retryable` attribute and the class set, but redefine it in operational terms as "sending this exact request again is safe and might succeed". Compute it per instance at the raise site. The class value is the default, and the transport can only lower it to `False`, never raise it. This is the stripe-python `APIConnectionError.should_retry` shape, using the same inputs urllib3 and azure-core use: whether the request was sent, whether the endpoint is idempotent, and whether the failure is permanent.

There are two reasons:

1. **Today's flag combines two separate questions.** "Will this go away?" and "Is resending harmless?" have different answers. Go deprecated `net.Error.Temporary()` for this reason. `while exc.retryable` loops forever on a TLS certificate failure and repeats a timed-out `reload`.
2. **The HA integration never reads the flag.** It maps errors by class and fails fast. HA's own machinery handles retries: setup retry and the next poll. The only reader is a generic loop in a script, like the docs snippet. A flag that is only read by a loop with no other context has to be safe on its own.

Rejected:

- A built-in retry policy. It contradicts "the client never retries", and HA already retries at the right layer.
- A bare `request_sent` field. It's correct, but it makes every caller know the idempotency of each endpoint.
- A predicate function. A correctly computed flag already works as one: `retry_if_exception(lambda e: e.retryable)`.
- Server signals (`Retry-After`, idempotency keys). Defer them until the server sends one.

## The Problem

A client error has to answer two questions that are separate:

- **Transient vs. permanent.** Would the same request succeed later? A refused connection, a 503, or a bootstrap 409 might. A TLS verification failure or an invalid URL won't.
- **Safe vs. unsafe to resend.** Could resending duplicate a side effect? A failure before the request was sent is always safe to resend. A failure after it was sent is safe only if the endpoint is idempotent.

hassette-client has non-idempotent POSTs: `action(..., "reload")` and `trigger_job`. Actions are held open until the operation finishes, with a 10 s default total timeout, so a slow reload produces a timeout as a normal outcome, not only on network failure. That makes the second question a real concern here.

## How We Do It Today

From `client/src/hassette_client/errors.py` and `transport.py`:

- **The flag.** `retryable: ClassVar[bool]` is `True` on `HassetteConnectionError`, `HassetteTimeoutError`, `BootstrapNotReleasedError` (409), `GatewayError` (502/504) and `ServiceUnavailableError` (503). The module docstring defines it as "the same request may succeed if sent again later unchanged". That is the transient question only.
- **Exception mapping.** `except TimeoutError` comes before `except aiohttp.ClientError`. Every timeout becomes `HassetteTimeoutError`, including aiohttp's `ConnectionTimeoutError`, which is a connect phase failure where the request wasn't sent. Every other `ClientError` becomes `HassetteConnectionError`, including `ClientConnectorCertificateError`, `ClientConnectorSSLError`, `ServerFingerprintMismatch`, `InvalidURL`/`InvalidUrlClientError` and `NonHttpUrlClientError`. All of these get `retryable=True`.
- **The docs snippet** (`docs/pages/web-ui/snippets/python_client_errors.py`) loops `if not exc.retryable: raise`. It uses `start`, so it happens to be safe. The prose admits that resending a `reload` restarts the app again, but the flag gives no warning of that.
- **aiohttp's built-in retry** (verified in aiohttp 3.14.3 `client.py:256, 703, 859-870`). aiohttp retries once on a stale pooled connection (`ServerDisconnectedError`/`ClientOSError`), but only for `IDEMPOTENT_METHODS = {GET, HEAD, OPTIONS, TRACE, PUT, DELETE}`. It never retries `ClientConnectorError` or `ConnectionTimeoutError`. A POST that hits a stale keep-alive connection therefore reaches our code as `HassetteConnectionError`, and we don't know whether the server processed it.
- **The HA consumer** (spec 113 brief, lines 62-68 and 145-168) maps by class:
  - connection error or timeout: `ConfigEntryNotReady` at setup, `UpdateFailed` in a poll
  - 401: `ConfigEntryAuthFailed`
  - 404 or 409 blocked: `ServiceValidationError`
  - 409 bootstrap, 500 or timeout: `HomeAssistantError`

  Actions are a single attempt. It never reads `retryable`.
- **Prior decision.** `design/research/2026-10-02-hassette-client-transport/research.md` Q1 chose option (c): a per-class attribute and no wire change. That brief compared where the classification lives. It didn't ask what the flag promises.

## Patterns Found

### Pattern 1: Exception-type taxonomy plus a predicate (no flag)

**Used by**: google-api-core (`if_exception_type`, `if_transient_error`), tenacity, botocore (`_TRANSIENT_EXCEPTION_CLS`), httpx (hard-wired), and every HA client library surveyed.

**How it works**: The library raises typed exceptions. A separate predicate or policy decides which types to retry, and exceptions carry no retry state. google-api-core's default `Retry(predicate=if_transient_error)` covers `InternalServerError`, `TooManyRequests`, `ServiceUnavailable` and `requests` connection errors. HA libraries all work this way, with no retry flag on any of them:

- aiohue
- aioesphomeapi
- aioshelly
- python-roborock
- aiounifi
- pyoverkiz
- pyatv
- zwave-js-server-python
- aiohomekit
- aiogithubapi

Their integrations pick the HA exception by class.

**Strengths**: The raise site makes no per-raise judgment, and the caller can swap policies.

**Weaknesses**: The result depends on the class hierarchy being shaped around retry semantics. botocore's `SSLError` inherits from `ConnectionError` and so is retried as transient. google's `if_transient_error` includes `requests.ConnectionError`, the parent of `SSLError`.

**Example**: google-api-core 2.41.0 `retry_base.py`, and https://raw.githubusercontent.com/boto/botocore/develop/botocore/retries/standard.py

### Pattern 2: A per-exception flag set where the failure is classified

**Used by**: stripe-python (`APIConnectionError.should_retry`), smithy-python (`CallError.is_retry_safe: bool | None`, plus `is_throttling_error`, `is_timeout_error`, `retry_after`, `fault`), Temporal (`ApplicationError.non_retryable`).

**How it works**: The code that sees the low-level failure sets the flag once, and the loop only reads it.

- **stripe-python** sets `should_retry=False` for `SSLError`, checked first with the comment "it belongs to ConnectionError, but we don't want to retry". It sets `True` for Timeout and ConnectionError, and `False` for anything unknown, so it fails closed. HTTP-status errors carry no flag; `_should_retry` decides from the status and the `Stripe-Should-Retry` header.
- **smithy** documents its flag as "a retry is *allowed*", not "a retry will occur". `None` means "not enough information".

**Strengths**: The classification sits next to the knowledge, the caller's loop is trivial, and the flag plugs into tenacity directly.

**Weaknesses**: It needs an operational definition (see Anti-pattern 1). Stripe's flag ignores the HTTP method and is safe only because the SDK adds an `Idempotency-Key` to every POST. Wrapping an exception can drop the flag (Temporal docs).

**Example**: https://github.com/stripe/stripe-python/blob/master/stripe/_http_client.py, https://smithy.io/2.0/guides/client-guidance/retries.html

### Pattern 3: A policy object with a method allowlist and a connect/read split

**Used by**: urllib3 `Retry`, azure-core `RetryPolicy`.

**How it works**: The policy keeps separate counters for `connect` ("raised before the request is sent"), `read` ("after the request was sent... may have side-effects") and `status`. `allowed_methods` defaults to HEAD/GET/PUT/DELETE/OPTIONS/TRACE. A read error on a method outside that list is re-raised immediately. `Retry-After` is honored on 413/429/503. azure-core also retries POST when the response is 500/503/504, but not after an exception.

**Strengths**: It encodes RFC 9110 §9.2.2 directly and is safe by default.

**Weaknesses**: The HTTP method is a crude stand-in for idempotency. There are many settings, and a policy object implies the library does the retrying.

**Example**: https://raw.githubusercontent.com/urllib3/urllib3/main/src/urllib3/util/retry.py

### Pattern 4: Sent vs. not-sent in the exception hierarchy

**Used by**:

- azure-core: `ServiceRequestError` ("No request was sent.") vs. `ServiceResponseError` ("The request was sent... These errors can be retried for idempotent or safe operations")
- urllib3: `ConnectTimeoutError` vs. `ReadTimeoutError`
- httpx: `ConnectError` vs. `ReadError`
- Go: `nothingWrittenError`
- gRPC A6: transparent retries when the RPC "never leaves the client"

**How it works**: The transport knows whether bytes reached the wire. A not-sent failure can be retried for any method. A sent failure can be retried only for idempotent or keyed requests. httpx's built-in `retries=N` retries only `ConnectError`/`ConnectTimeout`.

**Strengths**: It is the one distinction that makes a retry provably safe, and it matches RFC 9110's "some means to detect that the original request was never applied".

**Weaknesses**: Not-sent doesn't mean transient. Connect-phase failures include DNS NXDOMAIN, certificate verification and invalid URLs; smithy models safety and fault on separate axes. Not-sent isn't always knowable either: Go trusts it only on a reused connection with a rewindable body.

**Example**: azure-core `exceptions.py` docstrings, https://github.com/grpc/proposal/blob/master/A6-client-retries.md

### Pattern 5: Server-provided signals and idempotency keys

**Used by**:

- Stripe: `Stripe-Should-Retry` (absent means unknown), plus an auto-generated `Idempotency-Key` on every POST
- gRPC: `grpc-retry-pushback-ms`
- HTTP: `Retry-After`
- Go net/http: an `Idempotency-Key` header makes a POST count as idempotent
- HA: `UpdateFailed(retry_after=...)`, fed from pytibber's `RateLimitExceededError.retry_after`

**How it works**: The server knows things the client can't, such as whether the mutation was applied. Its signal overrides the client's guesses.

**Strengths**: The server's answer is authoritative and can change without a client release. **In HA, the only retry signal that flows from a library to the integration is a delay (`retry_after`), never a boolean.**

**Weaknesses**: It needs server cooperation. The hassette server sends neither header today.

**Example**: https://docs.stripe.com/error-low-level, `~/source/core/homeassistant/helpers/update_coordinator.py:41-52, 272-274, 498-514`

## Anti-Patterns

1. **A flag that only says "transient" or "temporary".** Go deprecated `net.Error.Temporary()` with the note: "Temporary errors are not well-defined. Most 'temporary' errors are timeouts, and the few exceptions are surprising." (https://github.com/golang/go/issues/45729). hassette's current definition, "may succeed if sent again later", is this flag.
2. **Retrying a sent, non-idempotent request after a read-phase failure.** RFC 9110 §9.2.2 says a client "SHOULD NOT automatically retry a request with a non-idempotent method unless it has some means to know that the request semantics are actually idempotent... or that the original request was never applied". aiohttp-retry violates this by default, since its `methods` include POST/PATCH. hassette's `HassetteTimeoutError.retryable=True` on a `reload` does too.
3. **Letting inheritance make permanent failures transient.** botocore's `SSLError` is a `ConnectionError`. stripe-python explicitly carves out SSL. hassette catches every `aiohttp.ClientError` into one class marked `retryable=True`.
4. **Treating connect-phase failures as transient.** azure-core promises only "No request was sent", which means safe to resend, not that a resend will work.

## Comparison of the Candidate Shapes

| # | Shape | Prior art it matches | Fixes TLS/InvalidURL loop | Fixes timed-out `reload` resend | Caller burden | Fit for hassette |
|---|---|---|---|---|---|---|
| 1 | Class `retryable` = transient, plus per-instance `request_sent: bool \| None` | azure-core, urllib3, smithy (two separate axes) | No, unless permanent cases are also fixed | Only if the caller combines it with idempotency knowledge it may not have | High: callers must know each endpoint's idempotency | Correct but pushes knowledge onto callers. The docs loop gets harder to write. |
| 2 | Per-instance `retryable` computed by the transport (class value is the default and can only be lowered) | stripe-python `should_retry`, smithy `is_retry_safe`, urllib3's decision logic | Yes | Yes | None: `while exc.retryable` is safe as written | **Best fit.** One place, no wire change, keeps the approved class defaults. |
| 3 | Drop the flag, ship a predicate | google-api-core, tenacity, every HA library | Only if the predicate inspects `__cause__` | Not without the call's idempotency, which a post-hoc predicate doesn't have | Medium | Weaker than 2. The predicate can't see which endpoint was called. |
| 4 | Built-in opt-in retry policy | urllib3, azure-core, aiohttp-retry, aiohue (503/429 loop) | Yes | Yes (method allowlist) | Low | Contradicts "the client never retries". HA already retries via `ConfigEntryNotReady` and the next poll, and aiohttp already handles stale connections. A lot of new code for no current consumer. |
| 5 | Server signals (`Retry-After`, `Stripe-Should-Retry`, idempotency keys) | Stripe, gRPC pushback, HA `UpdateFailed(retry_after)` | No | Only with idempotency keys, which need server work | Low | Needs server changes. `Retry-After` is a good future addition alongside 2 (see below). |
| 6 | Keep as is, document precisely | none (this is Go `Temporary()`) | No | No, documentation only | High: callers must read the caveats | Leaves both footguns in place, with the snippet showing the unsafe loop. |

## What the HA Consumer Needs

The local HA core checkout shows the following:

- **No retry within a call.** `DataUpdateCoordinator` makes one `_async_update_data()` call per poll. On failure it waits for the next interval, or for `retry_after` once (`update_coordinator.py:272-274, 498-514`). It already treats raw `TimeoutError`/`aiohttp.ClientError` as "unavailable" (L443-496).
- **Setup retry is the backoff mechanism.** `ConfigEntryNotReady` retries at 5 s, 10 s, 20 s and so on up to a 600 s cap (`config_entries.py:141, 839-880`). `ConfigEntryError` is permanent, and the `test-before-setup` quality-scale rule asks for it on errors that can't be fixed.
- **Actions are one attempt.** shelly `button.py:208-232`, esphome `entity.py:412-434` and roborock `entity.py:53-70` each map the library error to a translated `HomeAssistantError` and stop there. Neither the quality-scale `action-exceptions` rule nor core retries service calls. The user or the automation decides.
- **No integration in core reads a library-provided retryable boolean.** A grep for `retryable|is_retryable|should_retry` found only a local variable in bsblan. Two libraries split retryable errors into their own classes, and HA uses those classes:
  - pyTibber has `RetryableHttpExceptionError` and `FatalHttpExceptionError` (`tibber/coordinator.py:149-152`). On a fatal error, the integration reloads the entry.
  - hass_nabucasa has `CloudApiNonRetryableError` (`cloud/backup.py:144`).

  The only delay that flows from a library to HA is pyTibber's `retry_after`.

So the integration needs the class taxonomy it already has. The flag would matter to it in one place: telling a permanent connection error from a transient one at setup. Even there, a cert or URL problem is better caught in the config flow (`cannot_connect`/`invalid_cert`). At runtime, `ConfigEntryNotReady` is acceptable for an expired cert, because renewing the cert fixes it without reconfiguring HA. **The flag's real audience is scripts and automations that wrap the client in a loop.**

## Recommendation (Shape 2)

**Contract.** Define `retryable` as: "`True` when sending this exact request again is safe, meaning it can't duplicate an effect, and might succeed. `False` when a retry can't help, or might repeat an action the server already carried out." Put this definition in the `errors.py` module docstring and in the docs. It replaces "may succeed if sent again later".

**Mechanics.** Keep the approved classes and their class-level defaults. Make `retryable` a plain class attribute instead of a `ClassVar`, so an instance can shadow it. The transport sets the instance value to `False` in these cases and never sets it to `True`:

| Failure | Request sent? | `retryable` |
|---|---|---|
| `ConnectionTimeoutError`, `ClientConnectorError` (refused, DNS) | No | `True` for any method |
| `ClientConnectorCertificateError`, `ClientConnectorSSLError`, `ServerFingerprintMismatch`, `InvalidURL` (including `InvalidUrlClientError`), `NonHttpUrlClientError` | No | **`False`**: permanent, needs a human |
| Read-phase `TimeoutError`/`SocketTimeoutError`, `ServerDisconnectedError`, `ClientOSError` after connect, `ClientPayloadError` | Maybe | `True` only if the endpoint is idempotent |
| 504 `GatewayError` | Maybe (the upstream may have run it) | `True` only if the endpoint is idempotent |
| 502 `GatewayError`, 503, 409 `bootstrap_not_released` | Answered without acting | `True` (class default). This is Inferred for 502, which can also come after the upstream received the request. Treat 502 like 504 if you want to be conservative. |

**Order of the checks.** Catch the permanent subtypes before the generic `ClientError` bucket, and `ConnectionTimeoutError` before the bare `TimeoutError` (the Stripe lesson). The exception classes stay the same: a cert failure is still a `HassetteConnectionError`, just with `retryable=False`.

**Idempotency is declared per endpoint, not inferred from the HTTP method.**

- Add an `idempotent: bool` argument to `Transport.request`. Default it from the method, per RFC 9110: GET/PUT `True`, POST `False`.
- `HassetteClient.action` passes `idempotent=(action != "reload")`. Start and stop converge on a target state, as spec 113 documents at `app_lifecycle_service.py:509-512, 663-665`.
- `trigger_job` and `create_session` keep the POST default of `False`.

That is one argument and one call-site override. A simpler variant derives idempotency from the HTTP method alone, as urllib3 does. It is conservative and needs no override, but a timed-out `start`/`stop` would read as not retryable even though the docs call those safe to resend.

**Non-idempotent POST timeouts.** `HassetteTimeoutError(retryable=False)` on `reload` and `trigger_job`. The message and docs should say "outcome unknown: check the app's status before resending". This matches what spec 113 already does in HA: `HomeAssistantError`, "outcome unknown", one attempt. The server probably keeps running the action after the client disconnects, since Starlette doesn't cancel a handler when the client goes away. That is Inferred and was not checked. If so, a resend would queue a second reload behind the app-key lock, which is the case this guards against.

**Permanent connection errors.** `retryable=False` on the same `HassetteConnectionError` class, with the underlying aiohttp error kept as `__cause__`. Optionally add a `permanent` hint to the message. Don't add a new class; the class set is approved.

**Not now:**

- A retry policy or loop inside the client.
- A `request_sent` field. The table above captures that information without making callers combine it.
- A predicate function. `retry_if_exception(lambda e: isinstance(e, HassetteClientError) and e.retryable)` is enough.
- Idempotency keys.

**Later, additive:** if the server ever sends `Retry-After` on 503 or the bootstrap 409, expose `retry_after: float | None` on `HassetteHTTPError`. That is the signal HA actually consumes (`UpdateFailed(retry_after=...)`), and smithy and urllib3 both carry it next to the flag.

**Tests to add:**

- cert error, `InvalidURL` and `ConnectionTimeoutError` each give the right `retryable` for both a GET and a POST
- a read timeout on `reload` gives `False`, on `start` gives `True`
- 504 on a POST gives `False`

The existing `test_retryable_flags` stays as the test of class defaults.

**Open questions:**

- Should 502 be treated like 504, since the upstream may have received the request? Prior art splits on this, and Azure retries POST on 502-class responses.
- Is a 10 s total timeout right for `action()`, given that the server holds the request until the operation finishes? A slow reload timing out is a timeout the caller could have avoided, separate from retry semantics. A per-call timeout override may be the better fix.

## Coverage Notes

- Library facts for the HA libraries come from GitHub raw sources, not installed packages.
- The exact signature of AWS Java v2 `SdkException.retryable()` and stripe-node were not checked.
- The aiohttp behavior was checked against the installed 3.14.3 source.

## Sources

### Reference implementations
- https://raw.githubusercontent.com/urllib3/urllib3/main/src/urllib3/util/retry.py: `allowed_methods`, connect/read split
- https://raw.githubusercontent.com/boto/botocore/develop/botocore/retries/standard.py: transient checker, no idempotency logic
- google-api-core 2.41.0 (https://pypi.org/project/google-api-core/2.41.0/): `if_transient_error`, `if_exception_type`
- https://github.com/stripe/stripe-python/blob/master/stripe/_http_client.py: `should_retry`, SSL carve-out
- https://raw.githubusercontent.com/Azure/azure-sdk-for-python/main/sdk/core/azure-core/azure/core/exceptions.py: `ServiceRequestError`/`ServiceResponseError`
- https://raw.githubusercontent.com/Azure/azure-sdk-for-python/main/sdk/core/azure-core/azure/core/pipeline/policies/_retry.py
- https://github.com/inyutin/aiohttp_retry: default `methods` include POST
- https://github.com/smithy-lang/smithy-python: `CallError.is_retry_safe`
- https://raw.githubusercontent.com/golang/go/master/src/net/http/transport.go: `shouldRetryRequest`, `Idempotency-Key`
- aiohttp 3.14.3 `client.py:256, 703, 806-818, 859-870`, `client_exceptions.py` (local `.venv`)
- HA libraries: aiohue, aioesphomeapi, aioshelly, python-roborock, aiounifi, pyoverkiz, pyatv, zwave-js-server-python, aiohomekit, aiogithubapi (raw `exceptions.py`/`errors.py` on GitHub)
- HA core (local `~/source/core`): `helpers/update_coordinator.py`, `config_entries.py:141, 839-880`, `exceptions.py:244-286`, `components/{shelly/button.py, esphome/entity.py, roborock/entity.py, tibber/coordinator.py, hue/bridge.py, overkiz/coordinator.py}`

### Documentation & standards
- https://www.rfc-editor.org/rfc/rfc9110.html#name-idempotent-methods: RFC 9110 §9.2.2
- https://github.com/grpc/proposal/blob/master/A6-client-retries.md: gRPC retries, transparent retry, pushback
- https://docs.stripe.com/error-low-level: idempotency keys, `Stripe-Should-Retry`
- https://www.python-httpx.org/advanced/transports/: connect-only retries
- https://smithy.io/2.0/guides/client-guidance/retries.html: `isRetrySafe` YES/NO/MAYBE
- https://github.com/golang/go/issues/45729 and https://pkg.go.dev/net#Error: `Temporary()` deprecation
- https://docs.temporal.io/design-patterns/non-retryable-errors
- https://elastic-transport-python.readthedocs.io/en/stable/transport.html: `retry_on_timeout=False` default
- https://tenacity.readthedocs.io/en/latest/
- https://developers.home-assistant.io/docs/integration_fetching_data/, https://developers.home-assistant.io/docs/config_entries_index/, https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/ (test-before-setup, action-exceptions)

Note: URLs were not live-verified at write time, except those the research subagents fetched.
