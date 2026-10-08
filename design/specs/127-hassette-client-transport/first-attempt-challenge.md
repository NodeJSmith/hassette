# Challenge Findings

**Format-version:** 4
**Target:** hassette-client (`git diff main...HEAD` in worktree 2386): client/src/hassette_client/, with the hassette_wire models and src/hassette/web routes it depends on
**Critics:** contract-caller, senior-engineer, operational-resilience
**Likely-invalid:** 1

## Finding 1: Findings converge on the class-level `retryable` flag

**Severity:** HIGH
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** Synthesis
**Converges:** Findings 3, 10, 11
**visibility:** presented
**disposition:** pending

**Why-it-matters:** All three critics reached the same point from different directions: `retryable` is a `ClassVar` on the exception class, but whether a retry is correct depends on the request and on the failure phase, and the class can see neither. Finding 3 covers the method (a timed-out `reload`/`trigger_job` is flagged retryable but replays its effect). Finding 11 covers the phase (a connect failure means the request was never sent, while a read failure means the outcome is unknown, and both raise the same class). Finding 10 covers the cause (a TLS-certificate or invalid-URL failure is flagged retryable but will never heal). Each finding proposes its own patch: a docstring, a `request_sent` attribute, a subclass or per-instance override. Should the flag mechanism itself be re-evaluated (what it promises, where its value comes from, whether one boolean can carry the decision at all) before patching each case? Which classes carry the flag was approved and is not reopened here. This is about what the flag means and how it is computed, which the user put in scope.

**Evidence:** errors.py:184-185 (`retryable: ClassVar[bool]`), errors.py:194, 203 (connection/timeout `retryable = True`); transport.py:91-94 (every `TimeoutError` and `aiohttp.ClientError` collapses into the two classes); client.py:424-431 (`trigger_job`, no caveat); routes/apps.py:228-241 (server answers only after the operation finishes).

**Design-challenge:** The flag is used as a retry predicate (docs snippet python_client_errors.py:35-38 loops on it), but it is only a property of the failure class. Is `retryable` meant to say "transient" or "safe to replay"? Either way, should the class be the thing that answers?

**Deciding-factor:** Whether callers are expected to drive retries from `exc.retryable` alone, without per-method knowledge.

**Criteria:**
| | A: re-evaluate the flag mechanism | B: keep it, fix findings individually |
|---|---|---|
| Respects the approved class/flag assignment | Puts how the value is derived up for review, though not which classes carry it | Fully |
| Number of separate patches | One rework covers 3, 10, 11 | Three independent patches (docs, new attribute, override) |
| Safety for a `while exc.retryable` caller | Can make the flag itself correct per request | Relies on callers reading per-method docs |
| Cost before first release of the client | Moderate; cheapest now (0.x, beta) | Low |
| New state or heuristics added | Possibly (per-request inputs) | Few (mostly documentation) |

**Options:**
- **A**: Re-evaluate the `retryable` mechanism before addressing Findings 3, 10 and 11 individually. Open questions: what the flag promises (transient vs replay-safe); whether it is per class or per instance; which inputs it may depend on (HTTP method, request-sent phase, error subtype, a server signal); whether a separate attribute should carry replay safety instead.
- **B** *(recommended)*: Keep the class-level `retryable` mechanism and address Findings 3, 10 and 11 individually.

**Recommendation:** B. The class flags were approved deliberately, and the HIGH member (Finding 3) can be fixed without adding state: say precisely what the flag promises and add per-method caveats. The other two members are MEDIUM, and each has a cheap local fix.
**Pick-instead-if:** A: you expect HA coordinators or retry wrappers to loop on `exc.retryable` without consulting per-method docs. In that case only a flag that is correct per request prevents double reloads and double job triggers, and 0.x is the cheapest time to change it.

## Finding 2: Findings converge on how the transport decides what a response body is

**Severity:** MEDIUM
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** Synthesis
**Converges:** Findings 12, 13
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The transport decides three things purely by attempting a parse: whether an error body is a hassette problem (`http_error`, transport.py:108-111), whether a 503 is the probe's status model or a failure (transport.py:98-102), and whether a 2xx is the expected model (transport.py:96-97). It never reads `Content-Type`, even though the server deliberately sends problems as `application/problem+json` (web/errors.py:32, 195). Finding 12 (a foreign 503 accepted as a "not ready" answer) and Finding 13 (an auth proxy's 200 HTML login page reported as a schema mismatch) are two symptoms of this one classification step. Should the classification be re-evaluated as a single rule before each symptom gets its own patch?

**Evidence:** transport.py:88-90 (only `Location` is read from headers), transport.py:96-103, 106-119; web/errors.py:32, 195 (`PROBLEM_MEDIA_TYPE`); routes/health.py:24-29 (ready 503 carries the model, not a problem).

**Design-challenge:** The server already labels what each body is. The client ignores that label and infers the body type from whichever model happens to validate.

**Deciding-factor:** Whether one rule should cover every body-classification decision the transport makes.

**Criteria:**
| | A: re-evaluate body classification | B: fix 12 and 13 separately |
|---|---|---|
| Patches needed | One rule for problem, model and foreign bodies | Two independent changes in the same function |
| Consistency across 2xx, 503 and error paths | Single decision point | Can diverge again |
| Risk of over-tightening (proxies that rewrite headers) | Must be weighed once, explicitly | Weighed separately per path |
| Effort | Small; all in transport.py | Small |

**Options:**
- **A** *(recommended)*: Re-evaluate how the transport classifies response bodies before addressing Findings 12 and 13 individually. Open questions: which signal decides problem vs model vs foreign body; what a body matching none of them raises; how much of a foreign body the resulting error keeps.
- **B**: Keep body-shape classification and address Findings 12 and 13 individually.

**Recommendation:** A. Both members sit in one function, and the server already emits a distinct signal for each kind of body, so one classification rule removes both symptoms.
**Pick-instead-if:** B: you'd rather not let a header (which proxies can rewrite) influence classification at all, and accept handling each symptom separately.

## Finding 3: `retryable=True` on timeouts and connection errors for non-idempotent POSTs, with a 10s default that makes slow actions time out routinely

**Severity:** HIGH
**Type:** Fragility
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller, senior-engineer, operational-resilience
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The server holds `POST /apps/{k}/reload` open until the reload, including `on_initialize()`, has finished. The client's default total timeout is 10s. A slow reload therefore succeeds on the server while the client raises `HassetteTimeoutError`, whose `retryable` docstring says "sending the same request again later may succeed". A caller that loops on `exc.retryable` reloads the app a second time, or fires `trigger_job` twice. The `action()` docstring and docs line 130 warn about reload, but `trigger_job` has no caveat. The shipped retry snippet loops on `retryable` (written for `start`, but trivially copied to `reload`). In this library the flag means "may succeed", not "safe to resend", and nothing in the API exposes the second meaning.

**Evidence:** errors.py:149-150, 184-185, 194, 203; transport.py:21, 84, 91-92; client.py:117-118, 133 (action caveat), client.py:424-431 (`trigger_job`, none); routes/apps.py:228-241 (`_run_app_action` awaits `operation()` before answering); docs/pages/web-ui/python-client.md:124, 130; docs/pages/web-ui/snippets/python_client_errors.py:28-38.

**Design-challenge:** `retryable` is a property of the (failure, request) pair, but it is stored on the failure class. Does it mean "transient" or "safe to replay"?

**Deciding-factor:** Preventing a duplicate side effect from a caller that trusts the flag, without adding new state.

**Criteria:**
| | A: redefine + per-method caveats | B: per-instance replay-safety attribute | C: longer default for POST actions |
|---|---|---|---|
| Stops a `while exc.retryable` loop from double-firing | No; depends on callers reading docs | Yes, if callers read the new attribute | Reduces how often it happens; doesn't stop it |
| New public surface or state | None | New attribute plus method-idempotency knowledge in the transport | Default value only |
| Respects the approved flag assignment | Yes | Yes (flag unchanged, new attribute alongside) | Yes |
| Effort | Small (errors.py, client.py, docs, snippet) | Medium | Small, but overlaps Finding 11 |

**Options:**
- **A** *(recommended)*: In errors.py and the docs, state that `retryable` means "transient: the failure may not recur" and that it ignores idempotency. Add an "outcome unknown, may repeat the effect" caveat to `trigger_job`, and to the snippet and its prose.
- **B**: Add a per-instance attribute (e.g. `safe_to_retry`) on timeout/connection errors, computed from the request's method/idempotency (and the request-sent phase from Finding 11).
- **C**: Raise the default timeout for the action and trigger POSTs, or require a per-call timeout for them.

**Recommendation:** A. It removes the contradiction between the flag's docstring and the action docs with no new state, and it is the minimum all three critics named. B is the real fix only if callers are expected to retry from the exception alone (see Finding 1).
**Pick-instead-if:** B: the primary consumer is an unattended HA coordinator that will retry generically on the exception. C: you see real reloads taking longer than 10s and want fewer unknown-outcome timeouts regardless of the retry semantics (combine with A).

## Finding 4: Lenient parsing only covers `Open*` fields; closed Literals fail hard and defaulted fields mask renames

**Severity:** HIGH
**Type:** Fragility
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** pending

**Why-it-matters:** `ActionResponse.status` and `JobTriggerResponse.status` are closed `Literal["accepted"]`, and `LivenessResponse.status` is closed `Literal["live"]`. Leniency attaches only to `LenientValue`/`Open*` annotations (wire/lenient.py:68-74). If a newer server adds a value (for example `"completed"` for actions), every older client's `action()` raises `ResponseValidationError` after the action has already run. Synthesis reproduced this: `status: literal_error`. That contradicts errors.py:209 ("unknown enum values never cause this"), the parse_response docstring (parsing.py:27-28: "an enum or `Literal` value this release doesn't know becomes UnknownValue"), and docs python-client.md:138. In the other direction, defaults absorb drift silently: `LivenessResponse` validates `{}` (reproduced: `status='live'`), so `get_liveness()` succeeds on any 200 JSON object, and `TelemetryStatusResponse` counters default to 0, so a renamed counter reads as "no drops".

**Evidence:** wire/src/hassette_wire/apps.py:78; wire/src/hassette_wire/telemetry.py:373-381, 394; wire/src/hassette_wire/health.py:45, 58-61; wire/src/hassette_wire/lenient.py:3-7, 68-74; errors.py:209; parsing.py:26-28; python-client.md:138.

**Design-challenge:** "Lenient" is a property of individual wire annotations that nothing audits. The client's docstrings promise leniency for every enum or Literal.

**Deciding-factor:** Making the documented leniency promise true, and keeping it true, rather than correct only for today's models.

**Criteria:**
| | A: open the closed Literals + audit test | B: narrow the docs to `Open*` fields |
|---|---|---|
| Old client survives a new `status` value | Yes | No |
| Promise in errors.py/parsing.py/docs accurate | Yes | Yes, after rewording |
| Guards future models | Yes (test walks response models) | No |
| Touches hassette-wire | Yes (three fields + one test) | No |

**Options:**
- **A** *(recommended)*: Make `ActionResponse.status`, `JobTriggerResponse.status` and `LivenessResponse.status` open (an `Open*` alias, or drop the single-value Literal). Add a wire/client test that walks every response model reachable from a `HassetteClient` return type and fails on any closed Literal/Enum. Review whether `LivenessResponse.status` should be required, so `{}` doesn't count as a liveness answer.
- **B**: Keep the fields closed and reword errors.py:209, parsing.py:27-28 and python-client.md:138 to say that only fields typed `Open*` tolerate new values.

**Recommendation:** A. The library's stated purpose is tolerating a newer server. A closed Literal on the action response is the most likely field to grow, and it fails after the side effect has already happened.
**Pick-instead-if:** B: you'd rather treat any change to these single-value status fields as a breaking server change that requires a client upgrade.

## Finding 5: `action()` rejects actions it doesn't know with a local `ValueError`, contradicting "every failure raises HassetteClientError" and blocking newer server actions

**Severity:** HIGH
**Type:** Fragility
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** pending

**Why-it-matters:** `action()` checks `action` against a compiled-in `APP_ACTIONS` and raises `ValueError`. That is not a `HassetteClientError`, but client.py:52 and errors.py:3-4 both claim every failure is one, so a caller catching `HassetteClientError` misses it. The check also means an older client can't drive an action a newer server adds, even though the response side (`ActionResponse.action: OpenAppAction`) was made open for exactly that case. The server already answers an unknown action path with a 404, and the signature's `AppAction` Literal already catches misuse statically. Note that python-client.md:120 does document the `ValueError`, and `path_segment` raises `ValueError` for `.`/`..` too (transport.py:130-131), so the "every failure" claim is false for more than this one check.

**Evidence:** client.py:40, 52, 126, 135-136, 140; errors.py:3-4; transport.py:122-132; python-client.md:120; routes/apps.py:327-403 (only the three action routes exist).

**Design-challenge:** The client decides an action is invalid from its own compiled enum instead of asking the server, which is the authority.

**Deciding-factor:** Letting the server decide what actions exist, while keeping the "every failure" claim honest.

**Criteria:**
| | A: drop the pre-check | B: keep check, raise a HassetteClientError subclass | C: keep ValueError, narrow the claim |
|---|---|---|---|
| Older client can drive a newer action | Yes (with a cast) | No | No |
| "Every failure is HassetteClientError" holds for actions | Yes | Yes | Claim reworded |
| Misuse caught without a round trip | Statically only | Yes | Yes |
| Code change | Deletion | New exception class | Docstrings only |

**Options:**
- **A** *(recommended)*: Remove the `APP_ACTIONS` pre-check and pass `action` through `path_segment()`, so an unknown action becomes the server's `NotFoundError`. Also narrow client.py:52/errors.py:3-4 to cover the remaining `path_segment` `ValueError` (argument errors).
- **B**: Keep the pre-check but raise a `HassetteClientError` subclass. Document that new actions need a client upgrade.
- **C**: Keep the `ValueError` (as the docs already say) and reword client.py:52 and errors.py:3-4 to "every failure from the network or server".

**Recommendation:** A. It deletes code, matches the open response type, and leaves the static Literal as the misuse guard. Either way, the "every failure" wording needs narrowing for `path_segment`.
**Pick-instead-if:** B: you want a runtime guard and a single catchable base for every error. C: you consider argument errors programmer bugs that should stay `ValueError` and don't care about older clients driving newer actions.

## Finding 6: Version-skew detection is one-directional, and `server_is_newer` can raise `PackageNotFoundError`

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller, senior-engineer
**visibility:** presented
**disposition:** pending

**Why-it-matters:** `server_is_newer` returns `False` both for "same version" and for "server older". Yet the client-newer direction is the one that fails. A route the older server lacks surfaces as a generic `NotFoundError` (`code=not_found`). A required field the older server doesn't send (e.g. `SystemStatusResponse.websocket_connected`) raises a `ResponseValidationError` with no hint about versions. An HACS integration updated ahead of the user's hassette server hits exactly this case, and the docs only discuss the newer-server case. Separately, `version(CLIENT_DISTRIBUTION)` raises `PackageNotFoundError` (not a `HassetteClientError`) when the package has no installed metadata, such as when vendored or run from a source tree.

**Evidence:** version.py:11-29 (no `PackageNotFoundError` handling; docstring "False if it's the same version or older"); wire/health.py:37-47 (required fields); python-client.md:136-155; client/tests/test_version.py (no older-server or missing-metadata case).

**Design-challenge:** The client infers compatibility from silence. A bare 404 can't tell "route missing on an older server" apart from a wrong path prefix.

**Deciding-factor:** Giving callers the direction of skew that actually produces errors.

**Criteria:**
| | A: tri-state comparison + guard metadata | B: keep bool, document + guard metadata |
|---|---|---|
| Caller can detect "server older" | Yes | Manually, by comparing versions themselves |
| API change | New function or return type | None |
| Covers the HACS-updated-first case | Yes | Docs only |
| Effort | Small | Smaller |

**Options:**
- **A** *(recommended)*: Add a comparison that reports newer/same/older (e.g. a `compare_server()` returning an enum, or a tri-state), return `None` on `PackageNotFoundError`, and document that an older server shows up as `NotFoundError`/`ResponseValidationError`.
- **B**: Keep `server_is_newer`, catch `PackageNotFoundError` → `None`, and document the older-server failure modes.

**Recommendation:** A. In lockstep releases the integration side usually upgrades first, so "server older" is the skew that produces errors, and the current API can't report it.
**Pick-instead-if:** B: you expect the client to be upgraded only alongside or after the server, as with the in-repo CLI.

## Finding 7: `path_segment` percent-encodes `/`, but the server decodes it before routing, so a key containing `/` reaches a different route

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** No
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** pending

**Why-it-matters:** `path_segment`'s docstring promises "a `/` or `?` in it can't change the route". For `/` that is false. uvicorn unquotes the request path (`path = unquote(raw_path)`) and Starlette routes on the decoded path. Synthesis reproduced this with a FastAPI probe: `GET /api/apps/foo%2Fconfig` matched the `/apps/{app_key}/config` route with `app_key="foo"`, and `/api/apps/a%2Fb` returned a 404 `not_found`. So `get_app("foo/config")` silently queries a different app's config route (then fails to parse as `AppSummary`), instead of raising the `InvalidAppKeyError` the docstrings promise. `?` is safe; it stays in the path as `%3F` → `?`. The server's key regex rejects `/` anyway, so no valid key can contain one.

**Evidence:** transport.py:122-132; client.py:107-108, 112, 127; routes/apps.py:37 (`_VALID_APP_KEY` excludes `/`), 94-96; .venv/.../uvicorn/protocols/http/h11_impl.py:199-200; synthesis probe output: `/api/apps/foo%2Fconfig 200 {"route":"config","key":"foo"}`.

**Design-challenge:** The quoting assumes the server routes on the raw path. It routes on the decoded one.

**Deciding-factor:** Making the docstring promise true without depending on server routing internals.

**Criteria:**
| | A: reject `/` locally | B: keep encoding, fix docs + test |
|---|---|---|
| Wrong-route requests possible | No | Yes |
| Docstring promise holds | Yes | Reworded |
| Consistent with server validity rules | Yes (server rejects `/` too) | N/A |
| Interacts with Finding 5 | Same exception choice as the `.`/`..` rejection | No |

**Options:**
- **A** *(recommended)*: Reject `/` in `path_segment` the same way `.`/`..` are rejected, fix the docstring, and add a real-server integration test for a key containing `/`.
- **B**: Keep encoding `/`, reword the docstring and the `InvalidAppKeyError` raise lists, and add the integration test to pin the behavior.

**Recommendation:** A. No valid app key can contain `/`, and a local rejection is the only way to prevent wrong-route requests under uvicorn's decoding.
**Pick-instead-if:** B: you expect string path params (e.g. `execution_id`) that legitimately contain `/` and need a different encoding strategy.

## Finding 8: HTTP and validation exceptions can't be copied or pickled

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** No
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Audience assumption: library consumers who copy, pickle or re-raise exceptions across processes or construct them in their own tests. `HassetteHTTPError.__init__` and `ResponseValidationError.__init__` take keyword-only arguments but pass a single message string to `Exception.__init__`, so `exc.args == (message,)` and reconstruction calls `cls(message)`. Synthesis reproduced it: both `copy.copy(exc)` and `pickle.loads(pickle.dumps(exc))` raise `TypeError: HassetteHTTPError.__init__() takes 1 positional argument but 2 were given`. That breaks `ProcessPoolExecutor`, multiprocessing, and task runners that ship exceptions between processes.

**Evidence:** errors.py:215-223, 229-243; synthesis reproduction (TypeError on copy and pickle).

**Design-challenge:** The exceptions implicitly assume they are only ever built by `http_error()`/`parse_response()` and never reconstructed.

**Deciding-factor:** Standard exception behavior for a published library, at minimal cost.

**Criteria:**
| | A: add `__reduce__` | B: declare constructors private, leave as is |
|---|---|---|
| copy/pickle work | Yes | No |
| Effort | A few lines + a round-trip test | Docs only |
| Public surface | Constructor stays as is | Constructor marked non-public |

**Options:**
- **A** *(recommended)*: Add `__reduce__` to `HassetteHTTPError` and `ResponseValidationError` that rebuilds from their keyword arguments, plus a copy/pickle round-trip test.
- **B**: Document that the exceptions are not reconstructible and that their constructors are not public API.

**Recommendation:** A. The fix is small, and a published exception type that breaks `copy.copy` will surprise users.
**Pick-instead-if:** B: you consider cross-process use out of audience for an HA/script client.

## Finding 9: "Never a raw aiohttp exception" is overstated; a closed session raises a raw `RuntimeError`

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** No
**Classification:** User-directed
**Raised-by:** senior-engineer, operational-resilience
**visibility:** presented
**disposition:** pending

**Why-it-matters:** `Transport.request` catches only `TimeoutError` and `aiohttp.ClientError`. On a closed session, aiohttp raises `RuntimeError("Session is closed")` (aiohttp/client.py:581), which escapes raw. The caller-owns-the-session design makes this likely: HA closes the shared session on shutdown or reload under a long-lived client. Malformed header values (e.g. a non-ASCII token) or odd URLs can also raise non-`ClientError` exceptions. errors.py:3-4 and client.py:52 promise that every failure is a `HassetteClientError`.

**Evidence:** transport.py:77-94; errors.py:3-4; client.py:52; .venv/.../aiohttp/client.py:581.

**Design-challenge:** Session ownership belongs to the caller, but a closed session is neither detected nor mapped.

**Deciding-factor:** Keeping the "every failure" contract true for the failure the session-ownership design makes most likely.

**Criteria:**
| | A: wrap `RuntimeError` from the session call | B: check `session.closed` up front | C: soften the claim |
|---|---|---|---|
| Closed session raises HassetteClientError | Yes | Yes (narrow race remains) | No |
| Adds a guard that inspects another component's state | No | Yes | No |
| Catches other unexpected errors | Only `RuntimeError` | No | N/A |
| Effort | Small | Small | Docstring |

**Options:**
- **A** *(recommended)*: Catch `RuntimeError` (and `ValueError` from header/URL construction) around the session call and re-raise as `HassetteConnectionError` (or a dedicated subclass), chaining the cause.
- **B**: Check `self.session.closed` before the request and raise `HassetteConnectionError`.
- **C**: Reword errors.py:3-4 and client.py:52 to name the exceptions that can escape.

**Recommendation:** A. It keeps the contract without inspecting the session's state, and it covers the race that B leaves open.
**Pick-instead-if:** B: you want a specific "session closed" message and accept the race. C: you'd rather surface caller misuse (closed session) as a programmer error.

## Finding 10: Permanent connection failures (TLS certificate, invalid URL, DNS typo) are mapped to the retryable connection error

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** No
**Classification:** User-directed
**Raised-by:** operational-resilience
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Every `aiohttp.ClientError` becomes `HassetteConnectionError` (`retryable = True`). That includes `InvalidURL` from a bad `base_url` (a `ClientError` subclass), `ClientConnectorCertificateError`, and DNS failures for a mistyped host. A coordinator that honours `retryable` retries a misconfiguration forever, and the user sees "connection failed" instead of "your certificate is wrong". The class-level flag is approved, but the flag's docstring ("may succeed if sent again later") is actively misleading for these subtypes. Unlike Finding 9, this is about classification, not escaping exceptions.

**Evidence:** transport.py:93-94; errors.py:188-194 (docstring lists "DNS or TLS failure" under the retryable class); errors.py:149-150, 185.

**Design-challenge:** Mapping every aiohttp subtype into one class throws away the difference between transient and permanent failures.

**Deciding-factor:** Whether to stop a generic retry loop from spinning on misconfiguration, or only to document it.

**Criteria:**
| | A: map permanent subtypes to a non-retryable class | B: document best-effort retryability |
|---|---|---|
| Retry loop stops on bad cert/URL | Yes | No |
| Touches the approved class/flag set | Adds a class (or per-instance override) | No |
| Message names the real cause | Yes | Unchanged (aiohttp text is included) |
| Effort | Small–medium | Docstring |

**Options:**
- **A**: Map `InvalidURL` and certificate/SSL verification errors to a non-retryable `HassetteConnectionError` subclass (or a per-instance override), keeping refused/reset/timeout retryable.
- **B** *(recommended)*: Keep the mapping and document on `HassetteConnectionError` and in the Retrying docs that its retryability is best-effort, that TLS and URL misconfiguration also land there, and that callers must bound their retries.

**Recommendation:** B. It respects the approved flag assignment and fixes the misleading wording. aiohttp's message, already included in `str(exc)`, names the cause. If Finding 1 is re-evaluated (option A), fold this into that work instead.
**Pick-instead-if:** A: unattended coordinators that retry without a bound are a primary audience.

## Finding 11: One total timeout with no per-call override, and connect-phase vs read-phase failures are collapsed

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** No
**Classification:** User-directed
**Raised-by:** operational-resilience
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The only timeout knob is the constructor's total `timeout`, applied to every call. Cheap probes (`get_liveness`) and long actions (`reload`) can't be tuned independently without a second client. `except TimeoutError` merges aiohttp's connect timeout with read timeouts, and `ClientConnectorError` (request never sent) merges with `ServerDisconnectedError` (outcome unknown). A connect-phase failure is always safe to retry, even for `reload`. A read-phase failure is not. The client discards exactly the information Finding 3's stronger fix needs.

**Evidence:** transport.py:21, 38, 84, 91-94; errors.py:188-203 ("may or may not have received" is true only because the two cases are merged).

**Design-challenge:** The transport knows which phase failed but doesn't pass it on.

**Deciding-factor:** Giving callers the one fact (was the request sent?) that makes a retry decision safe, while keeping the surface small.

**Criteria:**
| | A: per-call `timeout=` + `request_sent` attribute | B: per-call `timeout=` only | C: leave as is |
|---|---|---|---|
| Probes and actions tunable independently | Yes | Yes | No |
| Safe-retry signal for non-idempotent calls | Yes | No | No |
| New public surface | kwarg on methods + attribute | kwarg on methods | None |
| Effort | Medium | Small | None |

**Options:**
- **A**: Add a per-call `timeout=` override and a `request_sent: bool | None` attribute on connection/timeout errors, filled from the aiohttp exception subtype.
- **B** *(recommended)*: Add only the per-call `timeout=` override (on `action`, `trigger_job` at least), and leave the phase distinction to Finding 1/3's decision.
- **C**: Keep the single constructor timeout.

**Recommendation:** B. The timeout override is cheap and needs no further decision. `request_sent` is only worth adding if Finding 1 or 3 chooses a replay-safety signal, and then it is part of that design.
**Pick-instead-if:** A: Finding 3 option B or Finding 1 option A is chosen. C: you'd rather callers construct a second client for long actions.

## Finding 12: The 503 status-model fallback accepts any JSON body that happens to fit the model

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** No
**Classification:** User-directed
**Raised-by:** contract-caller, senior-engineer, operational-resilience
**visibility:** presented
**disposition:** pending

**Why-it-matters:** For `get_ready()` and `get_telemetry_status()`, the client treats a 503 as the route's answer whenever the body validates as the model. Lenient parsing turns any unknown `status` into `UnknownValue`, so `{"status": "<anything>", "ready": false}` from a gateway is accepted as an authoritative "not ready", and any 503 JSON with a `degraded` bool is accepted as a telemetry status. A false "not ready" is indistinguishable from a real one. All three critics rate the probability as low (`ReadinessResponse` needs two fields), and they disagree on whether to act. The server already distinguishes the two cases by media type.

**Evidence:** transport.py:96-103; wire/health.py:64-67; wire/telemetry.py:373-381; web/errors.py:32, 195; routes/health.py:24-29.

**Design-challenge:** The client infers server intent from whether the body parses, not from the label the server attaches.

**Deciding-factor:** Whether a low-probability false "not ready" is worth a one-line media-type check.

**Criteria:**
| | A: require non-problem JSON content type | B: accept and document the assumption |
|---|---|---|
| Foreign JSON 503 misread as status | Only if it also claims `application/json` | Possible |
| Effort | One condition | Comment |
| Risk from proxies that rewrite Content-Type | Small | None |

**Options:**
- **A** *(recommended)*: Parse a 503 as the status model only when its content type is JSON and not `application/problem+json`. Otherwise raise as usual.
- **B**: Leave the body-shape check and document the assumption in `status_model_on_503`'s docstring.

**Recommendation:** A, unless Finding 2 option A is chosen, in which case this is decided there. The check costs one condition, and the server already sends the signal.
**Pick-instead-if:** B: you've seen proxies in HA setups strip or rewrite `Content-Type` on 503s.

## Finding 13: A 2xx non-JSON body (an auth proxy's login page) raises an opaque `ResponseValidationError` that reads like version skew

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** No
**Classification:** User-directed
**Raised-by:** contract-caller, operational-resilience
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Audience assumption: deployments behind forward-auth proxies, which the library explicitly targets (RedirectError docs). Many such proxies answer non-browser clients with `200 text/html`. The client then raises `Response from GET /api/apps does not match ...: <body>: json_invalid` (reproduced by synthesis). It carries no status, content type or body excerpt. The class docstring frames this as "a field was renamed, retyped or removed, or the server isn't hassette", which points the user at a version problem. Auth-handling code keyed on `AuthenticationError`/`RedirectError` never triggers. Error statuses keep a 500-char excerpt; the 2xx path keeps nothing.

**Evidence:** transport.py:96-97; parsing.py:39-46 (`from None`, no values); errors.py:206-223, 251-255; synthesis reproduction.

**Design-challenge:** The redirect handling was designed for this proxy scenario, but its 200 variant gets no diagnosis.

**Deciding-factor:** Making the proxy-login-page case recognizable without leaking server payload values into messages.

**Criteria:**
| | A: content-type check → distinct problem entry | B: attach status/content_type/excerpt attributes |
|---|---|---|
| Recognizable as "not hassette" | Yes (message says not JSON + type) | Yes (via attributes) |
| Conflicts with the no-values rule in parsing.py | No | Excerpt needs a deliberate carve-out |
| Effort | Small | Small–medium |

**Options:**
- **A** *(recommended)*: Check `Content-Type` on a 2xx. When it isn't JSON, raise `ResponseValidationError` with a distinct entry such as `<body>: not_json (content-type text/html)`, and add `status`/`content_type` attributes.
- **B**: Add `status`, `content_type` and a bounded `body_excerpt` attribute to `ResponseValidationError` when raised from a response, keeping the message unchanged.

**Recommendation:** A. It names the cause in the message without echoing payload content, which respects the deliberate `from None` rule. Under Finding 2 option A, this is decided there.
**Pick-instead-if:** B: you want the excerpt available for debugging and accept the carve-out from the no-values rule.

## Finding 14: `create_session`'s cookie is silently dropped for IP-address hosts, and in HA it lands in a jar shared with every integration

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** No
**Classification:** User-directed
**Raised-by:** senior-engineer, operational-resilience
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Audience assumption: the documented HA usage passes `async_get_clientsession(hass)`, a session shared with every integration. The docstring promises the cookie is "stored in the session's cookie jar". Both critics guessed HA uses a `DummyCookieJar`. It doesn't (HA's `_async_create_clientsession` passes no `cookie_jar`). Their conclusion still holds through a different mechanism: aiohttp's default `CookieJar(unsafe=False)` rejects cookies from IP-address hosts. Synthesis verified that a cookie for `http://127.0.0.1:8126` gives a jar length of 0, while `http://hassette.local:8126` gives 1. The client's own docstring example uses `127.0.0.1`. So `create_session` returns 200 and stores nothing for the most common LAN setup. Where it does store a cookie, every other consumer of the shared session sends it to that host. No test covers `create_session`.

**Evidence:** client.py:44-48, 60, 163-173; ~/source/core/homeassistant/helpers/aiohttp_client.py:278-298 (no `cookie_jar` passed); synthesis probe (IP host jar length 0); tests/integration/web_api/test_hassette_client.py (no `create_session` test).

**Design-challenge:** What is `create_session` for in a client constructed with `token=`? Its effect depends on a jar the client neither owns nor inspects.

**Deciding-factor:** Not shipping a method whose documented effect silently fails in the headline deployment.

**Criteria:**
| | A: document the jar requirement + test | B: remove `create_session` |
|---|---|---|
| Silent no-op on IP hosts | Documented, still possible | Gone |
| Covers every route (OpenAPI coverage test) | Yes | Needs an explicit exclusion |
| Approved method list | Unchanged | Changes it |
| Effort | Small | Small + coverage-test change |

**Options:**
- **A** *(recommended)*: Document that the cookie needs a session whose jar accepts it (`CookieJar(unsafe=True)` for IP hosts) and that it isn't suitable for HA's shared session. Add a test with the default jar against an IP host.
- **B**: Drop `create_session`, and exclude the route from the coverage test as browser-only.

**Recommendation:** A. The one-method-per-route list is approved, and the defect is the undocumented precondition, not the method's existence.
**Pick-instead-if:** B: you find no non-browser use for a cookie session in a token-configured client.

## Finding 15: One malformed element fails an entire list response

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** No
**Classification:** User-directed
**Raised-by:** senior-engineer
**visibility:** presented
**disposition:** pending

**Why-it-matters:** List methods (`get_recent_logs`, `get_executions`, `get_jobs`, etc.) parse as `list[Model]`. Leniency is per field, so a single element with a retyped or missing field makes the whole call raise `ResponseValidationError`, and the caller gets no data. For an HA entity polling telemetry, one odd row blanks the entity.

**Evidence:** client.py:206, 236, 284, 309, 326, 372, 383, 394, 422; parsing.py:44-50.

**Design-challenge:** If leniency is the policy, why is it per field and never per element?

**Deciding-factor:** Whether partial data is ever preferable to a loud failure for these callers.

**Criteria:**
| | A: accept and document | B: opt-in partial mode |
|---|---|---|
| Caller gets data despite one bad row | No | Yes, when opted in |
| New surface | None | Flag/return shape on list methods |
| Masks real schema drift | No | Risk, unless failures are reported |
| Effort | Docs | Medium |

**Options:**
- **A** *(recommended)*: Keep whole-list validation and document in the class docstring/docs that one bad element fails the call.
- **B**: Add an opt-in partial mode that drops invalid elements and reports how many were dropped.

**Recommendation:** A. Silently dropped rows are worse than a loud failure for a typed client, and an element-level failure means real schema drift (unknown fields and values are already absorbed).
**Pick-instead-if:** B: dashboard or HA-entity consumers report blanked entities from single bad rows in practice.

## Finding 16: The OpenAPI coverage test proves route coverage, not query-parameter or response-model correctness

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** No
**Classification:** User-directed
**Raised-by:** senior-engineer
**visibility:** presented
**disposition:** pending

**Why-it-matters:** `test_every_operation_has_a_client_method` matches only (method, path template). It never checks query parameter names, and FastAPI silently ignores unknown query parameters. A typo like `app=` instead of `app_key=` would pass the test and also do nothing in production (the filter is just not applied). The canned `{}` body with suppressed `HassetteClientError` means response models are never compared with the operation's declared schema. The real-server integration tests cover 7 of ~29 methods and no filters.

**Evidence:** client/tests/test_openapi_coverage.py:93-120; client/tests/fake_server.py; tests/integration/web_api/test_hassette_client.py:52-104.

**Design-challenge:** The test's name and placement suggest it proves that each method calls its route correctly. It only proves that each route is reached.

**Deciding-factor:** Catching silent filter typos cheaply, since the OpenAPI document is already loaded.

**Criteria:**
| | A: assert query keys + response `$ref` | B: query keys only | C: leave as is |
|---|---|---|---|
| Catches misnamed filters | Yes | Yes | No |
| Catches wrong response model | Yes | No | No |
| Effort | Small–medium (unwrap `list[...]`/`X | None`) | Small | None |

**Options:**
- **A** *(recommended)*: Record query keys in the fake server and assert they're a subset of the operation's declared parameters. Also assert that the response schema `$ref` matches the model each method parses (unwrapping list/optional).
- **B**: Add only the query-parameter assertion.
- **C**: Keep the test as is.

**Recommendation:** A. FastAPI ignores unknown parameters, so nothing else catches a misnamed filter, and the response check reuses the same loaded document.
**Pick-instead-if:** B: unwrapping `list[...]`/`Execution | None` against `anyOf`/`items` schemas turns out fiddly.

## Finding 17: Exception messages carry a non-problem body excerpt and the full `base_url`

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** No
**Classification:** User-directed
**Raised-by:** senior-engineer
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Audience assumption: logs shipped off-box or a shared HA install. For a solo, personal-data deployment, this matters less. `HassetteHTTPError` puts up to 500 chars of an arbitrary non-problem body (such as a forward-auth login page, which can embed return URLs or session identifiers) into `str(exc)`, which usually lands in logs. Timeout and connection messages include the full `base_url`, so userinfo in the URL is logged too. This is inconsistent with the deliberate `from None` no-values rule for `ResponseValidationError`.

**Evidence:** errors.py:158-159, 240-243; transport.py:92, 94; parsing.py:46-47 (no-values rationale).

**Design-challenge:** Is the exception message a log line or a diagnostic payload?

**Deciding-factor:** Applying the existing no-payload-in-messages rule consistently.

**Criteria:**
| | A: excerpt on attribute, strip userinfo | B: leave as is |
|---|---|---|
| Payload content in logs by default | No | Yes |
| Diagnostic value | Kept (attribute) | Kept (message) |
| Consistent with parsing.py's rule | Yes | No |
| Effort | Small | None |

**Options:**
- **A** *(recommended)*: Keep the body excerpt in `detail`/an attribute but leave non-problem bodies out of the message, and strip userinfo from `base_url` in transport messages.
- **B**: Keep the current messages.

**Recommendation:** A. The library already decided that server payloads don't belong in exception text, and this applies that decision to the other path.
**Pick-instead-if:** B: you value one-glance diagnosis in a terminal over log hygiene for this audience.

## Finding 18: Response bodies are read unbounded

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** No
**Classification:** User-directed
**Raised-by:** senior-engineer, operational-resilience
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Audience assumption: the client runs on a small HA host against a possibly proxied endpoint. On a trusted LAN this is mostly irrelevant. `await response.read()` buffers the whole body, bounded only by the 10s total timeout, which on a LAN can be hundreds of MB. `get_recent_logs(limit=None)`, `get_executions` and `get_app_source` are sized by the server. An error body is also read in full before the 500-char slice.

**Evidence:** transport.py:88; errors.py:240; client.py:175-206.

**Design-challenge:** Memory use is bounded by bandwidth × timeout, not by anything the caller sets.

**Deciding-factor:** Whether the HA-process memory risk justifies a cap and a new error.

**Criteria:**
| | A: accept and document | B: cap error bodies only | C: `max_response_bytes` cap |
|---|---|---|---|
| Protects HA process from huge bodies | No | Partly | Yes |
| New surface | None | None | Option + new exception |
| Effort | Docs | Small | Medium (streaming read) |

**Options:**
- **A** *(recommended)*: Accept it and document that list endpoints should be called with `limit=` on constrained hosts.
- **B**: Read error bodies capped at a few KB, since only 500 chars are kept.
- **C**: Add a `max_response_bytes` cap with a streamed read and a dedicated error.

**Recommendation:** A. Both critics flagged the audience assumption, and the server is the user's own hassette. A cap adds surface for a risk that is low in the stated deployment.
**Pick-instead-if:** B: you want the cheap win on proxy error pages. C: the client is expected to talk to untrusted or proxied servers from Raspberry Pi-class hosts.

## Finding 19: Silent recovery paths, `Retry-After` dropped, and the retry snippet has no backoff

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** No
**Classification:** User-directed
**Raised-by:** operational-resilience
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Audience assumption: the caller is an unattended HA coordinator without a debugger. `client/src` has no logger. Most failures raise, which is fine, but two recovery paths swallow without a signal: the 503 status-model fallback (transport.py:101) and the problem-body parse fallback (transport.py:110-111). Response headers other than `Location` are dropped, so a proxy's `Retry-After` is lost, and the server sends none. The documented retry snippet sleeps a fixed 5s with no backoff or jitter, so N callers retrying on a server restart hit it in lockstep.

**Evidence:** transport.py:88-90, 101-102, 108-111; docs/pages/web-ui/snippets/python_client_errors.py:28-38; grep: no `getLogger` in client/src.

**Design-challenge:** The exception text is the only diagnostic artifact, and the snippet teaches the simplest possible retry loop.

**Deciding-factor:** Cheap observability on the two silent paths and a snippet that is safe to copy, without growing the error API.

**Criteria:**
| | A: DEBUG logs + backoff snippet | B: A + `retry_after` attribute | C: leave as is |
|---|---|---|---|
| Silent paths observable | Yes (DEBUG) | Yes | No |
| Honours proxy `Retry-After` | No | Yes | No |
| New public surface | None | One attribute | None |
| Effort | Small | Small | None |

**Options:**
- **A** *(recommended)*: Add a module `getLogger(__name__)` with DEBUG logs on the two fallback paths (and per-request outcome), and show exponential backoff with jitter in the snippet.
- **B**: Do A and also expose `retry_after: float | None` on `HassetteHTTPError` from the response header.
- **C**: Keep as is.

**Recommendation:** A. It closes the dark paths per the logging rule (library code: `getLogger` only), and it fixes the copy-paste hazard at no API cost.
**Pick-instead-if:** B: proxies in front of hassette in your deployments actually send `Retry-After`, or the server is going to start sending it.

## Finding 20: The problem code wins over the status unchecked, so the exception class can contradict `.status`

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** No
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** pending

**Why-it-matters:** `error_class_for` returns the code's class without checking that the response status matches it. If a future server changes a code's status (which problems.py:12-14 allows as a flagged breaking change), or a proxy rewrites the status while forwarding hassette's body, an old client raises e.g. `NotFoundError` with `.status == 409`, and the class-level `retryable` is wrong for the real status. This is speculative: today's mapping is test-enforced against the server's declared statuses (test_openapi_coverage.py:122-131 asserts each code class subclasses its status family's class).

**Evidence:** errors.py:376-386; wire/problems.py:12-14; client/tests/test_openapi_coverage.py:122-131.

**Design-challenge:** The class hierarchy encodes status, but the resolution doesn't enforce that encoding at runtime.

**Deciding-factor:** Whether to defend at runtime against a mismatch that current tests prevent for the current server.

**Criteria:**
| | A: fall back to status on mismatch | B: accept |
|---|---|---|
| Protects old client from a re-statused code | Yes | No |
| Complexity | A family check in `error_class_for` | None |
| Scenario likelihood | Low (breaking change or odd proxy) | Low |

**Options:**
- **A**: In `error_class_for`, ignore the code when the status isn't in the code class's status family, and fall back to status resolution.
- **B** *(recommended)*: Accept it. Current tests already enforce the mapping, and a re-statused code is a declared breaking change.

**Recommendation:** B. The scenario needs a deliberate breaking server change or an unusual proxy, and the existing test already pins the pairing for the current server.
**Pick-instead-if:** A: you expect clients to lag servers across breaking releases (HA integrations pinned to an older client).

## Finding 21: `parse_response` is promised stable, but its error surface exposes pydantic's error type names and `repr()` of generic types

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** No
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Audience assumption: open-source library with external consumers. parsing.py:26 calls `parse_response` "a stable public entry point". `ResponseValidationError.problems` entries are built from pydantic's `loc` and `type` strings, which pydantic doesn't version as stable, across a `pydantic>=2.7` floor spanning many releases. `.model` uses `repr()` for generic types such as `list[Execution]` and `Execution | None`. Callers matching on these break on dependency upgrades.

**Evidence:** parsing.py:26-28, 55-61; errors.py:215-223; client/pyproject.toml:22.

**Design-challenge:** "Stable" isn't scoped, so it implicitly covers strings the library doesn't control.

**Deciding-factor:** Scoping the stability promise to what the library actually controls.

**Criteria:**
| | A: document `problems`/`model` as human-readable | B: normalize to library-owned strings |
|---|---|---|
| Matches what's actually stable | Yes | Yes |
| Effort | Docstrings | Mapping layer over pydantic error types |
| New maintenance surface | None | Ongoing |

**Options:**
- **A** *(recommended)*: Document that the stable contract is "returns the model or raises `ResponseValidationError`", and that `problems` and `model` are human-readable diagnostics, not for matching.
- **B**: Normalize `problems`/`model` into library-owned, versioned strings.

**Recommendation:** A. It's a docstring change that makes the promise true, and nobody has asked to match on these strings.
**Pick-instead-if:** B: you want callers to branch programmatically on the kind of validation failure.

## Finding 22: The exact `hassette-wire==X` pin limits what "a newer server is supported" can mean

**Severity:** TENSION
**Type:** Approach-later
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The client pins `hassette-wire` exactly to its own version, and all leniency lives in wire. So "a newer server is supported" (version.py:12) holds only for changes the pinned wire already tolerates: additive fields and values in `Open*` fields. It doesn't hold for new routes, new required request shapes, or newly required response fields. Consumers can't upgrade wire independently. The lockstep pin is deliberate. The tension is how much the docs promise.

**Evidence:** client/pyproject.toml:19; version.py:11-14; python-client.md:136-147.

**Design-challenge:** The leniency story implies broader forward compatibility than the exact pin allows.

**Side-a:** Keep the lockstep pin and the current docs. python-client.md:147 already says renamed, removed or retyped fields raise. One wire definition per release is the reason hassette-wire exists.

**Side-b:** Keep the pin, but spell out in version.py and the docs exactly which server changes an older client tolerates (new fields, new `Open*` values) and which need a client upgrade (new routes, new actions, new required fields).

**Deciding-factor:** Whether the current docs could lead an integration author to expect an old client to keep working against arbitrary newer servers.

**Criteria:**
| | Side A | Side B |
|---|---|---|
| Accuracy of the forward-compat promise | Mostly accurate; routes/actions unstated | Explicit |
| Effort | None | A short docs paragraph |
| Interacts with Findings 4 and 5 | Their outcomes may still need doc changes | Natural home for those outcomes |

**Pick-instead-if:** Side A: Findings 4 and 5 are fixed so that the remaining gaps (new routes) are self-evident. Side B: integration authors are the primary audience and need a precise compatibility statement.

## Likely Invalid

### LI-1: Dependency floors rest on an unverifiable external claim
**Original-severity:** MEDIUM
**Raised-by:** senior-engineer
**Claimed:** The pyproject comment "HA 2026.9 pins aiohttp==3.14.3, pydantic==2.13.4" can't be verified from the repo and will rot. Floors are tested only on Python 3.11, so a floor problem on 3.14 is uncovered.
**Actually:** The local HA core checkout at tag 2026.9.4 has `homeassistant/package_constraints.txt:9` `aiohttp==3.14.3`, `:144` `pydantic==2.13.4` and `:52` `packaging>=23.1`, exactly what client/pyproject.toml:14-15 states. The comment names a specific HA release, so it records a dated fact rather than a moving target.
**Why-invalid:** The finding's central premise, that the justification is unverifiable, is contradicted by the pinned constraints file. "Floors are lower than needed" describes the comment's stated, deliberate choice to stay at or below HA's pins, not a defect. The secondary remark that floors run only on the oldest Python is a test-matrix observation; synthesis did not verify whether the floor set can be installed on 3.14, and that remark alone doesn't carry the finding.
