# Design: hassette-client transport, errors and typed methods (#2386)

**Date:** 2026-10-07
**Status:** built
**Mode:** sketch

## Summary

Issue #2386 builds `hassette_client`, the typed async client that every Python consumer of hassette's web
API uses: the HA companion integration (`hass-hassette`, spec 113), the CLI port (#2387), and user scripts.
It adds:

- an aiohttp transport over a session the caller owns;
- a typed exception hierarchy resolved from the problem `code`, then the status;
- one typed method per route;
- a public `parse_response` entry point for the cross-version job (#2485);
- a version-skew helper.

The issue body's "Key Decisions" were approved before this ledger and are listed under Assumed. They are
reopened only where a decision below says so; Assumed lists which.

A first implementation exists as commit `b753b2c5` on branch `2386`. It was written without a ledger. Its
challenge produced 22 findings, 7 of them design-level. The full findings are in
`first-attempt-challenge.md` in this directory, and Fn below refers to Finding n there. This ledger settles
those contracts before any code is written. The build from this ledger is commits `48131a39` and
`a0391f27` on branch `2386-take-two`. Its ship-time challenge reopened D20, D21 and D24, restated D23's rationale, and added D25–D27;
Build lists the rework they require.

**Standards first.** Where Home Assistant, HACS or Python library conventions have an established
answer, this ledger follows it, even when that reverses an earlier decision, including the issue's own
Key Decisions. The user's reason: supporting the client is easier, and integration authors know what
to expect. A deviation needs a stated reason in its decision block.

Two prior-art briefs in this directory ground the decisions:

- `prior-art-retryable.md` covers retry signaling (D2–D5).
  Its recommendation, a per-instance flag, was later set aside for HA convention; see D2.
- `prior-art-skew-and-bodies.md` covers body classification and version skew (D18–D24).
- `prior-art-floor-verification.md` covers how client libraries choose and verify a minimum server
  version (D20, D25–D27). It was written when the ship-time challenge reopened D20.

Files involved:

- `client/src/hassette_client/`: `transport.py`, `errors.py`, `client.py`, `parsing.py`, `version.py`,
  `__init__.py`
- `client/tests/`
- `client/pyproject.toml`
- `wire/src/hassette_wire/`, for the response-model changes in D10 and D11, `API_SCHEMA_VERSION` and
  `SystemStatusResponse.api_schema_version` (D25), then
  `frontend/openapi.json` and the frontend types regenerated with
  `uv run python scripts/export_schemas.py --types`
- `src/hassette/core/runtime_query_service.py` (`get_system_status()` builds every `SystemStatusResponse`,
  for `GET /api/health` and the WebSocket status payload, so it sets `api_schema_version`, D25)
- `tools/check_wire_compat.py`, whose tag extraction and reversed oasdiff run D27's guard reuses, and
  `tools/check_client_floor.py`, rewritten in place as D27's guard (request check via the coverage test,
  response check via oasdiff); its tests in `tests/unit/tools/`
- `.github/workflows/tests.yml`, for D27's guard step on every PR
- `.claude/rules/web-api.md`, for D20's bump rule (replacing the release-PR paragraph the first build added)
- `tests/integration/web_api/test_hassette_client.py`
- `docs/pages/web-ui/python-client.md` and its snippets
- `noxfile.py`
- `client/README.md`

Out of scope:

- the CLI port (#2387);
- the cross-version CI job (#2485);
- any server-sent retry signal (`Retry-After`, idempotency keys);
- the HA integration's handling of `UnsupportedServerVersionError` and its repair issue (spec 113).

D20 also reverses spec 114's consumer-owned version floor and its newer-server warning (`design/specs/114-hassette-client/brief.md`).

## Decisions

### D1: Start from the first attempt's code, or rebuild from scratch?

**Deciding factor:** Shortest path to code that matches this ledger, without carrying unreviewed choices
along.

| | A: Cherry-pick `b753b2c5`, then apply the ledger | B: Rebuild from scratch, reading `b753b2c5` as reference |
|---|---|---|
| Work already done that survives | Most of it: 15 of 22 findings were local fixes; the method list, registry and coverage test hold | Re-typed by hand |
| Risk of an unledgered choice surviving | Moderate. Every surviving line was challenged once, and the ship-time challenge checks against this ledger | Low |
| Effort | Smaller | Larger (about 2.2k lines) |
| Reviewability | Diff vs main is the same either way (squash-merge) | Same |

**Recommendation:** A. The challenge found contract problems, not a bad skeleton. Every contract it
questioned is a decision below, and the ship-time challenge checks the code against this ledger.
**Pick B instead if** you want the build to reason through each file fresh instead of editing toward the
ledger.
**Reversibility:** easy (the build can drop the cherry-pick at any point before its first commit)
**Delete list** (added at the sketch challenge). After the cherry-pick, none of these first-attempt pieces
may survive in code, tests or docs, in any file the cherry-pick touched, and the ship-time challenge
checks each one:

- `retryable`, on every class and in every docstring and test (D2);
- the transport's retry classification, and idempotency tracking (D2, D3, D4);
- the per-call `timeout=` on `action()`, and the constructor's `timeout` name, which becomes
  `request_timeout` (D5);
- `APP_ACTIONS` and its `ValueError` (D6);
- `create_session`, its request model use, and its docs (D12);
- `server_is_newer`, `CLIENT_DISTRIBUTION` and the `importlib.metadata` version lookup (D20);
- the release-version floor the first build added after the cherry-pick: every item under Build,
  "Rework to the API schema floor" (D20, D21, D27);
- the commit message's claims about `retryable` and `server_is_newer`, which the squash-merge PR title
  and body replace.

**Ratified:** Chose cherry-picking `b753b2c5` with an explicit delete list over rebuilding, to reuse the challenged skeleton while ensuring no reversed first-attempt surface survives, accepting that the ship-time challenge must check each list item.

### D2: Does the client carry a `retryable` flag at all?

Background: F1, F3, F10, F11 and `prior-art-retryable.md`.

In the first attempt, `retryable` was a `ClassVar` meaning "may succeed if sent again later". As a result:

- a `while exc.retryable` loop resends a timed-out `reload`, which reloads the app twice;
- the same loop spins forever on a TLS certificate failure or an invalid URL.

This decision was first ratified as A, then reopened under the standards-first principle (Summary).

**Deciding factor:** HA library convention.

| | A: Per-instance flag meaning "safe to resend and may help"; the class value is the default; the transport can only lower it | E: No flag. Distinct exception classes carry the meaning; the docs say which failures are worth retrying and which leave the outcome unknown |
|---|---|---|
| Matches HA libraries (aiohue, aioesphomeapi, aioshelly, matter, zwave-js and the rest of the ten surveyed) | No (follows stripe/smithy) | Yes |
| Fits how HA consumes errors | Unused. The integration maps by class; HA retries through `ConfigEntryNotReady` and the next poll | Exactly |
| A script's retry loop | Safe as written on `exc.retryable` | Catches classes; the docs warn that a timeout on `reload`/`trigger_job` has an unknown outcome |
| Transport complexity | Classifies the failure phase, idempotency and 502 vs 504 | None |
| Reverses an approved decision | No | Yes, the issue's "`retryable` class attribute" Key Decision |

**Recommendation:** E. It is what every comparable HA library does and it fits how HA consumes errors. It
also deletes D3, D4 and the transport's retry classification.
**Pick A instead if** script authors who don't read the docs matter more than HA convention.
**Reversibility:** hard after the first release

What E means for the build:

- **No flag.** No exception class or instance has a `retryable` attribute, and the transport does no
  retry classification.
- **Docs, `HassetteTimeoutError`, `HassetteConnectionError` and `GatewayError`.**
  - The server may or may not have received the request, or may still be working on it (a proxy's
    502/504 can arrive while hassette is still reloading).
  - For `action()` and `trigger_job`, check the app's or job's state before resending.
  - A connection failure can also be permanent: a TLS certificate problem or a bad URL.
- **Docs, `ResponseValidationError` on `action()` and `trigger_job`.** When its `status` (D18) is 2xx
  and it is not an `UnexpectedResponseError`, hassette most likely applied the change and only the
  response body failed to parse, so don't resend blindly; but a proxy can answer 2xx too, so check
  the app's or job's state first (revised at the ship-time challenge). An `UnexpectedResponseError`
  means the answer may not have come from hassette (a proxy login page, the SPA at a wrong
  `base_url`), so the outcome is unknown.
- **Docs, which actions are safe to resend.** `start` and `stop` converge on a target state, so
  resending them is safe. `reload` and `trigger_job` are not.
- **Docs, Retrying page.** Two lists:
  - safe to retry with backoff: `BootstrapNotReleasedError`, `ServiceUnavailableError` on a read, and
    any failure on a read;
  - outcome unknown on writes (`action()`, `trigger_job`): `HassetteTimeoutError`,
    `HassetteConnectionError`, `GatewayError`, `UnexpectedResponseError`, `ServiceUnavailableError`
    (hassette never answers a write with 503, so a proxy sent it), and any `ServerError` other than
    `ActionFailedError` (revised at the ship-time challenge). `ActionFailedError` means the action ran
    and failed.

  It states that the client never retries, and that HA's own setup retry and polling are the retry
  mechanism inside HA.

**Ratified:** Switched from A to E under the standards-first principle: no `retryable` flag; distinct exception classes plus documented retry guidance carry the meaning, over a per-instance flag, to match every surveyed HA library and how HA consumes errors, accepting that script authors decide what to retry from classes and docs, and reversing the issue's `retryable` Key Decision. Re-ratified at the sketch comb with corrected guidance: two lists (safe to retry; outcome unknown on writes, which includes `GatewayError` and `UnexpectedResponseError`), "a 2xx `ResponseValidationError` means already applied" excludes `UnexpectedResponseError`, and `start`/`stop` are documented as safe to resend while `reload`/`trigger_job` are not. Refined at the ship-time challenge: a 2xx `ResponseValidationError` is "most likely applied, check before resending" since a proxy can answer 2xx, and a 503 or a generic `ServerError` on a write is outcome-unknown.

### D3: (withdrawn) How does the transport know whether a request is idempotent?

Withdrawn: D2 dropped the `retryable` flag, so nothing consumes idempotency. The underlying fact still
holds: `start`/`stop` converge on a target state and `reload` does not. D2's "safe to resend" docs
bullet uses it.

**Ratified:** Withdrawn as moot under D2 (no `retryable` flag).

### D4: (withdrawn) Is a 502 treated like a 504?

Withdrawn: D2 dropped the `retryable` flag. `GatewayError` covers both statuses, as before.

**Ratified:** Withdrawn as moot under D2 (no `retryable` flag).

### D5: How is the request timeout configured?

Background: F3 and F11. The server holds `POST /apps/{key}/{action}` open until the operation, including
`on_initialize()`, finishes (`routes/apps.py`, `_run_app_action`). `trigger_job` returns 202 right after
dispatch (`routes/scheduler.py:49-75`), so it doesn't hold the request.

This decision was first ratified as A, then reopened under the standards-first principle (Summary).

**Deciding factor:** HA library convention.

| | A: `timeout=` on `action()` only; default stays 10 s | B: `timeout=` on every method | C: No override; longer default for `action()` | E: One client-wide `request_timeout` (constructor, default 10 s); no per-call override |
|---|---|---|---|---|
| Matches HA libraries (frenck-style elgato, wled and others: `request_timeout` on the client) | No | No (big-SDK style) | No | Yes |
| Slow reload can finish | Yes, caller sets it | Yes | Up to the new default | Yes, via a second client with a longer `request_timeout`; cheap, since the session is shared and the client holds no state |
| Polling still detects a dead server quickly | Yes | Yes | Yes | Yes, if the polling client keeps the short timeout |
| Surface | One kwarg | ~30 kwargs | None | Constructor only |

**Recommendation:** E. It is the HA convention, the second client costs nothing, and method signatures
stay uniform. The constructor parameter is named `request_timeout` to match those libraries; the first
attempt called it `timeout`. It is a `float` in seconds, applied per request as aiohttp's
`ClientTimeout(total=request_timeout)`, which is what D17 logs as the timeout in effect. The `action()` docs say the server answers only after the operation
finishes, including `on_initialize()`, and show the second-client pattern for slow apps.
**Pick A instead if** a single client matters more than convention.
**Reversibility:** easy
**Ratified:** Switched from A to E under the standards-first principle: a single constructor-level `request_timeout` (default 10 s) with no per-call override, plus documented second-client guidance for slow actions, over a per-call `timeout=` on `action()`, to match HA library convention, accepting that slow reloads need a second client.

### D6: Does `action()` check the action name locally?

Background: F5. The first attempt checked `action` against a compiled-in `APP_ACTIONS` and raised
`ValueError`.

**Deciding factor:** Letting the server decide what actions exist. The response type `OpenAppAction` is
already open for exactly this case.

| | A: Drop the check; an unknown action becomes the server's `NotFoundError` | B: Keep the check, raise a `HassetteClientError` subclass | C: Keep `ValueError` |
|---|---|---|---|
| Older client can drive a newer server action | Yes (with a cast past the `AppAction` Literal) | No | No |
| Misuse caught without a round trip | Statically, via the `AppAction` annotation | Yes | Yes |
| Code change | Deletion | New class | None |

**Recommendation:** A. It deletes code, matches the open response type, and the static annotation still
catches typos.
**Pick B instead if** you want a runtime guard and accept that new actions need a client upgrade.
**Pick C instead if** you consider an unknown action a programmer bug.
**Reversibility:** easy
**Ratified:** Chose dropping the local `APP_ACTIONS` check (unknown actions become the server's `NotFoundError`) over a runtime guard, to let an older client drive a newer server's actions, accepting that misuse is caught only statically or by a round trip.

### D7: What do invalid local arguments raise, and which path segments are rejected?

Background: F5 and F7. uvicorn decodes `%2F` before routing, so `get_app("foo/config")` reaches the
`/apps/{key}/config` route. The server's key regex rejects `/` anyway (`routes/apps.py:37`).

**Deciding factor:** Never sending a request to a route the caller didn't name, with a failure contract
that is true as written.

| | A: `path_segment` rejects an empty value, `.`, `..` and any value containing `/`, with `ValueError`; the contract reads "every network or server failure is a `HassetteClientError`; invalid arguments raise `ValueError`" | B: Same rejections, but raise an `InvalidArgumentError(HassetteClientError)` | C: Keep encoding `/`, document it |
|---|---|---|---|
| Wrong-route request possible | No | No | Yes |
| One `except HassetteClientError` catches everything | No (argument errors are separate) | Yes | No |
| Matches Python convention for caller bugs | Yes | No | Yes |

**Recommendation:** A. A bad argument is a bug in the caller's code, which Python reports with
`ValueError`. Narrowing the contract's wording makes it true.
**Pick B instead if** you want one catch-all base, even for programmer errors.
**Pick C instead if** a future string path parameter legitimately contains `/`.
**Reversibility:** easy
The contract's exact wording, revised at the sketch challenge: "every network or server failure is a
`HassetteClientError`, and so is a malformed `base_url`, because aiohttp's `InvalidURL` is wrapped as
`HassetteConnectionError`, which is how an HA config flow maps a bad URL to `cannot_connect`.
Invalid path arguments and a non-positive `request_timeout` raise `ValueError`, and so does a token containing a control character such as
`\r` or `\n`, or a token combined with credentials in `base_url` or a session-level `auth=`, which aiohttp itself rejects on the first request (D8). A closed session raises aiohttp's own `RuntimeError` (D8).
`UnsupportedServerVersionError` comes only from `check_server_version()` (D20)." The docs publish this
as a failure-mode table with three columns: exception, cause, and whether `HassetteClientError` catches
it.

**Ratified:** Chose rejecting empty, `.`, `..` and `/` in `path_segment` with `ValueError`, with the failure contract worded exactly as quoted above and published as a docs failure-mode table, over a client-error subclass or encoding `/`, to make wrong-route requests impossible and the contract true as written, accepting that `except HassetteClientError` doesn't catch argument bugs or a closed session.

### D8: What happens to exceptions from below aiohttp's `ClientError` (closed session, bad header values)?

Background: F9. aiohttp raises a raw `RuntimeError("Session is closed")` (`aiohttp/client.py:581`). HA
closes its shared session on shutdown, under any long-lived client.

**Deciding factor:** Follow HA library convention (see Summary, "Standards first"). A closed session is
a bug in the caller's code, not a network failure.

| | A: Catch `RuntimeError` around the session call → `HassetteConnectionError`, cause chained | B: Check `session.closed` first | C: Let it propagate; docs state the client never closes the session and a closed one raises aiohttp's own error |
|---|---|---|---|
| Closed session raises a `HassetteClientError` | Yes | Yes (a narrow race remains) | No |
| Catches unrelated `RuntimeError`s ("Event loop is closed", misuse outside a task) as connection failures | Yes (a broad built-in catch) | No | No |
| Inspects another component's state | No | Yes | No |
| Matches HA libraries (aiohue, wled, matter, zwave-js) | No | No | Yes |

**Recommendation:** C. HA libraries let it through, and catching a broad built-in exception would
report programming errors as network failures. D7's contract ("network or server failures") doesn't
cover misuse of the caller's own session.
**Pick A instead if** a single catch-all base matters more than convention.
**Pick B instead if** you want a specific "session closed" message and accept the race.
**Reversibility:** easy
**Bad header values** (added at the sketch comb). aiohttp 3.14 raises a plain `ValueError` ("Forbidden
control character detected in headers") when a header value contains `\r` or `\n` (see Assumed).
The client adds no token check of its own.

| | A: aiohttp's `ValueError` propagates on the first request; D7's contract names it | B: Check the token in the constructor, raise `ValueError` there |
|---|---|---|
| Exception type | `ValueError` (D7's category) | `ValueError` |
| When it surfaces | First request | Construction |
| Code | None beyond the contract clause and a test | A check duplicating aiohttp's |
| Matches HA libraries (wled, aiohue, elgato don't validate tokens) | Yes | No |

**Recommendation:** A. aiohttp already raises the right type, and a duplicate check would drift from
aiohttp's own rules.
**Pick B instead if** you want a config flow to fail at construction rather than on the first call.
**Reversibility:** easy

**Ratified:** Switched from A to C under the standards-first principle: a closed session's `RuntimeError` propagates unchanged and the docs say so, over wrapping it or pre-checking, to match HA library convention and avoid a broad built-in catch, accepting that `except HassetteClientError` doesn't cover a closed session. At the sketch comb, also chose letting aiohttp's own `ValueError` for a control character in the token propagate on the first request over a constructor check, to avoid duplicating aiohttp's rule, accepting that the error surfaces at the first call.

### D9: Can the exceptions be copied and pickled?

Background: F8. `copy.copy` and `pickle` both raise `TypeError` today, because the constructors are
keyword-only.

**Deciding factor:** Standard exception behavior for a published library.

**Recommendation:** Yes. Every exception class that carries attributes (`HassetteHTTPError` and
its subclasses including `RedirectError` with `location`, `ResponseValidationError` and its
`UnexpectedResponseError` subclass, `UnsupportedServerVersionError`)
round-trips through `copy` and `pickle` with every attribute intact.
**Pick "no" instead if** you consider cross-process use out of scope and are willing to mark the
constructors non-public.
**Reversibility:** easy
**Ratified:** Chose making every attribute-carrying exception class (`HassetteHTTPError` and subclasses including `RedirectError`, `ResponseValidationError` and subclasses, `UnsupportedServerVersionError`) round-trip through `copy`/`pickle` with all attributes over declaring constructors private, to give standard exception behavior, accepting a little reconstruction code per class.

### D10: Which closed single-value `Literal` fields on response models become open?

Background: F4; the user picked option A in the first walk. Leniency in `hassette_wire` attaches only to
`Open*` aliases (spec 121). If a newer server adds a value to a closed `Literal`, an older client raises
`ResponseValidationError`. For `action()` that happens after the action has already run.

The closed single-value status fields:

- `ActionResponse.status` (`wire/apps.py:78`)
- `JobTriggerResponse.status` (`wire/telemetry.py:394`)
- `LivenessResponse.status` (`wire/health.py:61`)

`SessionResponse.status` (`wire/auth.py:33`) stays closed: D12 removed `create_session`, so no client
method returns it and the audit doesn't reach it.

**Deciding factor:** Making the "tolerates a newer server" promise true, and keeping it true.

| | A: Open all three, plus a test that fails on any closed `Literal`/enum reachable from a `HassetteClient` return type, except types spec 121 D14 declares closed (`SourceTier`, `LogLevel`) | B: Keep them closed; docs say only `Open*` fields tolerate new values |
|---|---|---|
| Old client survives a new status value | Yes | No |
| Guards future models | Yes | No |
| Touches `hassette_wire` (and `openapi.json`) | Yes (three fields, one regenerate) | No |

**Recommendation:** A. A status field is the field most likely to grow. A closed one fails after the
side effect has already happened, which is the worst time.
**Pick B instead if** you'd treat any new status value as a breaking change that requires a client
upgrade.
**Reversibility:** hard after release (a closed field reopened later doesn't help clients already in use)
**Ratified:** Chose opening `ActionResponse.status`, `JobTriggerResponse.status`, and `LivenessResponse.status` plus an audit test over every client-reachable response model (excepting spec 121 D14's closed types), over narrowing the docs, to make the newer-server promise true and keep it true, accepting a wire/`openapi.json` change in this PR.

### D11: Does `LivenessResponse.status` stop defaulting, so `{}` isn't a liveness answer?

Background: F4. `LivenessResponse` validates `{}` today, so any 200 JSON object counts as "live".
`TelemetryStatusResponse` counters default to 0 in the same way.

**Deciding factor:** A probe should fail loudly on an empty or keyless body. With D10, `status` is open,
so any string validates: this rejects `{}`, not every foreign body. D18's Content-Type rule is what
rejects most foreign bodies.

| | A: Make `LivenessResponse.status` required (no default) | B: Leave the defaults |
|---|---|---|
| `{}` from a foreign server counts as live | No | Yes |
| Server-side change | Required in the schema; the server already always sends it | None |
| Counters defaulting to 0 | Left alone (a missing counter is a real schema break that an old server can produce) | Same |

**Recommendation:** A. It costs one default, and the server always sends the field.
**Pick B instead if** the body classification rule (D18) already rejects foreign bodies well enough.
**Reversibility:** easy before release
**Ratified:** Chose making `LivenessResponse.status` required over keeping its default, so a foreign `{}` isn't read as "live", accepting a required-field schema change (the server already always sends it); counter defaults are left alone.

### D12: `create_session`: keep it with a documented precondition, or drop it?

Background: F14. aiohttp's default `CookieJar` rejects cookies from IP-address hosts, so against
`http://127.0.0.1:8126` the call returns 200 and stores nothing. In HA, the jar is shared with every
integration. The issue requires one method per route, with zero exemptions in the coverage test.

**Deciding factor:** Ship no method that fails silently in the headline deployment. The zero-exemption
rule is an internal test convention, not an HA or Python one.

| | A: Keep it; docstring states the jar precondition (`CookieJar(unsafe=True)` for IP hosts) and that HA's shared session is unsuitable; test with an IP host | B: Remove it; the coverage test exempts the route as browser-only |
|---|---|---|
| Silent no-op possible | Documented, still possible | Gone |
| Zero-exemption coverage rule | Holds | One exemption |
| Non-browser use case | Scripts that want a cookie session (rare) | None |

**Recommendation:** B, revised at the sketch challenge. Both named consumers authenticate with bearer
tokens, and no consumer of cookie sessions outside a browser exists. The zero-exemption rule is an
internal test convention, not an HA or Python one, and the coverage test's purpose (no forgotten route)
still holds with a named exemption. This also applies D12's own deciding factor, plus CLAUDE.md's
"Convenience APIs must earn their place".
**Pick A instead if** a concrete non-browser consumer of cookie sessions exists or is planned.
**Reversibility:** easy before release (adding the method later is additive)
**Ratified:** Switched from A to B at the sketch challenge: `create_session` is removed and the coverage test exempts `POST /api/auth/session` as browser-only with a stated reason, over keeping it with a documented precondition, so the client ships no method that silently fails in the headline deployment, accepting one named exemption to the coverage rule.

### D13: Do list responses validate whole or per element?

Background: F15.

**Deciding factor:** A typed client fails loudly on schema drift rather than silently dropping data.

**Recommendation:** Whole. One invalid element fails the call with `ResponseValidationError`, and the
docs say so. Unknown fields and values are already absorbed, so a failing element is real drift.
**Pick an opt-in partial mode instead if** consumers report entities going blank because of single bad
rows.
**Reversibility:** easy (a partial mode is additive)
**Ratified:** Chose whole-list validation (one bad element fails the call, documented) over an opt-in partial mode, to fail loudly on real drift, accepting that one bad row blanks the whole response.

### D14: What does the OpenAPI coverage test prove beyond route coverage?

Background: F16. FastAPI ignores unknown query parameters, so a misnamed filter silently does nothing.

**Deciding factor:** Catching silent filter typos and wrong response models while the OpenAPI document
is already loaded.

| | A: Query keys and response model | B: Query keys only | C: Routes only |
|---|---|---|---|
| Misnamed filter fails a test | Yes | Yes | No |
| Method parsing the wrong model fails a test | Yes | No | No |
| Effort | Small–medium (unwrap `list[...]` and `X \| None`) | Small | None |

**Recommendation:** A. Nothing else catches either mistake.
**Pick B instead if** matching response schemas through `anyOf`/`items` turns out to be fiddly.
**Reversibility:** easy
**Ratified:** Chose having the coverage test check query parameter names and response models against `openapi.json` over query keys only or routes only, to catch silent filter typos and wrong-model parses, accepting the work of unwrapping list/optional schemas.

### D15: What do exception messages contain?

Background: F17. Up to 500 characters of a non-problem body went into `str(exc)`, and `base_url`
userinfo went into connection messages. That contradicts `parsing.py`'s rule that server payloads never
go into exception text.

**Deciding factor:** Apply the existing rule (no payload in messages) consistently.

| | A: Non-problem body excerpt on an attribute only (`str(exc)` carries status, media type and byte length); a problem's `detail` stays in the message (it's server-authored text); userinfo stripped from URLs in messages | B: Keep the excerpt in the message |
|---|---|---|
| Payload in logs by default | No | Yes |
| Diagnostic value | Kept (attribute) | Kept |
| Consistent with the no-values rule | Yes | No |

**Recommendation:** A.
**Pick B instead if** you value one-glance terminal diagnosis over log hygiene.
**Reversibility:** easy
**Ratified:** Chose keeping foreign-body excerpts on an attribute (message carries status, media type, byte length; problem `detail` stays; URL userinfo stripped) over excerpts in the message, to apply the no-payload-in-messages rule consistently, accepting that diagnosis needs reading an attribute.

### D16: Are response bodies size-capped?

Background: F18. `response.read()` buffers the whole body.

**Deciding factor:** Whether the memory risk on an HA host justifies new surface, given the server is the
user's own hassette.

| | A: No cap; docs recommend `limit=` on constrained hosts | B: Cap error bodies only (a few KB) | C: `max_response_bytes` option plus a dedicated error |
|---|---|---|---|
| Protects HA from a huge body | No | Partly (proxy error pages) | Yes |
| New surface | None | None | Option + exception |
| Effort | Docs | Small | Medium (streamed read) |

**Recommendation:** B. Only an excerpt of an error body is ever kept, so reading the rest is pure
waste. Capping it costs no surface. Success bodies come from the user's own server.
**Pick A instead if** you want the transport's read path to stay a single `read()`.
**Pick C instead if** the client is expected to talk to untrusted or proxied servers from Pi-class
hosts.
**Reversibility:** easy
The cap and the excerpt length are each a single named module constant in `transport.py`; the build
picks the values (a few KB for the read, shorter for the excerpt).

**Problem bodies** (refined at the sketch comb). The cap applies only to error bodies whose D18 kind is
not PROBLEM. An `application/problem+json` body is read whole, because truncating it would make it
unparseable and cost a real hassette error its code-specific class. hassette's problem bodies are small
by construction: a 422's `detail` carries only each error's `loc` and `msg` (`web/errors.py:224-227`).

| | A: Cap only non-problem error bodies; PROBLEM is read whole | B: Cap every error body; a truncated problem is classed by status, `problem=None` |
|---|---|---|
| A real hassette error keeps its code class | Always | Only under the cap |
| Protects against huge proxy/HTML pages | Yes | Yes |
| Exposure to a huge `problem+json` body | Unbounded (only hassette sends that type) | None |

**Recommendation:** A. D18 already computes the media type, and hassette's problem bodies are small by
design.
**Pick B instead if** you want a hard ceiling on every error read, whoever sent it.
**Reversibility:** easy

**Ratified:** Chose capping error-body reads at a few KB, except `application/problem+json` bodies which are read whole, over no cap or a configurable cap, and over capping problem bodies too, to stop reading foreign bytes nothing keeps without costing a hassette error its class, accepting that success bodies and problem bodies remain unbounded.

### D17: Observability: logging on recovery paths, `Retry-After`, and the retry snippet

Background: F19. `client/src` has no logger. Two fallback paths swallow silently, and the docs snippet
retries with a fixed 5 s sleep.

**Deciding factor:** Every recovery path emits a signal (logging rule: library code calls `getLogger`
only), and the documented snippet is safe to copy.

| | A: Module loggers with DEBUG on each fallback path and per-request outcome; snippet shows bounded exponential backoff with jitter | B: A plus `retry_after: float \| None` on `HassetteHTTPError` | C: Leave as is |
|---|---|---|---|
| Silent paths observable | Yes | Yes | No |
| Honors a proxy's `Retry-After` | No | Yes | No |
| New public surface | None | One attribute | None |

**Recommendation:** A. The server sends no `Retry-After` today, and the prior-art brief lists it as a
later, additive change.
**Pick B instead if** a proxy in front of hassette sends `Retry-After`, or the server is about to.
**Reversibility:** easy (B is additive later)

What A means for the build. The user asked for logs that are useful in practice, not a minimum:

- **Loggers.** Each module calls `getLogger(__name__)` under the `hassette_client` namespace, so one HA
  `logger:` entry enables all of it. The library never configures handlers or levels.
- **Every request, at DEBUG.**
  - On send: method, path, the names of the query parameters sent, and the timeout in effect.
  - On completion: method, path, status, media type, body size in bytes, and duration in ms.
- **Every failure, at DEBUG, where the exception is raised.**
  - The exception class, status and problem code.
  - The underlying aiohttp exception's type, which tells a TLS or URL failure apart from a refused
    connection or a read timeout.
  - Never at ERROR. The caller owns that decision.
- **Every fallback or judgment path, at DEBUG,** each naming what was decided:
  - a missing Content-Type fell back to parsing (D18), on a 2xx or a probe 503;
  - a probe 503 failed to parse and was raised;
  - a malformed problem body was classed by status;
  - a non-problem error body was truncated at the cap (D16).
- **Nothing above DEBUG.** Every condition the transport notices either raises, where the exception
  carries it, or is a fallback logged above. A library that logs a WARNING and then raises reports the
  same failure twice, because HA logs the exception again when the integration handles it. Per-request
  DEBUG logging is what aiohue, the frenck-style libraries and httpx do.
- **Never logged:** the token, cookies, body content, or URL userinfo (D15).
- **Docs snippet:** bounded exponential backoff with jitter.

**Ratified:** Chose module loggers with DEBUG on every request, failure (with the underlying aiohttp exception type) and fallback path, plus a bounded-backoff-with-jitter snippet, over also exposing `retry_after`, to make the client diagnosable from HA's logger config alone, accepting no `Retry-After` support until the server sends one. Revised under the standards-first principle: the two WARNINGs originally ratified (non-JSON 2xx, unparseable problem body) were dropped, since they logged conditions that also raise.

### D18: How does the transport classify a response body (problem / model / foreign)?

Background: F2, F12 and F13; `prior-art-skew-and-bodies.md` Q2. The first attempt classified bodies by
trying to parse them and never read `Content-Type`, even though the server sends problems as
`application/problem+json` (`web/errors.py:32`). As a result:

- a foreign JSON 503 could be misread as "not ready";
- a proxy's `200 text/html` login page raised an opaque `json_invalid` error that reads like version
  skew.

A wrong `base_url` prefix hits the SPA catch-all, which returns `200 text/html`, so the same thing
happens there.

**Deciding factor:** One rule covers every classification the transport makes. It uses the signal the
server already sends and degrades gracefully when a proxy drops the header.

| | A: Parse attempt only (as built) | B: Content-Type strict (no JSON type means foreign) | C: Content-Type decides, parsing confirms; a missing header falls back to parsing |
|---|---|---|---|
| Foreign JSON 503 misread as "not ready" | Yes | No | No |
| 2xx HTML diagnosed as "not hassette" | No (reads as skew) | Yes | Yes |
| Proxy strips the header | Unaffected | Every response fails | Falls back to today's behavior |
| Where the classification lives | Three separate parse attempts | One media-type classification feeding the outcome table | One media-type classification feeding the outcome table |
| Prior art | stripe, google, githubkit | adguardhome, aiohttp `resp.json()` | azure, openai, RFC 9110 §8.3 |

**Recommendation:** C. It fixes both symptoms with one rule and costs nothing when the header is
missing.
**Pick A instead if** you've seen proxies in HA setups rewrite `Content-Type` to a wrong but present
value.
**Pick B instead if** you'd rather fail loudly on a missing header than guess.
**Reversibility:** easy

What C means for the build:

- **Media type kinds.** The transport strips parameters, lowercases, and classifies the media type:
  - `application/problem+json` → PROBLEM;
  - anything else matching aiohttp's `^application/(?:[\w.+-]+?\+)?json` → JSON;
  - any other value → OTHER;
  - no header → MISSING.

| Status | Kind | Result |
|---|---|---|
| 2xx | JSON or MISSING | Parse the model; a failure raises `ResponseValidationError` |
| 2xx | OTHER or PROBLEM | `UnexpectedResponseError` (a `ResponseValidationError` subclass, D19) with entry `<body>: not_json (<media type>)` |
| 503 on a probe (`get_ready`, `get_telemetry_status`) | JSON, or missing | Parse the status model; a parse failure raises `ServiceUnavailableError` |
| 503 on a probe | anything else | Raise as on any other route (by problem code, else by status) |
| other non-2xx | PROBLEM | Parse `ProblemDetail`, class by code; a parse failure gives `problem=None`, class by status, message notes "malformed problem" (no payload) |
| 3xx | any | `RedirectError` (a `HassetteHTTPError` subclass) carrying `location` (kept from `b753b2c5`; hassette's API never redirects, so a proxy did) |
| other non-2xx | JSON, OTHER, MISSING | `problem=None`, class by status |

- **Response attributes.** When `ResponseValidationError` is raised from a response, it carries
  `status: int | None` and `content_type: str | None`. Both are `None` from a bare `parse_response`.
- **Message hint.** For OTHER/PROBLEM bodies, the message adds "check base_url, or whether a proxy
  answered".
- **Foreign-body excerpt.** A foreign body's excerpt lives on an attribute, per D15.

**Ratified:** Chose Content-Type-decides-and-parse-confirms with a parse fallback for a missing header, over parse-attempt-only or strict Content-Type, to fix the misread probe 503 and the opaque proxy-HTML error with one rule, accepting that a proxy rewriting Content-Type to a wrong-but-present value will be misclassified.

### D19: Is "not a hassette response" its own exception subclass now?

Background: `prior-art-skew-and-bodies.md` Q2, open question. The integration's config flow could show
"this URL doesn't point to hassette" instead of `cannot_connect`.

**Deciding factor:** Follow HA library convention (see Summary, "Standards first"). HA integrations
map library errors to config-flow and setup errors by exception class.

| | A: No subclass; D18's `content_type` attribute distinguishes it | B: `UnexpectedResponseError(ResponseValidationError)`, raised for a 2xx body that isn't JSON (D18) |
|---|---|---|
| Config flow can tell the two cases apart | Yes, by checking `exc.content_type` | Yes, by class |
| Matches how HA maps library errors | No (an attribute check in one place) | Yes |
| New public surface | None | One class |
| Existing `except ResponseValidationError` keeps working | Yes | Yes (subclass) |

**Recommendation:** B. HA integrations branch on exception classes everywhere else, and the subclass
keeps every `except ResponseValidationError` working. The `status`/`content_type` attributes from D18
stay as well.
**Pick A instead if** you'd rather not add a class until a consumer asks for it.
**Reversibility:** easy
**Ratified:** Switched from A to B under the standards-first principle: a 2xx non-JSON body raises `UnexpectedResponseError(ResponseValidationError)`, over an attribute-only distinction, to match HA's class-based error mapping, accepting one more public class.

### D20: How is version skew handled, and who owns the minimum server version?

Background: F6; `prior-art-skew-and-bodies.md` Q1; `prior-art-floor-verification.md`. The direction that
fails is client-newer-than-server, because the HACS integration updates first. A missing route then
surfaces as a generic `NotFoundError`, and a missing query parameter is silently ignored.

This decision was ratified twice before (a skew enum, then a release-version floor) and reopened at the
ship-time challenge. The release-version floor as built had three problems:

- a v0.55.0 server, at the floor, couldn't parse `GET /api/apps` in this client, because its guard checked
  requests only;
- the floor was picked by hand on the release-please PR, a branch the bot regenerates;
- a build from main reports the previous release, so it reads as older than the routes it serves.

HA core precedent, from `~/source/core/homeassistant/components/`:

- **The library raises.** wled (`WLEDUnsupportedVersionError`), music_assistant and zwave_js
  (`InvalidServerVersion`), matter (`ServerVersionTooOld`). The integration catches it in setup and the
  config flow.
- **Libraries whose authors also own the server use an integer API schema version the server
  advertises,** bumped in the PR that makes the change: zwave-js-server-python
  (`MIN_SERVER_SCHEMA_VERSION`), python-matter-server (`SCHEMA_VERSION`; HA's `matter/api.py:354` checks
  `server_info.schema_version < TOPOLOGY_SCHEMA_VERSION`), music-assistant (`API_SCHEMA_VERSION`;
  `music_assistant/config_flow.py:113`).
- **Release-version floors are for servers the library author doesn't own:** mealie
  (`MIN_REQUIRED_MEALIE_VERSION`, compared by the integration), wled, docker-py.

No integration in HA core warns about a merely newer server.

**Deciding factor:** HA convention for a library that owns its server, with a floor that is bumped in the
change that needs it and verified by CI.

| | R: Release-version floor (`MIN_SERVER_VERSION`, as first built) | S: Integer API schema version the server advertises; the library owns `MIN_API_SCHEMA_VERSION`; `check_server_version(health)` raises `UnsupportedServerVersionError(HassetteClientError)` | M: The mealie pattern: no client helper; the integration keeps its own floor |
|---|---|---|---|
| HA precedent | wled, mealie (servers they don't own) | zwave-js, matter, music-assistant (servers they own) | mealie |
| Where a bump happens | The release-please PR, by hand | The feature PR that makes the client need it | The integration, from release notes |
| Picking the number | Guess which release has the routes | The next integer | Read release notes |
| A build from main reports correctly | No, it reports the last release | Closer: it reports the latest bump, which can lag API added after it (one bump per release; see Build, calls made during the build) | No |
| New surface | A constant, a function, an exception | The same, plus one health field and one wire constant (D25) | None |

**Recommendation:** S. It is what HA's own-server libraries do, it moves the bump into the PR that
creates the need, and it makes the guard independent of release numbers (D27).
**Pick R instead if** no server-side change is acceptable. **Pick M instead if** you'd rather have no
client surface and a floor kept by hand in the integration.
**Reversibility:** hard after release (a public constant, field and exception)

What S means for the build:

- **`MIN_API_SCHEMA_VERSION`** is a public `int` constant in `hassette_client/version.py`: the oldest API
  schema this client release works with. It replaces `MIN_SERVER_VERSION`, which is deleted.
- **`hassette_wire.API_SCHEMA_VERSION`** is the server's current API schema (D25). It starts at `1` in
  this change, and `MIN_API_SCHEMA_VERSION` starts at `1` too, since the client already calls routes no
  released server has.
- **The floor release** is the oldest `v*` tag whose `hassette_wire.API_SCHEMA_VERSION` is at least
  `MIN_API_SCHEMA_VERSION` (a tag without the constant counts as `0`), or HEAD when no tag qualifies. D27's
  guard checks against its `openapi.json`.
- **The bump rule.** A PR that makes the client depend on server API missing from the floor release raises `API_SCHEMA_VERSION` by one, unless it was already raised since
  the last release, and sets `MIN_API_SCHEMA_VERSION` to it, in the same PR. D27's guard fails until it
  does. The constant's docstring and `.claude/rules/web-api.md` state the rule.
- **`check_server_version(health)`** raises `UnsupportedServerVersionError` when the server's
  `api_schema_version` is below `MIN_API_SCHEMA_VERSION` (D21). The exception carries `server_version` (the
  release string the server reported, for the message), `api_schema_version` and
  `min_api_schema_version`, and says to upgrade the hassette server or install an older hassette-client.
- **The check is explicit, not automatic.** This is the one deviation from wled and matter, which raise
  from their connect call. hassette-client is plain HTTP with no connect step, and `get_health()` has to
  answer whatever the server's version, so the CLI can still report on an older server and health polling
  keeps getting status instead of exceptions. The integration calls the check during setup and in the
  config flow.
- **Not here.** A newer-server warning (no HA integration does it) and a server-declared oldest client
  (D26). The integration's own handling is spec 113's: `unsupported_version` in the config flow, and
  `ConfigEntryNotReady` at setup.

**Ratified:** Switched from R to S at the ship-time challenge: an integer API schema version the server advertises, with `MIN_API_SCHEMA_VERSION` owned by the client and bumped in the feature PR that needs it, over a release-version floor bumped on the release-please PR, to follow HA convention for libraries that own their server and make builds from main report correctly, accepting a new health field and wire constant (D25).

### D21: How does the check compare, and what does a server that reports no schema mean?

Background: under D20 the check compares two integers. Servers released before this change send no
`api_schema_version` at all. The release-version check this replaces passed an unreadable version (fail
open), which left callers re-parsing `health.version` to tell a pass from an unchecked one (ship-time
challenge F8).

**Deciding factor:** A server that can't have the routes the floor exists for is reported as too old, with
no unchecked state for callers to detect.

| | A: Integer `<`; a missing field parses as `0`, below every floor, so the check raises | B: Integer `<`; a missing field passes (fail open) and the check returns whether it compared |
|---|---|---|
| Pre-schema server | Raises "upgrade hassette" | Passes; caller must notice and warn |
| HA precedent | matter: `server_info is None or server_info.schema_version < X` | mealie's `version.valid and ...` for unparseable release strings |
| Caller code | `try`/`except` only | An extra branch on the return value |
| Runtime dependency | None (`packaging` is dropped) | None (`packaging` is dropped) |

**Recommendation:** A. A server without the field predates schema 1 and therefore every route the floor
exists for, so "too old" is the true answer. With no unreadable case, the check returns `None` and raises
below the floor, and the docs example loses its second parse.
**Pick B instead if** some caller must run against pre-schema servers through the check. The CLI doesn't
call it, so none does today.
**Reversibility:** easy before release
**Ratified:** Chose integer comparison where a missing `api_schema_version` parses as `0` and the check raises, over failing open, so a pre-schema server is reported as too old with no unchecked state for callers to detect, accepting that no caller can pass the check against a pre-schema server.

### D22: (withdrawn) Where does the client get its own version?

Withdrawn: under D20 the client compares the server's schema against `MIN_API_SCHEMA_VERSION`, not against
its own version, so nothing needs the client's version at runtime.

**Ratified:** Withdrawn as moot under D20.

### D25: Where, and under what name, does the server advertise its API schema?

**Deciding factor:** The value arrives with the response `check_server_version` already takes, under a name
that can't be confused with hassette's other schema versions.

| | A: `api_schema_version: int = 0` on `SystemStatusResponse` (`GET /api/health`), from a `hassette_wire.API_SCHEMA_VERSION` constant | B: A separate `GET /api/version` route | C: A response header on every response |
|---|---|---|---|
| Arrives with what the check takes | Yes | No, a second call | Yes, but not on the parsed model |
| HA precedent | matter and music-assistant put it in the server-info payload | None | None |
| One shared definition (server and D27's guard read it) | Yes, in hassette-wire, released in lockstep | Needs its own constant anyway | Same |
| New surface | One field, one constant | A route, a model, a client method | A header contract |

The name is `api_schema_version`, not HA's bare `schema_version`, because hassette already uses "schema
version" for the telemetry database's migration head (`SchemaVersionError`). The field defaults to `0`, so
lenient parsing of a pre-schema server's health gives D21's "too old".

**Recommendation:** A.
**Pick B instead if** you want version data off the health route entirely. **Pick C instead if** every
response, not only health, should carry it.
**Reversibility:** hard after release (a wire field and constant)
**Ratified:** Chose `api_schema_version: int = 0` on `SystemStatusResponse` (`GET /api/health`), sourced from `hassette_wire.API_SCHEMA_VERSION`, over a separate route or a response header, so the value arrives with the response the check takes and has one shared definition, accepting a wire field and constant that are hard to change after release.

### D26: Does the server also advertise the oldest client schema it supports?

music-assistant's server sends `min_supported_schema_version` so it can turn away old clients. hassette's
server never turns away a client: an older client is covered by lenient parsing and
`check_wire_compat`'s forward run.

**Deciding factor:** No field without a consumer.

**Recommendation:** No. Nothing on the server would set it, and nothing in the client would act on it.
**Pick yes instead if** the server will ever drop support for old clients.
**Reversibility:** easy (additive later)
**Ratified:** Chose not advertising an oldest supported client schema over adding `min_supported_schema_version`, since the server never turns away a client and nothing would consume the field, accepting that it must be added later if the server ever drops old clients.

### D27: What verifies the floor, and on which PRs?

Background: `prior-art-floor-verification.md`. No surveyed HA library checks its floor in CI; they test
fixtures at the current schema. opensearch-py is the one client found testing responses at old servers,
with a live container matrix. `tools/check_wire_compat.py` already runs oasdiff in the "new client, old
server" direction (blocking on `response-required-property-removed` and
`response-property-became-optional`), but only against the latest tag and with
`tools/wire_compat_ignore.txt` applied, which is where floor-to-HEAD drift accumulates.

**Deciding factor:** The guard fails on the verified v0.55.0 break, on the PR that causes it.

| | A: Every PR. Floor spec: the floor release's `openapi.json` (D20). Checks: the coverage test's request checks, plus the reversed oasdiff blocking IDs, limited to operations the client calls and the statuses it parses as models (2xx, and a probe's 503), with no ignore file | B: The same checks, on release-please PRs only | C: A, plus a job that runs the floor tag's published Docker image and calls it with the client | D: Request checks only (as first built) |
|---|---|---|---|---|
| Catches the v0.55.0 `GET /api/apps` break | Yes | Yes | Yes | No |
| Fails on the PR that causes it | Yes | No, at release | Yes | n/a |
| Cost | Spec diffs from committed files | Same | A container per run; unverified that a bare image serves the client's routes without Home Assistant | Lowest |
| Prior art | hassette's own oasdiff tooling, aimed at the floor | Same | opensearch-py | None |

The guard also fails when `MIN_API_SCHEMA_VERSION` is above `API_SCHEMA_VERSION` at HEAD, which catches
a typo or a missing server bump, and its failure message states D20's bump rule.

**Recommendation:** A.
**Pick B instead if** feature-PR CI time matters more than failing early. **Pick C instead if** a spec
check ever misses a real break.
**Reversibility:** easy (CI only)

What A means for the build:

- **The tool.** `tools/check_client_floor.py` is rewritten in place, keeping its name and its job of
  resolving a spec and running `client/tests/test_openapi_coverage.py` against it through
  `HASSETTE_CLIENT_OPENAPI`. The release-version resolution (`release_version()`, the "tag doesn't exist
  yet" fallback, `FloorSpecError`'s message) goes. `tests/unit/tools/test_check_client_floor.py` is
  rewritten to match.
- **Finding the floor release.** `API_SCHEMA_VERSION` lives in `wire/src/hassette_wire/health.py`, next to
  `SystemStatusResponse`, and is re-exported from `hassette_wire`. The guard lists tags the way
  `resolve_latest_release_tag` does (`git tag --list 'v*' --merged HEAD --sort=-v:refname`, so pre-release
  tags are candidates like any other; the build instead fails on reaching one, see Build). For each tag, newest first, it reads that file with
  `git show <tag>:<path>` and takes a module-level `API_SCHEMA_VERSION = <int>` with `ast`; a missing file
  or name is `0`. It stops at the first tag below `MIN_API_SCHEMA_VERSION`, which is sound because the
  bump rule only ever raises the constant. The last qualifying tag is the floor release, and its spec comes
  from `extract_tagged_openapi`. When no tag qualifies, the floor spec is HEAD's `frontend/openapi.json`.
- **The request check** is unchanged: the coverage test with `HASSETTE_CLIENT_OPENAPI` pointing at the
  floor spec.
- **The response check runs in the tool**, not the coverage test, because `nox -s client` runs the client's
  tests in an environment where `tools/` isn't importable. With `HASSETTE_CLIENT_OPENAPI` set, the coverage
  test also writes the operations the client calls to the JSON file named by `HASSETTE_CLIENT_OPERATIONS`:
  each `(method, template)` its recorded requests match in HEAD's `frontend/openapi.json` (matched against
  HEAD so the template strings are oasdiff's), and whether the method is in `STATUS_MODEL_503_METHODS`.
  The tool reads that file, runs `run_oasdiff` with HEAD's spec as base and the floor spec as revision,
  keeps findings in the blocking set (the build widens it, see Build's `FLOOR_BLOCKING_CHECK_IDS`), and then keeps only findings whose `operation` and `path`
  the client calls and whose status the client parses as a model: 2xx, plus 503 for
  `STATUS_MODEL_503_METHODS`. A 422 or other problem status is excluded because the client never parses
  those as the route's model.
- **Reading the status.** oasdiff 1.32.1 has no status field; it's in `text`, phrased two ways:
  - "from the response with the `200` status" (`response-required-property-removed`);
  - "became optional for the status `422`" (`response-property-became-optional`).

  The tool matches either order. A finding whose status can't be read fails the guard rather than being
  skipped.
- **No ignore file.** `run_oasdiff`'s `ignore_file` becomes `Path | None`, and `None` omits
  `--err-ignore`. `check_wire_compat.py`'s own runs keep passing `tools/wire_compat_ignore.txt`.
- **The guard's own failures** are the ones stated above the recommendation: `MIN_API_SCHEMA_VERSION`
  above `API_SCHEMA_VERSION` at HEAD, with D20's bump rule in the message.
- **CI.** In `tests.yml`'s `workspace-members` job, the checkout uses `fetch-depth: 0` on every run and
  the guard step drops its `release-please--` condition. The job also installs oasdiff the way the
  `frontend` job does. The comments on both steps are rewritten. The existing `tools/check_client_floor.py`
  path filter stays.
- **Tests use fixtures.** At merge no tag carries `API_SCHEMA_VERSION`, so the floor release is HEAD and
  the guard diffs HEAD against itself. The guard's tests build fixture tags and specs instead. One
  fixture is v0.55.0's committed `openapi.json`, against which the `GET /api/apps` 200 findings must block
  and its 422 findings must not. Another is a fixture spec where a client-parsed 200 field became
  optional, which must block. That is how this PR demonstrates the deciding factor.

**Ratified:** Chose a guard on every PR that diffs the client's operations against the floor tag's `openapi.json` (request checks plus reversed oasdiff blocking IDs, client-parsed statuses only, no ignore file), over release-PR-only checks, a live floor container, or request checks alone, so the v0.55.0 response break fails on the PR that causes it, accepting a spec diff on every PR.

### D23: Does an error from a missing route say the server may be older?

Background: `prior-art-skew-and-bodies.md` Q1, shape E. The server gives a missing route its own
problem codes (`not_found`, `method_not_allowed`), separate from `app_not_found` and its siblings. No
surveyed client does this; Docker does the server-side equivalent.

**Deciding factor:** HA and client library convention: raise what the server said, and document how to
read it.

A route miss under `/api` has two other causes besides skew:

- **A `base_url` with an extra `/api`.** Every request becomes `/api/api/...`, and the server answers
  each one with a `not_found` problem (`src/hassette/web/app.py` SPA convertor excludes `/api`;
  `web/errors.py:147` fallback codes). Paths outside `/api` get the SPA's `200 text/html`, which D18
  handles.
- **A misspelled action from untyped code.** D6 dropped the local check, so the typo reaches the server
  as an unmatched path.

Typed method names, CLI command typos and wrong keys/IDs can't trigger it. The client builds every
path itself, cyclopts rejects unknown commands locally, and a wrong key gets a resource-specific code
such as `app_not_found`.

| | A: Skew-only clause ("server may be older than hassette-client X.Y") | B: Clause naming both causes: "this server has no such endpoint: check base_url, or the server may be older than hassette-client X.Y"; `action()` errors also name the action | C: No hint; docs explain how to read the code |
|---|---|---|---|
| Points at skew when it's the cause | Yes | Yes | Only via docs |
| Misleading on a bad `base_url` (every call) or an action typo | Yes | No | No |
| New surface or state | None | None | None |
| Prior art | None client-side | None client-side | All surveyed clients |

`ResponseValidationError` never gets a direction hint under any option. Against a server at or above the
floor, D27's guard checks that every response field the client requires is still required and present,
so a missing required field isn't evidence of an older server. As built, the guard also catches a retyped or
newly nullable field (Build's `FLOOR_BLOCKING_CHECK_IDS`), but not a closed vocabulary that grew (D24's table lists those as `ResponseValidationError`), so a parse failure
points at drift in what a field holds, which a direction hint wouldn't explain either. (Restated when D20 was reopened: the earlier argument relied on
`check_wire_compat`'s adjacent-release chain, which `tools/wire_compat_ignore.txt` breaks.)

**Recommendation:** C, under the standards-first principle (see Summary). No surveyed client rewrites a
route miss into a skew hint. The standard is to raise what the server said and document how to read
it. The docs explain that `exc.problem.code` of `not_found`/`method_not_allowed` means "no such
endpoint", and they list the causes: an older server, a `base_url` with an extra path, or an action
name the server doesn't know.
**Pick B instead if** you'd rather put that guidance in the message than in the docs, and accept
behavior no other client has.
**Pick A instead if** a bad `base_url` is caught elsewhere first.
**Reversibility:** easy
**Ratified:** Switched from B to C under the standards-first principle: route-miss errors carry the server's message unchanged and the docs explain the `not_found`/`method_not_allowed` codes and their causes, over a message hint, to match every surveyed client, accepting that users must read the docs to connect a route miss to version skew.

### D24: How precisely is the compatibility promise stated?

Background: F22; `prior-art-skew-and-bodies.md` Q1 sections 3 and 5. The client pins `hassette-wire`
exactly, so an older client tolerates only what its wire already tolerates. FastAPI silently ignores
query parameters it doesn't know, so a newer client sending a new filter to an older server gets
unfiltered data back with no error. D20's `MIN_API_SCHEMA_VERSION` and D27's guard are what prevent that.
Reopened with D20: the promise it states changed shape.

**Deciding factor:** An integration author can tell, from the docs alone, what each side tolerates.

| | A: Table plus a per-method `.. versionadded::` on methods newer than the first transport release | B: Compatibility table on the docs page only (both directions), linking to `check_wire_compat` and D27's guard as the source of truth; nothing in `version.py` beyond `MIN_API_SCHEMA_VERSION`'s own docstring (CLAUDE.md, Internal Documentation); the docs explain `MIN_API_SCHEMA_VERSION`, `api_schema_version` and `check_server_version()` (D20, D25) | C: Keep the current "a newer server is supported" wording |
|---|---|---|---|
| Promise accurate in both directions | Yes | Yes | No |
| Author knows the oldest supported server | Yes | Yes (`MIN_API_SCHEMA_VERSION`, enforced by D27's guard) | No |
| Matches prior art | No: per-method markers stand in for per-command checks | GitHub REST's enumerated additive/breaking list, backed here by the oasdiff runs and D27's guard | n/a |
| Fits repo conventions | No: docs use mkdocstrings Google style (`mkdocs.yml:153`), which doesn't render the Sphinx directive | Yes | Yes |
| Effort | Docs plus a convention to establish | Docs | None |

The table's rows:

- new response field;
- new `Open*` value;
- new value in a closed field;
- new problem code;
- new route or action;
- new query parameter or request field;
- renamed, removed or retyped field.

Each row has an outcome for an older client, and for a newer client against a server whose
`api_schema_version` is at least `MIN_API_SCHEMA_VERSION`, per the brief's §5 table with D10 applied. Under
D27's guard, the "new response field", "new route" and "new query parameter" rows read "can't happen"
against such a server: the guard checks that routes, methods and parameters exist and that every response
field the client requires is present. It doesn't check what an existing parameter or field means. Under
D21 there is no unreadable-version case, so the table carries no precondition beyond the check passing.

**Recommendation:** B. A table backed by CI is the established precedent, and D27 makes the per-route
minimum exact.
**Pick A instead if** you want per-method markers too and are willing to establish a rendering
convention for them.
**Pick C instead if** you'd rather keep the docs short.
**Reversibility:** easy
**Ratified:** Chose a both-direction compatibility table on the docs page, backed by `check_wire_compat` and D27's guard and explaining `MIN_API_SCHEMA_VERSION`, `api_schema_version` and `check_server_version()`, over adding per-method `versionadded` markers or keeping the current wording, to make the promise accurate in both directions from the docs alone, accepting that per-method minimums live in CI rather than on each method.

## Assumed

- The issue body's Key Decisions stand, except the `retryable` attribute (reversed by D2), the per-call
  timeout (D5), the zero-exemption coverage rule (D12) and `server_is_newer()` (removed by D20). The ones that stand cover:
  - async aiohttp with a caller-owned session the client never creates or closes;
  - an explicit timeout on every request (D5) and `allow_redirects=False`;
  - no `Authorization` header when no token is configured;
  - exception resolution by problem `code`, then status family, then generic `HassetteHTTPError`;
  - `get_ready()`/`get_telemetry_status()` return their status model on 200 and 503, and every other
    503 raises;
  - lenient parsing via `hassette_wire.LENIENT_CONTEXT` on every parse;
  - `get_health()` exposes `version`;
  - a stable public `parse_response`;
  - one flat `HassetteClient` with one method per route;
  - an OpenAPI coverage test with no route exemptions except the ones D12 names;
  - dependency floors at or below HA's pins.

  Evidence: `gh issue view 2386`, "Key Decisions";
  `design/research/2026-10-02-hassette-client-transport/research.md`, "Decisions (2026-10-02)".
- Leniency uses spec 121's L2 shape: `X | UnknownValue` via `Open<TypeName>` aliases, with no `UNKNOWN`
  enum member. `SourceTier` and `LogLevel` are declared closed. Evidence: research.md Addendum
  2026-10-03; `design/specs/121-wire-lenient-unknown-enums/design.md` D1, D14.
- Methods and the coverage test ship in one PR. Evidence: issue #2386 body, "Methods and coverage test
  ship as a single PR".
- `tools/check_wire_compat.py` already compares the API against the last `v*` tag with oasdiff, in both
  skew directions, so CI already has tag-based schema access (D27's guard, D23). Evidence: `tools/check_wire_compat.py`;
  `design/research/2026-10-02-hassette-client-transport/research.md:68`.
- `POST /api/apps/{key}/{start|stop|reload}` answers only after the operation finishes. Evidence:
  `src/hassette/web/routes/apps.py`, `_run_app_action`.
- `POST /api/jobs/{id}/trigger` answers 202 right after dispatch. Evidence:
  `src/hassette/web/routes/scheduler.py:49-75`.
- `start`/`stop` converge on a target state; `reload` does not. Evidence: spec 113 brief citing
  `app_lifecycle_service.py:509-512, 663-665`.
- Problems are sent as `application/problem+json`; a missing route answers with problem code
  `not_found` or `method_not_allowed`. Evidence: `src/hassette/web/errors.py:32, 195`;
  `wire/src/hassette_wire/problems.py`.
- FastAPI ignores query parameters a route doesn't declare. Evidence: F16; `prior-art-skew-and-bodies.md`
  Q1.
- uvicorn decodes `%2F` before routing, and app keys can't contain `/`. Evidence: F7's probe;
  `routes/apps.py:37`.
- aiohttp's own retry covers only idempotent methods on a stale pooled connection, so a POST that hits
  one surfaces as a connection error. This is why D2's docs say a `HassetteConnectionError` on
  `action()`/`trigger_job` leaves the outcome unknown. Evidence: aiohttp 3.14.3 `client.py:256, 703, 859-870` (per
  `prior-art-retryable.md`).
- The HA integration maps errors by class and makes one attempt per action; HA's setup retry and
  coordinator polling do the retrying. Evidence: `design/specs/113-hacs-companion-integration/brief.md`; `prior-art-retryable.md`
  "What the HA Consumer Needs".
- aiohttp raises a plain `ValueError` for a header value containing `\r` or `\n` when the request is
  written; non-ASCII values pass. Evidence: aiohttp `http_writer.py:359`; probe against a local aiohttp
  server during the sketch comb.
- Every `v*` tag commits `frontend/openapi.json`, and hassette publishes a Docker image per release tag.
  Evidence: `tools/check_wire_compat.py` (`extract_tagged_openapi`); `.github/workflows/build_and_publish_image.yml`.
- HA 2026.9 pins `aiohttp==3.14.3` and `pydantic==2.13.4`. Evidence:
  `~/source/core/homeassistant/package_constraints.txt:9, 144`.

## Build

- [x] Implementation and tests committed (first build: `48131a39`, `a0391f27`)
- [x] Docs (first build)
- [x] Ship-time challenge (reopened D20, D21, D24, restated D23, added D25–D27)
- [x] Rework to the API schema floor committed
- [x] Docs reworked
- [x] Ship-time challenge on the rework (12 findings: 11 applied, 1 deferred as KI-001)

**Rework to the API schema floor.** The first build shipped a release-version floor. Every item below is
replaced, and none of the old floor may survive in code, tests or docs (D1's delete list points here):

- `client/src/hassette_client/version.py`: delete `MIN_SERVER_VERSION` and the `packaging` comparison. Add
  `MIN_API_SCHEMA_VERSION = 1` with the bump rule in its docstring (D20). `check_server_version` compares
  `health.api_schema_version` against it, so a pre-schema server's `0` raises, and it returns `None`
  (D21). Its docstring loses the PEP 440 and "unreadable version passes" text.
- `client/src/hassette_client/errors.py`: `UnsupportedServerVersionError` carries `server_version`,
  `api_schema_version` and `min_api_schema_version` instead of `min_version`, says to upgrade the hassette
  server or install an older hassette-client, and still round-trips through `copy`/`pickle` (D9).
- `client/src/hassette_client/__init__.py` (module docstring and exports) and `client.py`'s references:
  `MIN_SERVER_VERSION` becomes `MIN_API_SCHEMA_VERSION`.
- `client/pyproject.toml`: drop the `packaging` dependency and its mention in the floors comment; refresh
  `uv.lock`.
- `wire/src/hassette_wire/health.py`: add `API_SCHEMA_VERSION = 1` (re-exported from `hassette_wire`) and
  `SystemStatusResponse.api_schema_version: int = 0` (D25). `RuntimeQueryService.get_system_status()`
  (`src/hassette/core/runtime_query_service.py`), the one place the model is built, sets it from the
  constant, so the WebSocket status payload carries it too. Regenerate `frontend/openapi.json` and the
  frontend types, WS schemas included.
- D27's guard: `tools/check_client_floor.py`, the response check in
  `client/tests/test_openapi_coverage.py` (the operations file; its module docstring loses the release-PR
  wording),
  `run_oasdiff`'s optional ignore file, the CI changes, and the fixture-based tests, all as D27 lays out.
- Tests: rewrite `client/tests/test_version.py` and `tests/unit/tools/test_check_client_floor.py`; update
  `client/tests/test_errors.py` and `tests/integration/web_api/test_hassette_client.py` for the new
  exception attributes and the health field.
- `.claude/rules/web-api.md`: the release-PR paragraph becomes D20's bump rule (raise `API_SCHEMA_VERSION`
  and set `MIN_API_SCHEMA_VERSION` in the feature PR; D27's guard fails until it does).
- `docs/pages/web-ui/python-client.md` and `snippets/python_client_skew.py`: the version section becomes
  D24's both-direction table and explains `MIN_API_SCHEMA_VERSION`, `api_schema_version` and
  `check_server_version()` (a pre-schema server raises; no unchecked case). The CI paragraph says every
  PR, not every release. The snippet drops its second parse of `health.version`.

**Calls made during the build:** the first build's calls are unaffected by the rework. The rework's calls
come first.

- The bump rule's full statement, with why one raise per release is enough, lives once in the
  `MIN_API_SCHEMA_VERSION` docstring. A new path-scoped rule, `.claude/rules/client-schema-floor.md`
  (`client/**`, `wire/src/**`, `src/hassette/web/**`), points there; `web-api.md` keeps a one-line
  pointer. `web-api.md` alone loads only for server files, so a client edit would never see the rule.
- `list_release_tags` moved into `tools/check_wire_compat.py`, and `resolve_latest_release_tag` uses it, so
  both tools list tags one way. `schema_version_at` tests for the file with `git ls-tree --name-only`
  before `git show`, rather than matching git's stderr wording.
- The guard fails closed when oasdiff is missing from PATH or the coverage test wrote no operations, since
  either would otherwise let the response check pass without checking anything.
- v0.55.0's `openapi.json` is committed as a test fixture (`tests/unit/tools/fixtures/client_floor/`), so
  the deciding-factor test doesn't need tags, which the main suite's shallow checkout lacks.
- `UnsupportedServerVersionError`'s message says "reports no API schema" for schema `0` rather than "serves
  API schema 0".
- A build from main reports the schema of the latest bump, not of its own API: under the one-bump-per-release
  rule, API added after that bump and before the release isn't reflected, so the check is exact only for
  released servers. The docs say so. A per-PR bump would close the gap but can't be enforced while the floor
  is keyed on releases.
- The floor guard blocks on its own set, `FLOOR_BLOCKING_CHECK_IDS`: `check_wire_compat`'s two reversed IDs
  plus `response-property-type-changed`, `response-property-became-nullable` and
  `response-success-status-removed`, each verified against oasdiff 1.32.1 in the reversed direction. D27
  named only the shared two, but a retyped or nullable field breaks the client's parse exactly as a missing
  one does. Request bodies aren't compared; the docs say so.
- Tag-walk ordering and monotonicity are deferred as KI-001 (`known-issues.md`), with a tripwire: the tool
  fails if the floor walk reaches any tag that isn't a final `vX.Y.Z` release.
- The tool refuses a shallow or tagless checkout, and reads a tag as schema 0 only when `git ls-tree` shows
  the module absent there; any other git failure fails the check.
- `check_server_version` and `UnsupportedServerVersionError` keep their names (D20 names them); the
  function's docstring says "version" there means the API schema.

- The coverage test also checks, against the current API only, that every query parameter the server declares has a client filter, and that `CALLS` passes every keyword filter. Without the second check, D14's misnamed-filter check would pass vacuously for a filter no call sends.
- `HassetteConnectionError` for an `InvalidURL` says "the URL is invalid" without echoing it, because aiohttp's message is the raw URL, userinfo included (D15).
- `MAX_ERROR_BODY_BYTES = 4096` and `MAX_BODY_EXCERPT_BYTES = 200` (D16 left the values to the build). The excerpt is the first 200 bytes, decoded with replacement characters, so a multi-byte character cut at the boundary ends in U+FFFD. A body that isn't a parsed problem keeps its excerpt on `body_excerpt`; a malformed problem body does too.
- `DEFAULT_TIMEOUT_SECONDS` became `DEFAULT_REQUEST_TIMEOUT`, to match D5's parameter name.
- D10's open status fields use two new backing Literals, `AcceptedStatus` and `LivenessStatus`, unexported like the other `Open*` backing Literals.
- D11's required `LivenessResponse.status` trips `check_wire_compat`'s reversed run, so `tools/wire_compat_ignore.txt` gets one line. It isn't a real break, because every server serializes the old default. D27's guard doesn't read that file and doesn't need the line: it checks only statuses the client parses, against floor releases that post-date D11.
- `user:password@` in `base_url` isn't rejected or stripped. aiohttp turns it into Basic auth, and with a token set it raises `ValueError` on the first request (it won't send an `Authorization` header alongside URL credentials or a session-level `auth=`), so the docs say to leave it out and list the `ValueError` in the failure table. Rejecting it would have been a new argument check that no decision covers, and stripping it would silently drop credentials a user typed. Every message and log line still redacts it (D15), including the `ClientResponseError` path, whose aiohttp message carries the request URL.
- `noxfile.py`'s member floor run pins each direct dependency to its `>=` floor in an isolated, project-less environment (`floor_requirements()`), replacing `uv run --resolution lowest-direct`. Inside the workspace, `lowest-direct` resolves the root package's requirements too, so a member floor below the root's own floor (the client's `aiohttp` floor, say) would never be installed and the floor run would prove nothing. The parser handles exactly what the members declare today: a requirement with extras, an environment marker, or anything other than a single `>=` floor raises rather than being pinned wrongly. This also changes the existing `wire` floor job.
- D17's log lines have no tests that capture log output (the "No Log Capture Tests" invariant). The behavior around each fallback path is tested instead.

## Addendum

### 2026-10-08: the floor walk's pre-release tripwire is replaced by PEP 440 ordering (#2485)

The Build section's tripwire, which failed the floor check on reaching any tag that isn't a final
`vX.Y.Z` release, is gone. `list_release_tags` in `tools/check_wire_compat.py` now orders tags by PEP 440
and drops pre-release, dev-release and non-PEP 440 tags, so the floor walk never reaches one and its order
no longer depends on git's `versionsort.suffix`. KI-001 keeps only the still-open half: nothing asserts that
`API_SCHEMA_VERSION` never decreases toward newer tags.
