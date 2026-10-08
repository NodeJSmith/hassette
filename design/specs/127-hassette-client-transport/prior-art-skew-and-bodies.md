---
topic: "How client libraries signal client/server version skew, and how typed HTTP clients classify response bodies, applied to hassette-client"
date: 2026-10-07
status: Draft
---

# Prior Art: Version-Skew Signaling and Response-Body Classification, Applied to hassette-client

Two questions from the first-attempt challenge (`first-attempt-challenge.md`):

- **Q1** covers Findings 6 and 22: which direction of skew to report, in what shape, and what the client promises about forward compatibility.
- **Q2** covers Findings 2, 12, 13 and part of 17: how the transport decides whether a body is a problem, the expected model, or something that isn't hassette.

## Bottom line

**Q1.** Replace `server_is_newer() -> bool | None` with a function that returns a four-member enum: `SAME`, `SERVER_NEWER`, `SERVER_OLDER`, `UNKNOWN`. Read the client's version from a constant that release-please rewrites, not from `importlib.metadata`.

- Keep the minimum-version floor in the consumer, as spec 114 decided. Extend its rule: using a new route or parameter also means bumping `MIN_HASSETTE_VERSION`.
- Add a "may be older than this client" hint only where the server's own signal supports it. That is a 404 with the route-miss code `not_found`, or a 405 `method_not_allowed`. `ResponseValidationError` gets no direction claim.
- Replace "a newer server is supported" with a two-direction table of what each side tolerates. It must name the silent failure: an older server ignores a query parameter it doesn't know.
- In HA, a server below the floor should raise `ConfigEntryNotReady`, plus a non-fixable repair issue if v0.1 allows one. That is what zwave_js, matter and music_assistant do. A newer server gets one log warning.

**Q2.** Classify by `Content-Type` first, and use parsing only to confirm. The server already labels every body: problems are `application/problem+json`, and models, including the two probe 503s, are `application/json`.

- A problem is accepted only from `application/problem+json`.
- A probe's 503 model is accepted only from non-problem JSON.
- A 2xx that isn't JSON raises `ResponseValidationError` with a distinct entry, plus `status` and `content_type` attributes. It no longer reads like a renamed field.
- A missing `Content-Type` falls back to today's parse attempt, which RFC 9110 permits. This is the only place the client sniffs.
- A foreign body is kept as a bounded excerpt on an attribute and never goes into `str(exc)`. This follows the frenck libraries (adguardhome, wled), and it resolves the body half of Finding 17.

---

# Q1. Version-skew signaling

## The problem

Client and server release in lockstep, but they're upgraded separately. The HACS integration usually updates first, so the client is often newer than the server. That is the direction that fails, and today's API can't report it:

| Skew | What the client sees today | Signal to the caller |
|---|---|---|
| Server newer | Unknown fields are ignored. New `Open*` values become `UnknownValue`. | `server_is_newer() → True` |
| Same version | Nothing | `False` |
| Server older, method's route missing | `NotFoundError`, code `not_found` | `False`, the same as "same version" |
| Server older, new query parameter | **The server ignores the parameter and returns unfiltered data.** | None. This is a silent wrong answer. |
| Server older, new required response field | `ResponseValidationError` | None. In practice CI blocks this case (see below). |
| No installed client metadata | `PackageNotFoundError` is raised, which is not a `HassetteClientError` | Nothing |

## How we do it today

- **`version.py`** (b753b2c5): `Version(health.version) > Version(version("hassette-client"))`. It returns `None` only on `InvalidVersion`. `importlib.metadata.version` raises `PackageNotFoundError` when the package is vendored or run from a source tree without metadata.
- **The server's version signal.** `SystemStatusResponse.version: str = ""` (`wire/src/hassette_wire/health.py:45`). The server may send `"unknown"` (`src/hassette/utils/version_utils.py:5-14`). `/api/health` requires auth.
- **Route-miss 404s have their own code.**
  - Every unknown `/api/...` path reaches FastAPI's router 404, because `SpaPathConvertor` excludes the API prefix (`src/hassette/web/app.py:62-67`).
  - That 404 becomes a problem with code `not_found` (`FALLBACK_CODES`, `src/hassette/web/errors.py:147`).
  - Route-level "missing thing" errors use specific codes instead: `app_not_found`, `instance_not_found`, `source_not_found`.
  - So `code == not_found` on an `/api` path already means "this server has no such endpoint". The client's `GENERIC_CODES` treats it as plain status today.
- **CI already blocks most response-shape skew in both directions** (`tools/check_wire_compat.py:5-22, 54-68`).
  - The reversed run (new client, old server) blocks a response field that is newly required or that changed from optional to required.
  - The forward run (old client, new server) blocks every ERR-level break except added enum values.
  - Both can be overridden through `tools/wire_compat_ignore.txt`. Today that file holds only 422-shape entries.
  - The reversed run deliberately does not block *new endpoints*. A new route therefore isn't guarded in the new-client direction, and neither is a new optional query parameter.
- **Request models accept extra fields.** No `extra=` config appears anywhere in `wire/src/hassette_wire/`, so pydantic's default `ignore` applies. FastAPI also ignores query parameters a route doesn't declare (Supported: this is FastAPI's documented default, and hassette doesn't override it). An older server therefore accepts a newer client's extra parameter and drops it without saying so.
- **Prior decisions.**
  - Spec 114 (`brief.md:131-140`): a floor plus a warning, with no ceiling. The integration owns `MIN_HASSETTE_VERSION`. Wire fields added after the first release must be optional. Min/max schema negotiation is out of scope (`brief.md:252-254`).
  - Spec 113 (`brief.md:143-145`): the config flow checks `GET /api/health` and reports `unsupported_version` below the floor. The check is repeated at setup, not on every poll. Repair issues are out of scope for v0.1 (`:178`).

## Patterns found

### Pattern 1: A handshake with a negotiated schema version, failing in either direction

**Used by**: zwave-js-server-python, music-assistant-client, Kafka ApiVersions (KIP-35), Docker Engine API.

**How it works**: The server advertises a range (`min_schema_version`, `max_schema_version`), and the client checks it against its own range at connect.

- **zwave-js** fails when the ranges don't overlap, and otherwise downgrades `schema_version` to the server's maximum.
- **music-assistant** raises when `min_supported_schema_version > API_SCHEMA_VERSION`. The message names both remedies: "update the Music Assistant client to a more recent version or downgrade the server".
- **Docker** enforces the range on the server. The daemon answers "client version X is too new. Maximum supported API version is Y" (a 400). Every response carries an `Api-Version` header.
- **Kafka** negotiates per API key: the broker returns min/max for each operation.

**Strengths**: It detects skew in both directions before any real call is made. The compared quantity is a small API or schema number, not the product release, so a release that doesn't change the wire doesn't count as skew.

**Weaknesses**: It needs server cooperation (a published range), a connect step, and a schema number someone has to maintain. Spec 114 deferred this pattern explicitly. hassette-client is stateless per request and has no connect step.

**Example**: `zwave_js_server/client.py` (connect, ~174-187), `music_assistant_client/client.py` (~279-289), `moby/moby daemon/server/middleware/version.go`.

### Pattern 2: Per-operation minimum version, checked before sending

**Used by**: zwave-js (`send_command(..., require_schema=N)`), python-matter-server (`_prepare_message` raises `ServerVersionTooOld`), music-assistant (`require_schema=33`), aioesphomeapi (`MIN_VERSION_PROXY_ACK = APIVersion(1, 16)` and inline `if api_version < APIVersion(1, 5)` fallbacks), Kubernetes client-go discovery (`ServerSupportsVersion`, `IsResourceEnabled`).

**How it works**: Each command declares the oldest server that supports it. The client knows the server's version from the handshake and raises a typed "server too old" error before sending, naming the version required ("Update the Matter Server to a version that supports at least api schema N"). aioesphomeapi goes further: it degrades, for example by building `device_capabilities` from `device_info` on servers older than 1.15.

**Strengths**: The client-newer direction becomes a precise, typed error instead of a generic 404. This is the only surveyed pattern that turns "route missing" into "server too old for *this* call".

**Weaknesses**: It needs a per-method `since` table, kept accurate by hand or derived from OpenAPI history. It also needs the server version cached in the client, and hassette-client holds no such state. aioesphomeapi's `_supports_proxy_ack` treats an unknown version as new, a fail-open choice the docs don't call out.

**Example**: https://github.com/esphome/aioesphomeapi/blob/main/aioesphomeapi/client.py, `matter_server/client/client.py`.

### Pattern 3: A direction-bearing exception, used at setup

**Used by**: python-matter-server as HA uses it (`InvalidServerVersion`, with subclasses `ServerVersionTooOld` and `ServerVersionTooNew`), zwave-js (`InvalidServerVersion` with `server_version`, `server_max_schema_version`, `required_schema_version`), aiohue (`require_version()` raising `BridgeSoftwareOutdated`, paired with a bool `check_version()`), python-wled (`WLEDUnsupportedVersionError`).

**How it works**: The library raises one class the integration can catch. The base class is for "any mismatch", and the subclasses carry the direction. HA's matter integration branches on `isinstance(err, ServerVersionTooOld)` and `ServerVersionTooNew` to pick a repair-issue text: "update the Matter Server" or "update Home Assistant or downgrade the Matter Server" (`~/source/core/homeassistant/components/matter/__init__.py:100-121`, `strings.json:748-755`).

**Strengths**: The direction is typed, the fields are structured, and it maps straight onto HA's setup exceptions.

**Weaknesses**: zwave-js and music-assistant use a single class with no direction. The zwave-js message says "update the server" even when the client is the side that's too old, which is the conflation hassette's bool has.

### Pattern 4: An advisory warning in either direction

**Used by**: kubectl (`getVersionSkewWarning` in `pkg/cmd/version/skew_warning.go`, with `supportedMinorVersionSkew = 1`).

**How it works**: It takes `math.Abs` of the minor difference and warns when the difference exceeds the stated policy: "version difference between client (%d.%d) and server (%d.%d) exceeds the supported minor version skew of +/-1". It returns a string, not a bool or an exception, and it enforces nothing.

**Strengths**: It handles both directions with one comparison, and the tolerance is a named constant with a published policy (https://kubernetes.io/releases/version-skew-policy/).

**Weaknesses**: It warns on the product version, so it can't say which feature breaks.

### Pattern 5: A stated, enumerated compatibility contract

**Used by**: GitHub REST (`X-GitHub-Api-Version`), Stripe (version pinned per request).

**How it works**: The docs list which changes are additive and which are breaking. GitHub's list of additive changes: a new operation, an optional parameter, a response field, an enum value. Breaking changes include a new required parameter or a removal. Stripe solves skew by having the server serve the client's pinned version.

**Strengths**: This is the most precise forward-compat statement found. Callers know exactly what an older client tolerates.

**Weaknesses**: GitHub and Stripe back the promise with server-side versioning that hassette doesn't have. Without it, a precise list is still worth publishing, but CI has to back it (hassette's oasdiff runs).

**Example**: https://docs.github.com/en/rest/about-the-rest-api/api-versions, https://docs.stripe.com/api/versioning

### Not found: annotating a 404 or a validation error with skew information

No surveyed client library rewrites a generic 404 or a parse failure to say "this may be version skew". Skew is either detected up front (Patterns 1 and 2) or produced by the server (Docker's daemon error). An annotation on the client side would be new. It is safe here only because hassette's server already gives a route miss its own problem code. The client doesn't have to guess from a bare 404.

## Anti-patterns

1. **A bool that treats "same" and "older" as one answer.** No surveyed library does this. Every library that reports direction uses an exception (with subclasses in matter), a symmetric warning (kubectl), or a bool predicate paired with a raising `require_` form (aiohue). hassette's `False` for both cases hides the only direction that breaks.
2. **A remedy message that names one side.** zwave-js's connect error says "update the Z-Wave JS Server" even when the client is the side that's too old. music-assistant names both remedies.
3. **Treating an unknown version as compatible without saying so.** aioesphomeapi `_supports_proxy_ack` does `api_version is None or ...`. HA's mealie integration does the same deliberately and visibly (`version.valid and version < MIN`, `mealie/__init__.py:67`), which is reasonable for dev builds. The anti-pattern is the silent version.
4. **Comparing product versions where only the wire contract matters.** aiohue compares firmware versions, and kubectl compares minors. Under lockstep, every hassette release changes the product version even when the wire is unchanged, so `SERVER_NEWER` will be reported after nearly every server upgrade. That's acceptable for a log line, but not for a repair issue or an error.
5. **Library code raising a non-library exception from version introspection.** `importlib.metadata.version()` raises `PackageNotFoundError` without installed metadata. The surveyed libraries keep their version in a constant or a schema number instead.

## Comparison of candidate shapes

| # | Shape | Prior art | Reports "server older" | Turns route-miss 404 into skew info | New state or surface | Fit for hassette |
|---|---|---|---|---|---|---|
| A | `server_is_newer() -> bool \| None` (today) | none | No | No | none | Hides the direction that breaks |
| B | Keep the bool, guard `PackageNotFoundError`, document older-server symptoms | none | Manually | Docs only | none | Cheapest. Leaves the HACS-first case undetectable in code |
| C | **`version_skew(health) -> VersionSkew` enum (`SAME`, `SERVER_NEWER`, `SERVER_OLDER`, `UNKNOWN`), client version from a constant** | kubectl (symmetric), matter (two directions) | Yes | No, but see E | One small enum | **Best fit.** Stateless, one call at setup, maps onto HA's warning and floor logic |
| D | Library-raised `ServerVersionTooOldError(HassetteClientError)` from a `require_server_version(health, minimum)` | aiohue `require_version`, zwave/matter `InvalidServerVersion` | Yes, below a floor | No | One exception class, one function | Good, but the floor belongs to the consumer (spec 114). Additive later if integrations ask for it |
| E | **Message hint on 404 `not_found` / 405 `method_not_allowed`** | Docker (server-side analogue). No client-side precedent | Hints | Yes | none (problem code already exists) | **Recommended alongside C.** Zero state, and the server's own code backs it |
| F | Per-method `since` table, checked before sending | zwave `require_schema`, aioesphomeapi, client-go discovery | Yes, per call | Yes, precisely | Cached server version, a `since` table, client state | Strongest signal. Needs state hassette-client doesn't have. Revisit if C plus E proves too coarse |
| G | Server-advertised range or version header (`Api-Version`, `min_supported_schema_version`) | Docker, music-assistant, zwave, Kafka | Yes | Yes | Server change, schema number | Spec 114 deferred it. A version header on unauthenticated 401s would also disclose the version |

## What the HA consumer needs

From the local core checkout (`~/source/core`):

- **Below the floor, at setup, two conventions exist.**
  - **`ConfigEntryNotReady` plus a non-fixable ERROR repair issue**, deleted after a successful connect: zwave_js (`__init__.py:206-221`), matter (`:100-121`), music_assistant (`:102-111`), system_bridge (`:105-123`). The entry retries with backoff, up to the 600 s cap noted in `prior-art-retryable.md`, so upgrading the server heals it without user action. These four are the closest analogues to hass-hassette: a companion server the user upgrades independently.
  - **`ConfigEntryError`**, which is permanent and needs a manual reload: mealie (`__init__.py:67-75`, translated with `mealie_version`/`min_version` placeholders) and WLED (`coordinator.py:150-156`).
- **In the config flow:** `errors["base"] = "unsupported_version"` (WLED `config_flow.py:62-64`, mealie `"mealie_version"`). This matches spec 113's plan.
- **Server newer:** nothing in core warns about a merely newer server. matter's `ServerVersionTooNew` is an actual incompatibility reported by the library. A log warning (spec 114) is the right weight.
- **Route-miss 404 in the integration:** spec 113 maps 404 to `ServiceValidationError(not_found)`, which reads as "app not found". The integration should catch `AppNotFoundError` for that message, and let a `not_found`-coded 404 fall through to a `HomeAssistantError` that mentions the version. Under a correctly maintained floor this shouldn't happen, but the mapping costs nothing.

## Recommendation for Q1 (shapes C + E, plus a stated promise)

**1. Replace `server_is_newer` with `version_skew(health) -> VersionSkew`.**

- `VersionSkew` is a `StrEnum`: `SAME`, `SERVER_NEWER`, `SERVER_OLDER`, `UNKNOWN`.
- `UNKNOWN` covers an empty version, `"unknown"`, or anything that isn't PEP 440.
- The comparison uses the full PEP 440 version, so `0.56.0.dev3` sorts before `0.56.0`.
- The docstring says the function only compares and enforces nothing. It also says `SERVER_NEWER` is expected after most server upgrades, since releases are lockstep. The name is a suggestion; it reads well in a `match` statement.

**2. Client version from a constant.** `CLIENT_VERSION = "0.55.0"  # x-release-please-version` in `version.py`, added to `release-please-config.json`'s `extra-files` (per CLAUDE.md, a marker does nothing without that entry). This removes the `PackageNotFoundError` path entirely instead of catching it. The fallback, if a constant is unwanted, is to catch `PackageNotFoundError` and return `UNKNOWN`.

**3. The floor stays in the consumer, with a wider rule.**

- Spec 114 says "adding a required wire field means bumping `MIN_HASSETTE_VERSION`". Extend that to "calling a route, or sending a parameter, that is newer than the current floor also means bumping it". The reversed oasdiff run guards response fields. Nothing guards routes or parameters, and an older server drops an unknown parameter silently.
- To make the rule followable, give each client method that postdates the first transport release a `.. versionadded:: X.Y` line in its docstring. It's cheap, it's the lightest form of Pattern 2, and the integration author can see the floor each method needs.

**4. Hint on a route miss.**

- When an error resolves with code `not_found` or `method_not_allowed`, `HassetteHTTPError` appends one clause to its message: "this server has no such endpoint; it may be older than hassette-client X.Y (compare with version_skew())". No new class is needed. The docs say that `exc.code is ProblemCode.NOT_FOUND` means "no endpoint", and that `AppNotFoundError` and its siblings mean "no such thing".
- **Don't** add a direction hint to `ResponseValidationError`. CI blocks newly required response fields in the reversed direction, so above the floor a parse failure is more likely a forward break that was overridden, or a body that isn't hassette (Q2).

**5. State the compatibility promise as a table.** Put it in `version.py` and in the docs' "Talking to a newer server" section, renamed to cover both directions. This is Finding 22, Side B.

| Server change | Older client (server newer) | Newer client (server older, at or above the consumer's floor) |
|---|---|---|
| New response field | Ignored | n/a. New fields are optional, and CI blocks required ones (reversed oasdiff run) |
| New value in an `Open*` field | `UnknownValue` | n/a |
| New value in a closed `Literal`/enum | `ResponseValidationError` (Finding 4) | n/a |
| New problem code | Resolves by status | n/a |
| New route or action | Not called | `NotFoundError` with code `not_found`, or 405, plus the hint above |
| New query parameter or request field | Not sent | **Silently ignored by the server.** The floor is the only guard |
| Renamed, removed or retyped field | `ResponseValidationError`. CI blocks it (forward run) unless overridden in `wire_compat_ignore.txt` | Same |

**6. HA guidance (for spec 113, not this client).**

- Config flow: `unsupported_version` below the floor.
- Setup: `ConfigEntryNotReady` with a translated message naming both versions. Add a non-fixable repair issue if v0.1's "no repair issues" boundary is relaxed for this one case. Delete it on a successful setup, as zwave_js does.
- `VersionSkew.SERVER_NEWER` logs a warning once per setup. `UNKNOWN` passes, as mealie does for dev builds.

**Not now:** a handshake or schema number (G, already deferred by spec 114), per-call `since` enforcement (F), and a library-raised floor exception (D). D is additive whenever an integration asks for it.

## Open questions (Q1)

- [ ] Should a `ConfigEntryNotReady` repair issue for below-floor servers come into v0.1, given that 113 puts repair issues out of scope? Without one, the only user-visible signal is the entry's "retrying setup" message.
- [ ] Should `version_skew` compare full versions, or only `major.minor`? Full versions are simpler but report `SERVER_NEWER` after every patch release. Only matters if a caller surfaces it beyond a log line.
- [ ] Should a CI check flag a new optional query parameter on an existing route? That is the silent-skew case. oasdiff reports `new-optional-request-parameter` as INFO. Whether that check id exists in the pinned oasdiff 1.32.1 was not verified.

---

# Q2. Response-body classification

## The problem

The transport makes three decisions purely by trying to parse (b753b2c5 `transport.py:96-111`). It never reads `Content-Type`:

| Decision | Today | Misclassifies |
|---|---|---|
| Is a 2xx body the model? | `parse_response(model)` | A forward-auth proxy's `200 text/html` login page becomes `ResponseValidationError: <body>: json_invalid`, which reads as version skew (Finding 13). Another case found during this research: a `base_url` with the wrong path prefix pointed at hassette itself also returns `200 text/html`, because the SPA catch-all serves `index.html` for every non-`/api` path (`src/hassette/web/app.py:140-157`) |
| Is a probe 503 the status model? | Try the model, suppress failure | A gateway's JSON 503 that happens to fit `ReadinessResponse` is accepted as "not ready" (Finding 12) |
| Is an error body a problem? | Try `ProblemDetail`, else `None` | Low risk in practice, but any foreign JSON shaped like a problem counts as one |

## How we do it today (server side)

**The server already labels every body.**

- Every error goes through `problem_response()` with `media_type=PROBLEM_MEDIA_TYPE` (`src/hassette/web/errors.py:179-197`). Its callers are:
  - the `HTTPException` handler, including route misses (`:230-238`)
  - the validation handler (`:243`)
  - the unhandled-exception handler (`:272`)
  - the auth middleware (`middleware.py:214`)
  - the body limit (`body_limit.py:62`)
- The only non-2xx responses that aren't problems are the two probe 503s. They return their model through FastAPI's default `application/json`:
  - `routes/health.py:24-29`
  - `routes/telemetry.py:84-98`, whose docstring reads: "a failure answers with this status body rather than a problem body"

So a `Content-Type` rule can tell apart every body hassette sends.

## Patterns found

### Pattern 1: Classify by Content-Type, use a distinct error for "not our service"

**Used by**: python-adguardhome (frenck), python-wled, octokit/request.js, azure-core's 2xx pipeline (`ContentDecodePolicy`), aiohttp's own `ClientResponse.json()`.

**How it works**:

- **adguardhome** (`adguardhome.py:266-295`):
  - It reads status, content type and body, and raises on status first.
  - If `"application/json" not in content_type`, it raises `AdGuardHomeResponseError("AdGuard Home responded with something else than JSON, check if the URL points to AdGuard Home", status=..., body=...)`. The message is fixed text and the body goes on an attribute.
- **aiohttp** `json()` (local `.venv`, `client_reqrep.py:764-795`) raises `ContentTypeError("Attempt to decode JSON with unexpected mimetype: %s")` unless the type matches `^application/(?:[\w.+-]+?\+)?json` (`:90, 250-255`). That accepts `+json` suffixes and ignores parameters. The error does not include the body. `content_type=None` disables the check.
- **octokit** dispatches on the type: JSON is parsed, and a JSON parse failure falls back to text.
- **azure-core** picks JSON, XML or text by media type for 2xx bodies, and raises `DecodeError("Cannot deserialize content-type")` for other types.

**Strengths**: It uses the label RFC 9457 §3 says identifies the format, so a JSON body from another service can't be mistaken for ours. The error can name the actual cause: "not JSON, text/html, check the URL or proxy".

**Weaknesses**: A proxy that rewrites the type while keeping the body would be misclassified. Proxies that intercept errors (nginx `proxy_intercept_errors`, forward-auth) replace the body along with the type, so in the cases that matter the label and the body change together. That is Inferred; no proxy's behavior was tested.

### Pattern 2: Classify by parse attempt and shape (no Content-Type check)

**Used by**: stripe-python (`_interpret_response`, `handle_error_response`), google-api-core (`from_http_response`), githubkit, openai-python's error path (`_make_status_error_from_response`), azure-core's error path (`_parse_odata_body`), and hassette-client today.

**How it works**: The client tries `json.loads` and a shape check. If that fails, it falls back to the raw text. The status still picks the exception class.

- Stripe raises `APIError("Invalid response body from API: %s (HTTP response code was %d)")`.
- google-api-core wraps the text as `{"error": {"message": text}}`.

**Strengths**: Nothing a proxy does to headers can affect it.

**Weaknesses**: RFC 9110 §8.3 counts this as sniffing: it "risks drawing incorrect conclusions" and distinct types "are impossible to distinguish by inspecting the data alone". That is exactly Finding 12. google-api-core's `.get` chain turns a JSON body of the wrong shape into `"unknown error"`, and azure's bare `except Exception: pass` hides parse failures.

### Pattern 3: Content-Type first, with a parse fallback when the header is missing or wrong

**Used by**: openai-python (Stainless) for 2xx bodies, azure-core.

**How it works**:

- **openai** strips parameters and tests `endswith("json")`. If the type isn't JSON and the target is a model, it still tries `response.json()`. With strict validation on, a failure raises `APIResponseValidationError("Expected Content-Type response header to be application/json but received X instead.", body=response.text)`. That puts a content-type mismatch in the *validation* error class.
- **azure** assumes JSON when the header is missing ("Let's guess it's JSON", `_universal.py:700-705`), and also accepts `text/*+json`.

**Strengths**: It tolerates a stripped or rewritten header. openai's error message names the actual mismatch.

**Weaknesses**: Falling back on every non-JSON type brings back the sniffing problem. Treating a missing header as JSON hides a proxy that strips it. openai with strict validation off returns the raw text typed as the model, which is a type lie.

### How much of a foreign body is kept, and where

| Library | Where | Bound |
|---|---|---|
| stripe, google-api-core, openai, octokit | Full text in `str(exc)` and on an attribute | none |
| azure-core | Appended to `str(exc)` only when no error parsed. Full text via `exc.response.text()` | `[:2048]` on the whole string |
| adguardhome, wled | `.body` attribute only. The message is fixed text | none |
| aiohttp `ContentTypeError` | Not kept | n/a |
| hassette-client today | `str(exc)` and `detail` | 500 chars |

No surveyed library redacts. Only adguardhome and wled keep the body out of the message. That is the only shape consistent with hassette's existing rule that server payloads never reach exception text (`parsing.py:42-43`, `from None`).

## Anti-patterns

1. **Using a successful parse as proof of origin.** RFC 9110 §8.3 names this risk. It produces Finding 12.
2. **A foreign body with no limit in `str(exc)`** (stripe, openai, google-api-core). An SSO login page in a log line can carry session ids and return URLs (Finding 17).
3. **A not-JSON body reported as a schema mismatch.** That is today's 2xx path. The class docstring then sends the user looking for a renamed field (Finding 13).
4. **Exact-string type matching.** wled's `content_type == "application/json"` (`wled.py:1578`) breaks on `; charset=utf-8`. Match the media type after removing parameters, or use aiohttp's regex.
5. **Swallowing an error-body parse failure with no signal** (azure `except Exception: pass`). Today's `http_error` does the same by suppressing `ResponseValidationError` into `problem=None`. That is acceptable only if the media type said it was a problem and something should note the mismatch.

## Comparison of candidate rules

| # | Rule | Prior art | Foreign 503 JSON misread as "not ready" | 2xx HTML diagnosed | Proxy strips header | Fit |
|---|---|---|---|---|---|---|
| A | Parse attempt only (today) | stripe, google, githubkit | Yes | No (reads as skew) | Unaffected | Leaves Findings 12 and 13 open |
| B | Content-Type strict: no JSON type means foreign | adguardhome, aiohttp `json()` | No | Yes | Every response fails | Simple, but brittle where the header is missing |
| C | **Content-Type decides, parse confirms; a missing header falls back to parsing** | azure (missing header), openai (fallback), RFC 9110 §8.3 ("MAY examine the data") | No (requires non-problem JSON) | Yes | Degrades to today's behavior | **Best fit.** One rule covers all three decisions |
| D | Parse attempt, plus a `content_type` attribute on errors | none exactly | Yes | Partly (via attribute) | Unaffected | Diagnoses without fixing the misread |

## Recommendation for Q2 (rule C)

**One classification function**, for example `body_kind(content_type) -> {PROBLEM, JSON, OTHER, MISSING}`.

- Remove parameters and lowercase the value.
- `application/problem+json` maps to `PROBLEM`.
- Anything matching aiohttp's `^application/(?:[\w.+-]+?\+)?json` otherwise maps to `JSON`. Reusing aiohttp's rule keeps the client consistent with `resp.json()` in the same session.
- `OTHER` and `MISSING` cover everything else.

The transport then branches on status and kind:

| Status | Kind | Result |
|---|---|---|
| 2xx | `JSON` | Parse the model. A failure raises `ResponseValidationError` (contract or skew), as today |
| 2xx | `MISSING` | Parse the model, which is the RFC 9110 fallback. A failure raises `ResponseValidationError` |
| 2xx | `OTHER` or `PROBLEM` | `ResponseValidationError` with the entry `<body>: not_json (text/html)` |
| 503, probe endpoint | `JSON` | Parse the model. A failure means the body isn't hassette's, so raise `ServiceUnavailableError` |
| 503, probe endpoint | anything else | Raise `ServiceUnavailableError` (or its subclass, by problem code) as on any other route. This is Finding 12 option A. A stripped header raises rather than reporting "not ready" |
| non-2xx | `PROBLEM` | Parse `ProblemDetail` and pick the class by code. If the parse fails, `problem=None`, pick by status, and add `malformed_problem` to the message (no payload) |
| non-2xx | `JSON`, `OTHER`, `MISSING` | `problem=None`, class by status |

**The 2xx foreign-body error.** Add `status: int | None` and `content_type: str | None` attributes to `ResponseValidationError`, set when the error is raised from a response and `None` from a bare `parse_response`.

- Use a distinct problem entry, not a new class. That is Finding 13 option A. It matches openai, which raises its validation error for a type mismatch, and it keeps spec 113's mapping (`ResponseValidationError` to `UpdateFailed`) unchanged.
- Update the class docstring: "a renamed or removed field, or a body that isn't a hassette JSON response (see `content_type`)".
- adguardhome-style hint text belongs in the message: "check base_url, or whether a proxy answered".
- If the integration's config flow needs to tell "not hassette" apart from "schema mismatch" to show a distinct form error, a subclass such as `UnexpectedResponseError(ResponseValidationError)` is an additive later step. Every existing `except ResponseValidationError` keeps working.

**Where the foreign body goes.**

- Keep up to `MAX_BODY_EXCERPT_CHARS` on an attribute, renamed from `detail` to something like `body_excerpt` for non-problem bodies, on both `HassetteHTTPError` and the 2xx `ResponseValidationError`.
- `str(exc)` carries status, media type and byte length, never body text.
- A problem's `detail` stays in the message, because it is server-authored text whose constants exist precisely so internals don't leak (`INTERNAL_ERROR_DETAIL`, `TELEMETRY_UNAVAILABLE_DETAIL`, `errors.py:150-157`).
- This follows the adguardhome and wled shape and covers the body half of Finding 17.

**Not now:** a CHANGELOG-visible new exception class, header-based detection of specific proxies, and sniffing HTML to extract a login URL.

**Tests to add:**

- `200 text/html` gives `ResponseValidationError` with `content_type == "text/html"` and no body text in `str(exc)`.
- 2xx `application/json; charset=utf-8` parses.
- A 2xx with no `Content-Type` and valid JSON parses.
- A probe 503 `application/json` model is returned. A probe 503 `text/html` raises `ServiceUnavailableError`. A probe 503 `application/problem+json` raises by code.
- 404 `application/json` `{"detail": "Not Found"}` gives `NotFoundError` with `problem is None`.
- 404 `application/problem+json` `not_found` gives `NotFoundError` with the skew hint from Q1.

## Open questions (Q2)

- [ ] Should a non-2xx `application/json` body that parses as a `ProblemDetail` count as a problem? That covers a proxy that rewrites the type but keeps the body. RFC 9457 identifies problems by media type, and no evidence was found of a common proxy doing this. The recommendation says no.
- [ ] Should `UnexpectedResponseError` be a subclass now, so the config flow can show "this URL doesn't point to hassette" (adguardhome's hint) as a form error, not `cannot_connect`? That depends on the integration's error UX. The cost is one class.
- [ ] The SPA catch-all answering `200 text/html` for a wrong `base_url` prefix is a server behavior. Should non-API paths return 404 to `Accept: application/json` requests? That's a server question, outside the client.

## Coverage notes

- **HA core:** checked locally (`~/source/core`). matter's `ServerVersionTooNew` and `ServerVersionTooOld` are confirmed by HA's imports from `matter-python-client==1.4.0` (`matter/manifest.json:11`). The research subagent read the `python-matter-server` repo, which showed only `ServerVersionTooOld`, so the library source wasn't confirmed at the pinned version.
- **aiohttp:** behavior was read from the installed `.venv` source (python3.14 site-packages).
- **Docker:** the 400 status for "client too new" is inferred from `InvalidParameter()` and a commit title. aiohue's `InvalidAPIVersion` raise site was not found.
- **Not checked:** music-assistant mobile-app#1012 (cited in spec 114), kiota, openapi-python-client, aiogithubapi, roborock, aioshelly, and RFC 6839's text on `+json` suffixes. python-elgato and python-tailscale were checked and don't check Content-Type.
- **FastAPI:** the claim that it ignores undeclared query parameters is from its documented default behavior, not a test run here.

## Sources

### Reference implementations
- https://github.com/home-assistant-libs/zwave-js-server-python/blob/master/zwave_js_server/client.py, `exceptions.py`: schema range check, `require_schema`, `InvalidServerVersion` fields
- https://github.com/home-assistant-libs/python-matter-server/blob/main/matter_server/client/client.py, `client/exceptions.py`: per-command `ServerVersionTooOld`
- https://github.com/music-assistant/client/blob/main/music_assistant_client/client.py: `min_supported_schema_version`, two-remedy message
- https://github.com/esphome/aioesphomeapi/blob/main/aioesphomeapi/connection.py, `client.py`: `APIVersion` gates and fallbacks
- https://github.com/home-assistant-libs/aiohue/blob/master/aiohue/v2/controllers/config.py: `check_version` / `require_version`
- https://github.com/moby/moby/blob/master/daemon/server/middleware/version.go, https://github.com/docker/docker-py/blob/main/docker/api/client.py
- https://github.com/kubernetes/kubectl/blob/master/pkg/cmd/version/skew_warning.go, https://github.com/kubernetes/client-go/blob/master/discovery/helper.go
- https://raw.githubusercontent.com/frenck/python-adguardhome/main/src/adguardhome/adguardhome.py (L266-295)
- https://raw.githubusercontent.com/frenck/python-wled/main/src/wled/wled.py
- https://raw.githubusercontent.com/Azure/azure-sdk-for-python/main/sdk/core/azure-core/azure/core/exceptions.py, `.../pipeline/policies/_universal.py`
- https://raw.githubusercontent.com/stripe/stripe-python/master/stripe/_api_requestor.py
- https://raw.githubusercontent.com/googleapis/google-cloud-python/main/packages/google-api-core/google/api_core/exceptions.py
- https://raw.githubusercontent.com/octokit/request.js/main/src/fetch-wrapper.ts
- https://raw.githubusercontent.com/yanyongyu/githubkit/master/githubkit/response.py
- https://raw.githubusercontent.com/openai/openai-python/main/src/openai/_response.py, `_base_client.py`, `_exceptions.py`
- aiohttp `client_reqrep.py:90, 250-255, 764-795` (local `.venv`)
- HA core (local `~/source/core`): `components/{zwave_js,matter,music_assistant,system_bridge,mealie,wled}/__init__.py`, `wled/coordinator.py`, `wled/config_flow.py`, `matter/strings.json`, `zwave_js/strings.json`

### Documentation and standards
- https://www.rfc-editor.org/rfc/rfc9457.html: §3 media type, §3.2 ignore unknown extensions, §5 intermediaries
- https://www.rfc-editor.org/rfc/rfc9110.html#section-8.3: Content-Type, missing header, sniffing
- https://kubernetes.io/releases/version-skew-policy/
- https://docs.docker.com/reference/api/engine/
- https://docs.github.com/en/rest/about-the-rest-api/api-versions
- https://docs.stripe.com/api/versioning
- https://cwiki.apache.org/confluence/display/KAFKA/KIP-35+-+Retrieving+protocol+version
- https://www.rfc-editor.org/rfc/rfc9745.html: `Deprecation` header (server-to-client retirement, not client-too-new)

Note: URLs were fetched by the research subagents on 2026-10-07 at `main`/`master`. Line numbers may drift.
