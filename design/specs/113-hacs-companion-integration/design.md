# Design: hassette-client library (HACS companion v0.1, unit B)

**Date:** 2026-09-24
**Status:** draft
**Scope-mode:** hold
**Research:** `/tmp/claude-mine-define-research-sm9flW/brief.md` (key findings folded in below; the
file is session-scoped, and this document is the durable record)

Unit B of the v0.1 split recorded in `brief.md` (Spec decomposition). A is #2368 (failed
start/reload return 500). C is the `hass-hassette` integration, specced in its own repo. D is the
pinned-release end-to-end test and the docs page. The integration's needs (its config flow,
coordinator and entity call sites) are this library's spec. Decisions that belong to C and D stay
in `brief.md`.

## Problem

The `hass-hassette` integration (ADR-0006) is an API client of hassette's web API, and HA
integrations need their wire logic in a separate PyPI library that takes HA's shared aiohttp
session (`inject-websession`). Two things block that today:

- **There's nothing to reuse.** The only client, `src/hassette/cli/client.py`, is synchronous
  `httpx2` and calls `sys.exit` on errors. Importing `hassette` into HA would pull hassette's
  whole dependency tree into HA's environment, which installs integration requirements against
  its own exact pins.
- **Errors aren't machine-readable.** Callers can only tell hassette's two 409s apart
  ("bootstrap not released", retryable; "blocked by the `--app` filter", not retryable) by their
  human-readable `detail` text. No test pins those strings, and a published client that matched
  on them would silently misclassify errors after a rewording.

## Goals

- A published, typed, async `hassette-client` 0.x on PyPI that covers exactly what the v0.1
  integration calls, and that installs cleanly next to HA 2026.9's pinned `aiohttp` and `pydantic`.
- Hassette's app-action error responses carry a stable machine-readable code (RFC 9457 problem
  details), so the client classifies errors by code instead of by prose.
- Server/client drift fails hassette's own CI.
- Hassette's existing release (tags `vX.Y.Z`, release-PR title, `CHANGELOG.md`, Docker image,
  PyPI package) is unchanged by the second release train.

## Non-Goals

- The HA integration itself (C), the pinned-release end-to-end test and docs page (D), and
  start/reload failure semantics (#2368, A).
- Problem details on hassette's other routes, the auth middleware, and 422/413/503 responses,
  except the 400 `invalid_app_key` on the `manifest`/`config`/`source` GET routes, which FR#1
  covers. The rest is
  tracked as #2369: the user explicitly didn't want the scoped version to stay
  permanent.
- Per-instance client methods, WebSocket push, and any endpoint beyond the five below.
- Porting the CLI onto the library. The CLI stays on sync `httpx2`.

## User Scenarios

### Integration author: the `hass-hassette` config flow, coordinator and entities
- **Goal:** talk to hassette with typed results and typed failures.
- **Context:** inside HA's event loop, on HA's shared `aiohttp` session.

#### Validate a new config entry
1. **Construct the client** with `async_get_clientsession(hass, verify_ssl=...)`, the URL, and the
   token if the user entered one (`None` for a trusted-peer setup).
   - Then: nothing happens on the network. The client owns no session.
2. **Call `get_health()`.**
   - Sees: `ServerStatus.parsed_version`, or an exception.
   - Decides: `HassetteAuthError` → `invalid_auth`; `HassetteConnectionError` (including a timeout)
     → `cannot_connect`; `parsed_version` below the integration's minimum → `unsupported_version`.
     `parsed_version is None` (a dev or editable hassette reporting `"unknown"`) is the caller's
     call (C decides); the client never raises for it.

#### Poll
1. **Call `get_app_manifests()`** every 30 s.
   - Sees: `AppManifestList.manifests`, each with `app_key`, `status`, `in_current_config`, and
     so on.
   - Decides: `HassetteAuthError` → reauth; any other `HassetteError` → `UpdateFailed`. A 503
     always raises and never yields an empty list.

#### Act
1. **Call `start_app` / `stop_app` / `reload_app(app_key)`.**
   - Sees: an `ActionResult` (accepted), or a typed error.
   - Decides: `HassetteNotFoundError` → `not_found`; `HassetteAppBlockedError` →
     `blocked_by_filter`; `HassetteBootstrapNotReadyError` → `not_bootstrapped`;
     `HassetteActionFailedError` → `action_failed` carrying the server's `detail`. Any other
     `HassetteApiError` (a code-less 500, a proxy error) → a generic action failure;
     `HassetteConnectionError` → outcome unknown.
   - Then: the integration requests a coordinator refresh.

The call sites the user approved during discovery are the interface anchor (see Architecture →
Client API).

## Functional Requirements

**Hassette server: problem details for app actions**

- **FR#1** Every error that the app-level and instance-level start/stop/reload routes
  (`POST /api/apps/{app_key}/{start,stop,reload}` and
  `POST /api/apps/{app_key}/instances/{index}/{start,stop,reload}`) raise for the FR#4 conditions
  is sent with `Content-Type: application/problem+json`. So is the 400 `invalid_app_key` response
  from the GET routes `/api/apps/{app_key}/manifest`, `/config` and `/source`, which share
  `_validate_app_key`. Two paths are deliberately outside this guarantee (see Edge Cases): the
  auth middleware's 401, and exceptions `_run_app_action` doesn't catch.
- **FR#2** Those error bodies contain the RFC 9457 members `type`, `title`, `status` and `detail`,
  plus an extension member `code`.
- **FR#3** The `detail` member keeps exactly the string the route sends today.
- **FR#4** Each error condition has a stable `code`: `invalid_app_key` (400), `app_not_found`
  (404), `instance_not_found` (404), `bootstrap_not_released` (409), `app_blocked` (409), and
  `action_failed` (500).
- **FR#5** `type` is the absolute URI of that code's anchor on the new docs page
  `docs/pages/web-ui/api-errors.md`.
- **FR#6** Successful action responses (202 `ActionResponse`) are unchanged.

**Client library**

- **FR#7** `HassetteClient` takes a caller-owned `aiohttp.ClientSession`, a base URL and an
  optional token, and never closes the session.
- **FR#8** When a token is given, every request sends `Authorization: Bearer <token>`. When the
  token is `None`, no request sends an `Authorization` header, so hassette's trusted-peer check
  (`web_api.trusted_proxies`) decides admission.
- **FR#9** Every request uses an explicit per-request timeout (default 10 s, set via a
  constructor argument).
- **FR#10** Requests never follow redirects. A 3xx response raises `HassetteRedirectError`.
- **FR#11** `get_health()` returns a `ServerStatus` parsed from `GET /api/health`. Its
  `version` is the server's raw version string, which is the non-PEP 440 sentinel `"unknown"`
  when hassette's package metadata can't be resolved (editable or dev installs;
  `utils/version_utils.py:9-14`). `ServerStatus.parsed_version` exposes it as a
  `packaging.version.Version`, or `None` for the sentinel or any other unparseable value, so
  callers never parse it themselves.
- **FR#12** `get_app_manifests()` returns an `AppManifestList` parsed from
  `GET /api/apps/manifests`.
- **FR#13** `start_app(app_key)`, `stop_app(app_key)` and `reload_app(app_key)` POST to the
  matching app-level route and return an `ActionResult`.
- **FR#14** A connection failure raises `HassetteConnectionError`.
- **FR#15** A timeout raises `HassetteTimeoutError`, a subclass of `HassetteConnectionError`.
- **FR#16** A 401 raises `HassetteAuthError`.
- **FR#17** A 409 with `code: bootstrap_not_released` raises `HassetteBootstrapNotReadyError`;
  `code: app_blocked` raises `HassetteAppBlockedError`; any other 409 raises their shared base,
  `HassetteConflictError`.
- **FR#18** A 404 raises `HassetteNotFoundError`.
- **FR#19** A 500 with `code: action_failed` raises `HassetteActionFailedError`, exposing the
  server's `detail` as `.message`.
- **FR#20** Any 503 raises `HassetteUnavailableError`, whatever its body.
- **FR#21** Any other non-2xx status raises `HassetteApiError`, carrying `.status`, `.code`
  (possibly `None`) and `.message`. It's the base of every status-derived error.
- **FR#22** A 2xx body that isn't valid JSON, or doesn't match the model, raises
  `HassetteResponseError`.
- **FR#23** Model parsing ignores unknown fields.
- **FR#24** An enum-valued field with an unrecognized value parses to that enum's `UNKNOWN`
  member instead of failing.
- **FR#25** The status-to-exception mapping is a public pure function,
  `error_from_response(status, body, headers)`, which the client's HTTP layer calls.
- **FR#26** Every exception the client raises is a `HassetteError`.
- **FR#27** The installed `hassette_client` package imports nothing from `hassette`.
- **FR#28** The package ships `py.typed`.
- **FR#40** The client reads `code` only from a response whose `Content-Type` is
  `application/problem+json`. Any other error response, including JSON from a proxy that happens
  to contain a `code` key, is classified by status alone with `code=None`.

**Packaging and release**

- **FR#29** The repo is a uv workspace with `client/` as its only member. `codegen/` stays a
  standalone path dependency.
- **FR#30** A commit touching only `client/` does not bump hassette's version and does not appear
  in `CHANGELOG.md`.
- **FR#31** The client releases through its own release-please PR titled
  `chore(main): release hassette-client X.Y.Z`, tagged `hassette-client-vX.Y.Z`, with changelog
  `client/CHANGELOG.md`.
- **FR#32** Hassette's release PR title (`chore(main): release X.Y.Z`), tags (`vX.Y.Z`) and
  `CHANGELOG.md` are unchanged.
- **FR#33** A client release builds and publishes only `hassette-client` to PyPI, from its own
  job and GitHub environment (`release-client`).
- **FR#34** A hassette release never builds or publishes the client, and a client release never
  runs hassette's Docker, PyPI, release-notes or verify jobs.
- **FR#35** A manual `workflow_dispatch` with `tag_name` runs the hassette jobs for a `v*` tag, the
  client jobs for a `hassette-client-v*` tag, and fails fast for anything else.
- **FR#36** Every open release PR gets its `uv.lock` re-synced, not only the first.
- **FR#37** The PyPI and Docker drift checks compare against the newest `v*` release, never a
  `hassette-client-v*` release.
- **FR#38** After `publish-client`, a `client-release-verify` job installs
  `hassette-client==<released version>` from PyPI into a clean environment, imports
  `hassette_client`, and asserts `hassette_client.__version__` matches. It fails the run
  otherwise, printing a recovery notice the same way hassette's `release-verify` does.
- **FR#39** A scheduled client drift check compares the newest `hassette-client-v*` GitHub release
  with the latest `hassette-client` version on PyPI, and files an issue when they diverge. It
  reuses `tools/release/drift_check.py`.

## Edge Cases

- **A 503 from `/api/apps/manifests` has a valid, empty body** (`db_degrades_to`,
  `web/dependencies.py:122-134`). The client raises `HassetteUnavailableError` and never returns
  the empty list. The CLI's `tolerate_503` behavior is deliberately not copied.
- **Forward-auth proxy:** it answers 302 to an HTML login page. Because redirects aren't
  followed, this surfaces as `HassetteRedirectError`, not as a JSON decode error on the login
  page's 200.
- **Trusted peers and tokens.** A presented `Authorization` header is authoritative: a wrong or
  malformed token fails closed with no fall-through to peer trust (`web/auth/__init__.py:94-102`,
  `resolve_auth_outcome`). So with a token, a wrong one is always a 401 → `HassetteAuthError`,
  even from a trusted peer. Peer trust only admits requests with no `Authorization` header,
  which is what `token=None` sends (FR#8). A tokenless client whose address isn't in
  `trusted_proxies` gets a 401 → `HassetteAuthError`.
- **Empty-string token:** it is treated as `None`, meaning no header is sent. An empty bearer
  value would fail closed on the server anyway, so sending it only produces a confusing 401.
- **401 from the auth middleware is not problem-details.** `DefaultDenyMiddleware` returns
  `_unauthorized_response()` (`web/middleware.py:265`), a plain
  `JSONResponse({"detail": "Not authenticated"}, 401)` (`:206-207`),
  before FastAPI's exception handlers run. This is deliberately out of scope: 401 has one meaning
  in this API, so the status alone yields `HassetteAuthError`, and changing the shared
  security middleware gains nothing. #2369 covers it.
- **Uncaught exceptions on the action path.** `_run_app_action` catches only
  `AppBootstrapNotReleasedError`, `AppBlockedError` and `(ValueError, RuntimeError)`
  (`routes/apps.py:158-170`). Anything else escapes to Starlette's plain-text 500 with no `code`.
  The client raises the base `HassetteApiError(status=500, code=None)` for it. Callers treat
  a code-less 500 as a generic action failure by catching `HassetteApiError`, not only the named
  leaf classes. A catch-all conversion is #2369's job. #2368 (A) widens which failures reach
  `action_failed` and carries the real error message.
- **Unresolvable server version:** a dev or editable hassette reports `version: "unknown"`.
  `ServerStatus.parsed_version` is `None`, and the caller decides what that means (C's version
  gate). The client never raises for it.
- **Newer hassette, older client:** new fields are ignored (FR#23); new status values parse to
  `UNKNOWN` (FR#24). `ManifestStatus.BLOCKED` (added 2026-08-13) is the precedent: a strict mirror
  would have failed every poll.
- **Newer client, older hassette:** before this spec's hassette change ships, 409s carry no
  `code`. They raise the generic `HassetteConflictError`, never the wrong subclass.
- **Proxy-generated errors** (413/502/504, HTML bodies): `HassetteApiError(status)` with
  `code=None`. A non-JSON error body is never an error in its own right.
- **`app_key` containing URL-reserved characters:** hassette's `_VALID_APP_KEY`
  (`routes/apps.py:37`, `^[a-zA-Z_][a-zA-Z0-9_.]{0,127}$`) requires a leading letter or `_`,
  allows only `[a-zA-Z0-9_.]` after it, and caps the key at 128 characters. The client still percent-encodes the path
  segment, and an invalid key comes back as a 400 `invalid_app_key` → `HassetteApiError`.
- **Base URL with or without a trailing slash or path prefix** (`http://host/hassette/`): the
  client joins `/api/...` onto a normalized base, and a subpath prefix is preserved.
- **Session closed by the caller mid-request:** aiohttp's `RuntimeError` or `ClientError`
  surfaces as `HassetteConnectionError`.

## Acceptance Criteria

- **AC#1** `uv run pytest tests/integration/web_api/test_problem_details.py` passes. For each
  code in FR#4 it asserts the status, `Content-Type: application/problem+json`, `code`, `type`,
  and the unchanged `detail` string (FR#1-FR#5).
- **AC#2** The existing `tests/integration/web_api/test_endpoints.py` passes unchanged, including
  the 202 `ActionResponse` assertions (FR#6).
- **AC#3** `uv run nox -s client` passes in an environment without `hassette` installed, and
  meets `client/pyproject.toml`'s `fail_under` (FR#7-FR#28, FR#40).
- **AC#4** `uv run nox -s client_lowest` passes: the client suite under
  `--resolution lowest-direct` proves the declared `aiohttp` and `pydantic` floors.
- **AC#5** `uv run pytest tests/integration/web_api/test_client_contract.py` passes. It runs real
  JSON from all five routes through the `hassette_client` models, and drives every FR#4 error path
  through `error_from_response`, asserting the exception subclass.
- **AC#6** `grep -rnE '^\s*(from|import) hassette(\.|\s|$)' client/src` prints nothing (FR#27).
- **AC#7** `uv build --package hassette-client --out-dir /tmp/hc-dist` produces exactly one
  `hassette_client-*.whl` and one sdist, and the wheel contains `hassette_client/py.typed`.
- **AC#8** `uv lock --check` passes, and `docker build .` succeeds. The image's installed packages
  do not include `hassette-client`.
- **AC#9** `prek -a && prek pyright -a --stage pre-push` passes, including zizmor and actionlint on
  the edited workflows and pyright over `client/src`.
- **AC#10** `uv run pytest` at the repo root does not collect anything under `client/`.
- **AC#11** `python tools/check_release_please_config.py` passes. It's a new check that asserts
  the root package has `exclude-paths: ["client"]` and `include-component-in-tag: false`, that
  top-level `separate-pull-requests` is `true`, and that the `client` package declares component
  `hassette-client`.

## Key Constraints

- **The client never imports `hassette`**, not even for types, and never exact-pins (`==`,
  minor-level `<`, patch-level `~=`) anything HA ships. Floors stay at what the code actually
  uses.
- **No redirect following, no default-infinite timeouts.** HA's shared session has no short
  default timeout.
- **Never match on `detail` prose** in the client. Classify by status plus `code` only.
- **Don't change the root release's observable surface:** tags, PR title, `CHANGELOG.md`,
  Docker, or PyPI.
- **Don't build both packages in one job.** `uv build --package` writes to the workspace-root
  `dist/`, and `tools/release/check_wheel_spa.py` checks every wheel there.
- **Keep the workspace `members` list explicit (`["client"]`), never a glob.** A glob would
  absorb `codegen/`.
- **Don't seed the client in `.release-please-manifest.json`.** `"0.0.0"` is release-please's
  never-released sentinel. With no entry, the first release is `0.1.0`.

## Dependencies and Assumptions

- **HA 2026.9.2 pins** `aiohttp==3.14.3` and `pydantic==2.13.4`
  (`~/source/core/homeassistant/package_constraints.txt:9,144`), and installs integration
  requirements with `--constraint` (`homeassistant/util/package.py:174-175`). The client's floors
  must sit at or below the pins of the integration's minimum HA version. C picks that version;
  AC#4 proves the floors install.
- **hassfest** runs format-only checks on custom-integration requirements
  (`script/hassfest/requirements.py:374-410`), so `"hassette-client>=0.1.0,<0.2"` (no spaces) is
  valid in C's `manifest.json`.
- **release-please v17.11.2 / action v5.0.0 mechanics**, read from source by the research:
  - The root package receives every commit unless `exclude-paths` is set
    (`src/manifest.ts:689-706`).
  - `separate-pull-requests` defaults to "exactly one package" (`src/manifest.ts:383-385`).
  - Root outputs are unprefixed; the client's are `client--*`.
  - `createRelease` never sets `make_latest` (`src/github-api.ts:700-709`), so each client
    release becomes GitHub's "Latest".
- **Manual setup (owner: the maintainer) before the first client release:**
  - Create the PyPI pending publisher: project `hassette-client`, owner `NodeJSmith`, repo
    `hassette`, workflow `release-please.yml`, environment `release-client`.
  - Create the `release-client` GitHub environment, optionally restricted to `hassette-client-v*`
    tags.
  - A pending publisher does not reserve the name. `hassette-client` was free on 2026-09-24, so
    set this up shortly before the first release merges.
- **Process verification, not an AC:** before merging the release plumbing, run
  `release-please release-pr --dry-run` with the new config. It needs a GitHub token. Confirm
  that the root PR title stays `chore(main): release …` and that `client/` commits are absent from
  the root changelog.
- **Accepted costs** (the user reviewed the tradeoffs and accepted all of them, 2026-09-24):
  - **The five endpoints' response models are a published contract.** Changes must stay
    additive. Mitigation: lenient parsing (FR#23-FR#24) plus the contract test (AC#5).
  - **A second test environment**: the isolated `client` nox venv, a client CI job, and a
    lowest-direct job.
  - **Two release trains**: two changelogs, two PyPI environments, and tag-prefix routing.
    Accepted with the implementation preferences.
- **Unverified; mitigated by construction:** Renovate's default range handling for
  `client/pyproject.toml` under the self-hosted runner. A `packageRule` in `renovate.json`
  disables updates to that file's dependency ranges, so the floors change only by hand.

## Architecture

### 1. Problem details on app-action errors (hassette)

A new module, `src/hassette/web/problems.py`, holds the whole mechanism:

- `ApiProblem(HTTPException)` takes `status_code`, `code` and `detail`. It derives `title` from a
  module-level `PROBLEM_TITLES: dict[str, str]`, and `type` from
  `f"{PROBLEM_DOCS_URL}#{code}"`, where `PROBLEM_DOCS_URL` is the absolute docs URL of
  `pages/web-ui/api-errors/`.
- `problem_exception_handler(request, exc: ApiProblem)` returns a `JSONResponse` with
  `media_type="application/problem+json"` and the body
  `{"type", "title", "status", "detail", "code"}`.
- A pydantic `ProblemResponse` model is used in the `responses=` of each action route, and in the 400 entry of the three GET routes that share `_validate_app_key` (`/manifest`, `/config`, `/source`), so OpenAPI documents the shape everywhere FR#1 applies. Run `scripts/export_schemas.py --types` afterwards.

`create_fastapi_app` (`web/app.py:49`) registers the handler with
`app.add_exception_handler(ApiProblem, problem_exception_handler)`. Starlette dispatches handlers
by the exception's MRO, so this more specific handler wins over the default `HTTPException` one.
Every other route keeps raising plain `HTTPException` and is untouched.

In `web/routes/apps.py`, each `HTTPException` raised on the action path becomes an `ApiProblem`,
keeping the existing `detail` strings verbatim:

- `_validate_app_key` (`:66-68`) → `invalid_app_key`
- `_require_known_app` (`:97-103`) → `app_not_found`
- `_require_valid_instance_index` (`:106-130`) has two raises: its own unknown-app 404 (`:125`)
  → `app_not_found`, and the out-of-range 404 (`:130`) → `instance_not_found`. Instance-level
  routes call it before `_run_app_action`, so the `:125` raise, not `_require_known_app`, is
  what an unknown `app_key` hits on those routes.
- `_run_app_action`'s two 409s → `bootstrap_not_released` / `app_blocked`
- `_run_app_action`'s 500 → `action_failed`

This is also the path #2368 (unit A) sends failed starts through, so A only needs to raise into
it. `_validate_app_key` is also called by the non-action GET routes (`/apps/{app_key}/manifest`,
`/config`, `/source`; `:229`, `:374`, `:447`), so their 400 becomes a problem-details response
too. That's additive and harmless (their tests assert status only), and it's the first step of
the repo-wide follow-up (#2369). Their 404s are separate inline raises (`:238`, `:377`, `:450`,
`:470`, `:475`) and stay plain `HTTPException`: they're outside this spec's scope and belong to
#2369.

Existing consumers are unaffected. The CLI reads `response.json().get("detail")`
(`cli/client.py:554`), and the frontend reads `body.detail ?? body.message`
(`frontend/src/api/client.ts:26-27`). Neither checks the content type.

### 2. The `hassette-client` package

```
client/
  pyproject.toml          # name hassette-client, build-backend uv_build (same range as root),
                          # requires-python >=3.11, deps: aiohttp>=<floor>, pydantic>=2.<floor>,<3,
                          #   packaging>=23.1 (HA core package_constraints.txt:52)
  README.md               # PyPI landing page: install, quick example, error table
  CHANGELOG.md            # created by release-please on first release
  src/hassette_client/
    __init__.py           # re-exports HassetteClient, models, errors; __version__
    py.typed
    client.py             # HassetteClient (aiohttp plumbing only)
    errors.py             # exception hierarchy + error_from_response()
    models.py             # pydantic models + lenient enums
  tests/                  # client's own suite; aiohttp test server fixtures
```

**Client API** (the call sites approved in discovery are the contract):

```python
class HassetteClient:
    def __init__(self, session: aiohttp.ClientSession, base_url: str, token: str | None = None,
                 *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None: ...
    async def get_health(self) -> ServerStatus: ...
    async def get_app_manifests(self) -> AppManifestList: ...
    async def start_app(self, app_key: str) -> ActionResult: ...
    async def stop_app(self, app_key: str) -> ActionResult: ...
    async def reload_app(self, app_key: str) -> ActionResult: ...
```

A private `_request(method, path) -> bytes` does the one aiohttp call, with
`allow_redirects=False`, `timeout=aiohttp.ClientTimeout(total=self.timeout)`, and the bearer
header only when a token is set. It wraps `asyncio.TimeoutError` → `HassetteTimeoutError` and `aiohttp.ClientError` /
`RuntimeError` → `HassetteConnectionError`. **Except order is load-bearing:** the
`asyncio.TimeoutError` clause must come before `aiohttp.ClientError`. `aiohttp.ServerTimeoutError`
(connect and socket-read timeouts) subclasses both, so a `ClientError`-first order would
classify it as a plain connection error and break FR#15. It hands every non-2xx to `error_from_response`.
Each public method is `_request` plus `Model.model_validate_json(...)`, wrapping
`ValidationError` → `HassetteResponseError`.

**Errors** (`errors.py`):

```
HassetteError
├── HassetteConnectionError
│   └── HassetteTimeoutError
├── HassetteResponseError            # 2xx body unparseable / wrong shape
└── HassetteApiError(status, code, message)   # any non-2xx
    ├── HassetteRedirectError        # 3xx
    ├── HassetteAuthError            # 401
    ├── HassetteNotFoundError        # 404
    ├── HassetteConflictError        # 409 (unknown code)
    │   ├── HassetteBootstrapNotReadyError   # code bootstrap_not_released
    │   └── HassetteAppBlockedError          # code app_blocked
    ├── HassetteActionFailedError    # 500 + code action_failed
    └── HassetteUnavailableError     # 503
```

`error_from_response(status: int, body: bytes, headers: Mapping[str, str]) -> HassetteApiError`
is pure. It reads `code` and `detail` from the body only when `headers["Content-Type"]` (compared
case-insensitively, ignoring parameters) is `application/problem+json`. Otherwise `code=None`,
and the message comes from a JSON `detail` if present, else the raw body or status. It then
picks the subclass through a `(status, code)` lookup table, with a per-status fallback, then
`HassetteApiError`. Gating on the problem media type stops a proxy's JSON error that happens to
contain `code: bootstrap_not_released` from being classed as a retryable hassette condition.
Hassette always sends that media type for its coded errors (FR#1), so nothing legitimate is lost.

**Models** (`models.py`):

- They mirror the fields the integration reads, not every server field:
  - `ServerStatus`: `status`, `version`, `websocket_connected`, `bootstrap_released`,
    `app_count`, plus the computed property `parsed_version` (FR#11).
  - `AppManifestList`: `total`, `manifests`, `only_apps`.
  - `AppManifest`: `app_key`, `class_name`, `display_name`, `enabled`, `autostart`, `status`,
    `block_reason`, `instance_count`, `instances`, `error_message`, `in_current_config`.
  - `AppInstance`: `app_key`, `index`, `instance_name`, `class_name`, `status`, `error_message`.
  - `ActionResult`: `status`, `app_key`, `action`, `instance_index`.
- Sources: `web/models.py:78-176,462-474`.
- `model_config = ConfigDict(extra="ignore", frozen=True)`.
- Lenient enums: `ManifestStatus`, `InstanceStatus` (mirrors `ResourceStatus`) and
  `HealthState` (mirrors the `SystemHealthStatus` Literal, `web/models.py:50`) are `StrEnum`s
  with an `UNKNOWN = "unknown"` member and a `_missing_` classmethod that returns `UNKNOWN`. The
  values mirror `types/enums.py` exactly. The contract test (AC#5) catches a server enum growing
  a value the client hasn't learned yet. The published client degrades to `UNKNOWN` instead of
  failing.

### 3. Workspace conversion

Files changed (see Impact):
- Root `pyproject.toml` gains `[tool.uv.workspace] members = ["client"]`,
  `[tool.uv.sources] hassette-client = { workspace = true }`, and `hassette-client` in the `test`
  dependency group. The Docker, pip-audit and wheel paths all exclude that group.
- `"client"` is added to `[tool.pytest.ini_options] norecursedirs` and `[tool.house-lint] include`.
- The Dockerfile adds only `client/pyproject.toml`. Unlike `codegen/` (Dockerfile:31-32), it
  needs no stub `__init__.py`: codegen is a setuptools path dependency, while the client is a
  `uv_build` workspace member that `--no-default-groups` never installs. The research verified
  that this single file makes `uv lock --check` and `uv sync --locked --no-default-groups`
  pass.
- `pyrightconfig.json` includes `client/src`.
- The house-lint `files` regex in `prek.toml` gains `client`.
- The `changes` path filters in `tests.yml` and `lint.yml` gain `client/**`.

**New nox sessions:**
- `client` creates its own venv and installs only `./client` plus its test deps, so any
  `import hassette` fails there. That's AC#3's enforcement of FR#27.
- `client_lowest` runs the same suite with `--resolution lowest-direct`.

A new CI job in `tests.yml` runs both. The client's `fail_under` lives in
`client/pyproject.toml`. Root coverage stays `source = ["hassette"]`, so neither measures the
other.

### 4. Release plumbing

- **`release-please-config.json`:**
  - Top level: `"separate-pull-requests": true`.
  - Root `"."`: `"exclude-paths": ["client"]`, `"include-component-in-tag": false`.
  - New `"client"` package: `release-type: python`, `package-name` and `component`
    `hassette-client`, `bump-minor-pre-major: true`, and the root's `changelog-sections`.
  - No manifest entry for the client.
- **New `tools/check_release_please_config.py`** (AC#11) encodes those invariants, so a later
  config edit can't silently regress them. It's wired as a prek hook on
  `release-please-config.json`.
- **`.github/workflows/release-please.yml`:**
  - The `release-please` job also exports `client_release_created`
    (`steps.release.outputs['client--release_created']`), `client_tag_name` and `prs`.
  - `sync-lockfile` runs as a matrix over `fromJSON(prs)` whenever `prs` is non-empty, with **no
    run-level release guard**. Today's guard is root-only `release_created != 'true'`
    (`release-please.yml:47`). The aggregate `releases_created` would be just as wrong, because a
    push that releases one package while the other's PR stays open would skip that PR. The
    per-PR `git diff --quiet uv.lock` check (`:85-88`) already makes an up-to-date PR a no-op.
  - New `build-client` / `publish-client` jobs mirror `build-pypi` / `publish-pypi`
    (`:167-274`). They check out `client_tag_name`, run
    `uv build --package hassette-client --out-dir dist-client`, check the tag version against
    `client/pyproject.toml`, and upload a `client-dists` artifact. They publish from environment
    `release-client` (`url: https://pypi.org/p/hassette-client`, `id-token: write`) with the
    same `skip-existing` retry pattern, then run `gh release edit <tag> --latest=false`. That
    step retries three times like the workflow's other remote mutations, and **fails the job** if
    it still can't apply. It never uses `continue-on-error`, because a silent failure leaves a
    0.x client release as the repo's "Latest" badge.
  - A `route` step on `workflow_dispatch` classifies `inputs.tag_name`: a `v*` tag runs the
    existing jobs, `hassette-client-v*` runs the client jobs, and anything else fails.
  - The existing hassette jobs keep their unprefixed-output gates, which are already root-only.
- **`.github/zizmor.yml`:** the `artipacked` ignore is anchored to `release-please.yml:49`
  (`zizmor.yml:13`), which is already stale: line 49 is now `timeout-minutes: 10`, and the
  `actions/checkout` it covers sits at `:57`. Re-anchor it to the `sync-lockfile` checkout's line
  after this spec's edits, and confirm with `prek -a` (AC#9).
- **`pypi-drift-check.yml:33` and `docker-drift-check.yml:34`:** select the newest non-draft,
  non-prerelease release whose tag matches `^v[0-9]`, via
  `gh release list --json tagName,isDraft,isPrerelease`, instead of `gh release view`.
- **Named convention for "latest release":**
  - A new subcommand in `tools/release/drift_check.py` takes a tag-prefix pattern and prints
    the matching latest tag: `latest-tag --pattern '^v[0-9]'`, or `'^hassette-client-v'` for the
    client drift job. It wraps that `gh release list` query.
  - Every drift job calls it, so the lookup lives in one place.
  - Its docstring states the rule: never resolve "the latest hassette release" with
    `gh release view`, because that returns GitHub's Latest, which can be a client release.
  - A one-line pointer to it goes in `CLAUDE.md` (Documentation Updates).
- **`renovate.json`:** add a `packageRule` matching `client/pyproject.toml` that disables range
  updates.
- **Client verification (FR#38-FR#39):**
  - A new `client-release-verify` job needs `publish-client`. It mirrors `release-verify`
    (`release-please.yml:292-346`): `uv venv` plus
    `uv pip install hassette-client==<version>` with the same retry-on-propagation-delay loop,
    then an import-and-version assertion.
  - `pypi-drift-check.yml` gains a second job for `hassette-client`, pointed at
    `https://pypi.org/pypi/hassette-client/json` and the newest `hassette-client-v*` release, and
    reusing `tools/release/drift_check.py`. That keeps both packages' drift logic in one workflow.
- **`sync-release-notes` stays hassette-only.** The client ships release-please's raw notes.

### Code leverage

| Sub-problem | Existing code | Coverage |
|---|---|---|
| Response shapes | `web/models.py` (`SystemStatusResponse`, `AppManifestListResponse`, `AppManifestResponse`, `AppInstanceResponse`, `ActionResponse`); `types/enums.py` | Partial: reference only; re-declared in the client, because it can't import hassette |
| Status taxonomy | `routes/apps.py` `_run_app_action`, `_validate_app_key`, `_require_known_app`, `_require_valid_instance_index`; `db_degrades_to` | Partial: extended with `ApiProblem` codes; the client mapping is new |
| HTTP client pattern | `cli/client.py` (10 s timeout, redirect-as-forward-auth hint) | Partial: pattern reference only |
| Contract test harness | `tests/integration/web_api/` `client` fixture over `create_fastapi_app(mock_hassette)` | Full: reused |
| Publish jobs | `release-please.yml:167-274` `build-pypi` / `publish-pypi` | Partial: mirrored for the client |

## Implementation Preferences

- **Build and packaging:** the `uv_build` backend with the root's version range; a uv workspace
  member; an explicit `members` list.
- **HTTP:** `aiohttp` only, with an injected session. No `httpx`/`httpx2` in the client.
- **Models:** pydantic v2 (`pydantic>=2.<floor>,<3`), using no feature newer than HA 2026.9's
  pydantic 2.13.
- **Floors:** set to the lowest version whose APIs the client uses, and proven by
  `client_lowest`. They're expected to be well below HA's pins.
- **Errors:** the hierarchy above. `HassetteTimeoutError` subclasses `HassetteConnectionError`
  (approved call-site shape).
- **Lint and types:** the root `ruff.toml`, pyright, house-lint and prek. No
  `from __future__ import annotations`, and `X | None`.
- **Tests:**
  - The client suite uses aiohttp's `aiohttp.test_utils` test server (a real transport), not
    `aioresponses`.
  - `error_from_response` gets table-driven unit tests.

## Replacement Targets

No existing code is being replaced. `HTTPException` raises on the app-action path are converted
to `ApiProblem` in place (Architecture §1), and the CLI's client is untouched.

## Convention Examples

### Error mapping in the action route (the code this spec extends)

**Source:** `src/hassette/web/routes/apps.py:158-170`

```python
    _validate_app_key(app_key)
    _require_known_app(app_key, hassette, action)
    try:
        await operation()
    except AppBootstrapNotReleasedError as exc:
        raise HTTPException(
            status_code=409, detail="App bootstrap prerequisites are not ready yet; retry later"
        ) from exc
    except AppBlockedError as exc:
        raise HTTPException(status_code=409, detail=f"App {app_key!r} is blocked by the --app filter") from exc
    except (ValueError, RuntimeError) as exc:
        LOGGER.warning("Failed to %s app %s", action, app_key, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to {action} app") from exc
```

### Response models document why each field exists

**Source:** `src/hassette/web/models.py:462-474`

```python
class ActionResponse(BaseModel):
    """Response for app mutation endpoints (start/stop/reload).

    ``instance_index`` is the server-confirmed instance the action ran against — ``None`` for
    an app-level action, the validated index for an instance-scoped one. ...
    """

    status: Literal["accepted"] = "accepted"
    app_key: str
    action: str
    instance_index: int | None
```

### Client constants: explicit timeout, documented next steps

**Source:** `src/hassette/cli/client.py:35-40`

```python
DEFAULT_TIMEOUT = 10.0

CLI_AUTH_DOCS_URL = "https://hassette.readthedocs.io/en/stable/pages/cli/configuration/#web-api-token"
"""Where an operator hitting a 401 goes next. The web API credential is a separate concept from
the Home Assistant long-lived token, and nothing in a 401 hints that a second token even exists
unless the message says so."""
```

### Web API route test shape (contract and problem-details tests follow it)

**Source:** `tests/integration/web_api/test_endpoints.py:172-184`

```python
    async def test_start_app_returns_conflict_for_blocked_app(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.app_handler.start_app = AsyncMock(
            side_effect=AppBlockedError("App 'my_app' is blocked by the --app filter")
        )

        response = await client.post(APP_START_PATH)

        assert response.status_code == 409
```

### PyPI publish job (mirrored for the client)

**Source:** `.github/workflows/release-please.yml:226-249`

```yaml
    publish-pypi:
        needs: [release-please, build-pypi]
        if: >-
            always()
            && needs.build-pypi.result == 'success'
        environment:
            name: release
            url: https://pypi.org/p/hassette
        permissions:
            id-token: write
        steps:
            - name: Publish to PyPI (attempt 1)
              id: attempt1
              continue-on-error: true
              uses: pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b # release/v1
              with:
                  skip-existing: true
```

## Alternatives Considered

- **Match the 409 `detail` strings.** Rejected: unpinned, human prose, and a rewording silently
  misclassifies errors in already-published clients.
- **An `X-Hassette-Error` response header.** Rejected in favor of RFC 9457: a body member is the
  industry-standard discriminator, it shows up in OpenAPI, and it's equally additive for the CLI
  and frontend.
- **Move "bootstrap not ready" from 409 to 503 + `Retry-After`.** Semantically more correct, but
  it changes a documented status code. The user chose the scoped problem-details fix; the
  repo-wide follow-up can revisit it.
- **Dataclass models.** Rejected: HA ships pydantic v2. A wide `>=2,<3` range fits its pin, and
  pydantic mirrors hassette's server models directly.
- **Client depends on `hassette`.** Rejected: it drags hassette's full dependency tree into HA's
  constrained environment.
- **Reuse or extend the CLI's sync `httpx2` client.** Rejected: sync, exits the process on
  errors, and not `inject-websession`-compatible.
- **Separate repo for the client.** Rejected: the contract test needs hassette's route harness in
  the same CI run to catch drift before release.
- **Keep release-please's combined release PR.** Rejected: it couples every client release to
  hassette's pending release (181 commits since v0.54.0 at research time).

## Test Strategy

### Required Test Types

- **Unit (client):** the error mapping is a pure function (table-driven), plus model parsing.
  Single module each.
- **Integration (client):** `HassetteClient` against an `aiohttp.test_utils` server, covering real
  transport behavior (redirect not followed, timeout, bearer header, connection refused).
- **Integration (hassette):** problem-details bodies through the FastAPI app, and the contract
  test crossing the server/client boundary.
- **Floor verification:** `client_lowest`.
- **Gap:** the release workflow itself isn't testable locally beyond lint (zizmor/actionlint),
  the config-invariant check (AC#11), and the `--dry-run` process step.

### Existing Tests to Adapt

- `tests/integration/web_api/test_endpoints.py:163-225, 325-365` assert only status codes for
  409 and 404, so they stay green unchanged (AC#2). No edits are required.
- `tests/integration/web_api/` tests for `/apps/{app_key}/manifest|config|source` 400 paths:
  status-only assertions, unaffected by those routes' 400 now emitting problem details.

### New Test Coverage

- `tests/integration/web_api/test_problem_details.py` also asserts
  `Content-Type: application/problem+json` and `code: invalid_app_key` on the 400 from each of
  the three GET routes (FR#1), so that shared-helper behavior is pinned, not incidental.
- `tests/integration/web_api/test_problem_details.py` covers every FR#4 code, including both
  instance-level 404s (unknown app via `:125`, out-of-range index via `:130`) and both 409s
  (FR#1-FR#6).
- `tests/integration/web_api/test_client_contract.py` covers:
  - real `/api/health`, `/api/apps/manifests` (with a manifest per `ManifestStatus` value) and
    action 202 bodies → client models;
  - every FR#4 error path → `error_from_response` → the expected subclass (FR#11-FR#13,
    FR#16-FR#22);
  - the 503 degraded manifests body → `HassetteUnavailableError` (FR#20).
- `client/tests/test_errors.py` is a table over (status, body, headers), including a non-JSON
  body, an HTML 502, a 409 with no code, a 409 with `code: bootstrap_not_released` but
  `Content-Type: application/json` (→ plain `HassetteConflictError`), and a 3xx (FR#10,
  FR#16-FR#22, FR#25, FR#40).
- `client/tests/test_models.py` covers unknown field ignored, unknown enum → `UNKNOWN`, and a
  missing required field → `HassetteResponseError` (FR#22-FR#24).
- `client/tests/test_client.py` uses a real aiohttp test server and covers:
  - a connect-level timeout (`aiohttp.ServerTimeoutError`, e.g. via `ClientTimeout(sock_connect=...)`
    against a non-accepting socket) → `HassetteTimeoutError`, not only an overall-request timeout
    (FR#15);
  - bearer header sent with a token, and no `Authorization` header at all with `token=None` or
    `""` (FR#8); timeout → `HassetteTimeoutError` (FR#9, FR#15);
  - 302 not followed (FR#10); connection refused (FR#14);
  - session not closed after use (FR#7);
  - base URL with a subpath and trailing slash; `app_key` path encoding.
- The `check_release_please_config.py` self-test fixtures cover a passing config and one
  violation per invariant (AC#11).

### Tests to Remove

No tests to remove.

## Documentation Updates

- **New `docs/pages/web-ui/api-errors.md`:** the problem-details format and one anchored section
  per code (`#invalid_app_key` … `#action_failed`), each giving its meaning and whether it's
  retryable. Every `type` URI points here. Linked from `docs/pages/web-ui/health-endpoints.md`
  and the mkdocs nav.
- **`client/README.md`:** install, the approved call sites as a quick start, the exception table,
  and the compatibility policy (0.x, additive-only server changes, unknown enum → `UNKNOWN`).
  It's the PyPI long description.
- **`CLAUDE.md` (Architecture → Api or a new "Client library" note):**
  - the workspace layout and the `client` nox sessions;
  - the rule that the client never imports hassette;
  - the two release trains;
  - the rule to resolve the latest hassette release via `drift_check.py latest-tag`, never
    `gh release view`.
- **`.claude/rules/changelog-quality.md` and `.claude/commands/changelog-review.md`:** release
  PRs are now per-package (a hassette PR and a `hassette-client` PR). The release-body-format
  warning applies to both.
- **`scripts/export_schemas.py --types`:** regenerate `frontend/openapi.json` and
  `generated-types.ts` for the new `ProblemResponse` error schemas.

## Impact

### Changed Files

- modify `pyproject.toml`: workspace, sources, `test` group, `norecursedirs`, house-lint include
- modify `uv.lock`: regenerated
- modify `release-please-config.json`: `separate-pull-requests`; root `exclude-paths` /
  `include-component-in-tag`; `client` package
- modify `.github/workflows/release-please.yml`: outputs, `sync-lockfile` matrix, client
  build/publish jobs, `client-release-verify` (FR#38), dispatch routing
- modify `.github/zizmor.yml`: move the `artipacked` anchor
- modify `.github/workflows/pypi-drift-check.yml`, `.github/workflows/docker-drift-check.yml`:
  `v*`-only release selection; `pypi-drift-check.yml` also gains the `hassette-client` job
  (FR#39)
- modify `.github/workflows/tests.yml`: `client/**` filter; client and client_lowest job
- modify `.github/workflows/lint.yml`: `client/**` filter
- modify `Dockerfile`: `ADD ./client/pyproject.toml`
- modify `pyrightconfig.json`: include `client/src`
- modify `prek.toml`: house-lint `files` regex; new `check-release-please-config` hook
- modify `renovate.json`: client `packageRule`
- modify `noxfile.py`: `client`, `client_lowest` sessions
- create `src/hassette/web/problems.py`: `ApiProblem`, handler, `ProblemResponse`, code table
- modify `src/hassette/web/app.py`: register the handler
- modify `src/hassette/web/routes/apps.py`: raise `ApiProblem` on the action path; `responses=`
  docs
- modify `frontend/openapi.json`, `frontend/src/api/generated-types.ts`: regenerated
- create `client/pyproject.toml`, `client/README.md`,
  `client/src/hassette_client/{__init__,client,errors,models}.py`,
  `client/src/hassette_client/py.typed`, `client/tests/{__init__,conftest,test_client,test_errors,test_models}.py`
- create `tools/check_release_please_config.py` (+ its tests under `tests/unit/tools/`)
- modify `tools/release/drift_check.py`: `latest-tag --pattern` subcommand (the single
  "latest release" lookup)
- create `tests/integration/web_api/test_problem_details.py`,
  `tests/integration/web_api/test_client_contract.py`
- create `docs/pages/web-ui/api-errors.md`; modify `docs/pages/web-ui/health-endpoints.md`,
  `mkdocs.yml`
- modify `CLAUDE.md`, `.claude/rules/changelog-quality.md`,
  `.claude/commands/changelog-review.md`

### Behavioral Invariants

- Hassette release: tag format `vX.Y.Z`, PR title `chore(main): release X.Y.Z`, `CHANGELOG.md`,
  the Docker image contents, and the `hassette` PyPI package are unchanged.
- The app-action 202 `ActionResponse` is unchanged, and every error keeps its status code and
  `detail` string (CLI and frontend error display unchanged).
- `uv sync --no-default-groups` (Docker) installs no client. The `hassette` wheel doesn't contain
  `hassette_client`.
- `codegen/` keeps its own lock and stays out of the workspace.
- Root pytest collection and root coverage (`source = ["hassette"]`) are unchanged.

### Blast Radius

- **Release pipeline:** the highest-risk surface, exercised only on a real release. It's
  mitigated by the config-invariant check, the dry run, and leaving the unprefixed root-output
  gates as they are.
- **Web API consumers:** the error content type changes to `application/problem+json` on the
  action routes (and the 400 of three GET routes). Both first-party consumers parse
  `detail` regardless of content type. Third-party scripts see only extra members.
- **Every dev environment:** `uv sync` now installs the client editable, and the lockfile
  changes once.
- **Downstream:** unit C consumes this library, and D pins a release that depends on it.

## Open Questions

- **Exact dependency floors** for `aiohttp` and `pydantic`: set to the lowest versions whose APIs
  the implementation actually uses, then proven by `client_lowest` (AC#4). The implementing task
  owns this. It must also confirm the floors are at or below the pins of whatever minimum HA
  version C chooses; if C hasn't chosen yet, stay at or below HA 2026.9.2's pins.
- **`PROBLEM_DOCS_URL` base:** `stable` vs `latest` readthedocs path. The implementing task
  matches whatever `CLI_AUTH_DOCS_URL` uses (`/en/stable/`) unless the docs page won't exist on
  `stable` until release. In that case it still uses `stable`, because a `type` URI is an
  identifier first and resolves once released.
