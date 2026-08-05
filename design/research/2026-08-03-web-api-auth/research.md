---
proposal: "Add authentication to the hassette web API and settle the default-bind question, in a way that stays compatible with the planned HA add-on's ingress-first exposure model (issue #1117, epic #71)."
date: 2026-08-03
status: Draft
flexibility: Leaning
motivation: "Hassette runs on the user's own VPS. They want to reach it from their own network without hassette becoming an open port into the whole box. Defense in depth, not just a login screen."
constraints: "Must not conflict with ADR-0005's ingress-first add-on model. Must not silently break existing `docker run -p` deployments. Single-operator self-hosted tool — no enterprise auth patterns. Ship soon."
non-goals: "RBAC, multi-user accounts, OAuth/OIDC, JWT lifecycles, multi-tenant isolation."
depth: deep
---

# Research Brief: Web API Authentication and Safe Default Bind

**Initiated by**: GitHub issue #1117 — "Add authentication and a safe default bind to the web API" (`priority:high`, `release:v1.0.0`, `size:large`).

## Context

### What prompted this

The web API has no inbound authentication of any kind. This was first filed as a MEDIUM finding in the 2026-03 audit ("No Rate Limiting on App Mutation Endpoints", `design/audits/2026-03-25-comprehensive-audit/web-frontend.md:173-188`) and upgraded by the 2026-06 retrospective to **"CONFIRMED — worse"** (`design/audits/2026-06-22-project-retrospective/audit.md:57`), which enumerated the source-disclosure endpoint, the handshake-free WebSocket, and the `0.0.0.0` default bind alongside the original finding. #1117 is that upgrade.

The user's deployment is a personal VPS. The question they actually care about is not "does the dashboard need a login page" but "if this port is reachable, what does an attacker get, and can it be a stepping stone into the rest of the box?" That framing changes the answer materially — see [VPS Threat Model](#vps-threat-model).

### Current state

**Confirmed by reading the code — this is greenfield.** `git log --all` shows no prior auth attempt (the two `update auth` commits, `bc3b2f11` / `af2c74ab`, touch `volumes/config/.storage/auth`, Home Assistant's own storage file in a dev fixture). Grep confirms zero hits for `fastapi.security`, `APIKeyHeader`, `HTTPBearer`, `OAuth2` anywhere in `src/`. Every `auth`/`bearer`/`token` hit in `src/` is hassette authenticating *outbound* to Home Assistant, not protecting itself.

| Layer | Today |
|---|---|
| Middleware stack (`src/hassette/web/app.py:53-59`) | **CORS only.** No custom ASGI middleware, no `BaseHTTPMiddleware`, no `@app.middleware("http")` anywhere in `src/hassette/web/`. An auth layer establishes the first one. |
| DI helpers (`src/hassette/web/dependencies.py`) | Five `Depends()` accessors (`get_hassette`, `get_runtime`, `get_telemetry`, `get_scheduler`, `get_api`), all reading `request.app.state.hassette`. No identity concept. |
| Exception handling | **No global exception handler** (`grep exception_handler` → nothing). Domain errors are mapped inline, e.g. `_raise_bootstrap_not_released` (`apps.py:67-69`) → 409. |
| Bind (`src/hassette/config/models.py:342`) | `host: str = Field(default="0.0.0.0")` → `uvicorn.Config(host=...)` in `core/web_api_service.py:65-73`. |
| CORS | `allow_credentials=True` with `cors_origins` defaulting to `("http://localhost:3000", "http://localhost:5173")`. `Authorization` is **already** in `allow_headers` — a bearer scheme needs no CORS change. |
| Frontend REST (`frontend/src/api/client.ts:3,16`) | `BASE_URL = "/api"`, plain `fetch`, same-origin, one central `apiFetch` wrapper. |
| Frontend WS (`frontend/src/hooks/use-websocket.ts:42`) | `new WebSocket(\`${proto}//${location.host}/api/ws\`)`. Native browser `WebSocket` — **cannot set request headers.** |
| CLI (`src/hassette/cli/client.py:245-252`) | Builds its own `HassetteConfig(token=None)`, derives `base_url` from `web_api.host`/`port` (rewriting `0.0.0.0`→`127.0.0.1`), and sends **no credential at all**. |
| Docs | `docs/pages/web-ui/index.md:17-24` already carries a `!!! warning "No authentication"` block telling users to set `host = "127.0.0.1"` or put a reverse proxy in front. |

The full endpoint inventory, with mutation endpoints marked:

| Mutates | Endpoint | Effect |
|---|---|---|
| ✅ | `POST /api/apps/{key}/start` (`apps.py:156`) | Starts an app |
| ✅ | `POST /api/apps/{key}/stop` (`apps.py:170`) | Stops an app |
| ✅ | `POST /api/apps/{key}/reload` (`apps.py:187`) | Re-imports app source from disk, `force_reload=True` |
| ✅ | `POST /api/scheduler/jobs/{id}/trigger` | Fires a scheduled job immediately |
| ✅ | `PUT /api/logs/level` (`logs.py:54`) | `logging.getLogger(body.logger).setLevel(...)` — process-wide, any logger name |
| | `GET /api/apps/{key}/source` (`apps.py:286`) | Raw app source code (path-traversal guarded to `app_dir`) |
| | `GET /api/config`, `GET /api/apps/{key}/config` | Full config dump, `SecretStr` fields masked |
| | `GET /api/logs/recent`, `/api/telemetry/*`, `/api/bus/listeners`, `/api/scheduler/jobs`, `/api/executions/*` | Read-only telemetry |
| | `WS /api/ws` (`ws.py:85`) | `websocket.accept()` with no check; broadcast-only downstream |
| | `GET /api/health`, `/health/live`, `/health/ready` | Liveness/readiness/system status |

Two of those mutation endpoints — `POST /api/scheduler/jobs/{id}/trigger` and `PUT /api/logs/level` — are **not listed in #1117**. The issue's acceptance criteria say "at minimum gating the mutation endpoints, `/source`, `/config`, and `/api/ws`"; a default-deny posture covers them, an endpoint-by-endpoint allowlist would miss them.

### Key constraints

- **ADR-0005 (Accepted) commits to ingress-first exposure** and states plainly: *"The hassette web API has no authentication. Any exposure model must not widen that gap."* (`design/adrs/0005-ha-addon-packaging.md:17`). Its rejected alternative — direct-port-only — was rejected specifically because it "exposes the auth-less UI on the LAN as the *only* access path."
- **Prereq-03 (`web_api.allowed_client_ips`) is designed but not built.** Grep confirms the string appears only under `design/` — no hits in `src/`, `frontend/`, `tests/`, `docs/`. Its own doc says: *"this is not authentication and must not be described as such… The real auth layer remains the audit gap's follow-up"* (`prereq-03-ingress-source-guard.md:31-35`). Nothing is built yet to conflict with.
- **Home Assistant's add-on docs are explicit** about ingress add-ons: *"Users are previously authenticated via Home Assistant. Authentication is not required."* and *"Only connections from `172.30.32.2` must be allowed. You should deny access to all other IP addresses within your app server."*
- **Browser `WebSocket` cannot set request headers.** This is a hard constraint of the browser API, not an implementation choice, and it is the single fact that shapes the whole design.
- **380+ existing tests** touch the HTTP/WS surface: ~211 integration (`tests/integration/web_api/`, 12 files), ~165 Playwright e2e (`tests/e2e/`, 14 files), 6 system. Blast radius management is a first-class design concern, not an afterthought.
- Single operator, personal tool, `solo` developer. Correct and hard-to-misuse beats feature-complete.

---

## VPS Threat Model

Answering question 2 directly, and pushing back on the implicit framing that `/source` disclosure is the headline risk.

### What an unauthenticated peer can do today

**Reconnaissance (moderate value).** `GET /api/apps/{key}/source` returns raw app source. It is path-traversal guarded (`apps.py:302-309` resolves both sides and checks containment), so it is scoped to files under the manifest's `app_dir` — no arbitrary file read. But app source is where users hardcode entity IDs, device IPs, third-party API endpoints, and — realistically — credentials they didn't route through config. `GET /api/config` adds the HA `base_url`, `config_dir`/`data_dir` filesystem paths, and every app's non-secret config in plaintext. `GET /api/logs/recent` (up to 2000 records) adds tracebacks with absolute paths and library versions.

**The HA token is not disclosed.** Verified at two layers: `HassetteConfig.token` is `SecretStr` (`config/config.py:142-146`), so Pydantic's `model_dump(mode="json")` already renders `"**********"`; then `mask_values` (`web/config_view.py:74-98`) independently replaces anything with `writeOnly: true` / `format: "password"` with `MASK_SENTINEL`. There is a system test asserting the plaintext token never appears in the response body (`tests/system/test_web_api.py:75-93`). Masking is **type-driven**, though — a secret held in a plain `str` app-config field leaks in full. App authors write their own `AppConfig` classes, so that is a live gap (and is what #708 is about).

**Actuation — this is the actual headline risk.** Hassette holds a long-lived HA token that is, for most users, full-admin. An unauthenticated network peer can `start`/`stop`/`reload` any app and `trigger` any scheduled job on demand. That means forcing hassette to execute the user's own automation code — the code that calls `lock.unlock`, `light.turn_on`, `cover.open_cover`. **An unauthenticated peer gets indirect actuator control of the user's home**, mediated through hassette's HA credential. For a VPS-hosted hassette pointed at a home HA instance, that is sharper than source disclosure by a wide margin.

**Denial of service.** `PUT /api/logs/level` sets any logger to DEBUG process-wide. Log records flow into stdout *and* the telemetry SQLite DB via `LogPersistenceHandler`. Unbounded start/stop/reload loops have no rate limit. Combined, this is a cheap disk-fill and CPU sink — relevant on a VPS specifically, where disk exhaustion takes down neighbours.

### Is it a stepping stone into the broader VPS?

**Not directly.** The API exposes no file write, no shell, no arbitrary file read, and no unparameterised SQL surface. There is no path from these endpoints to code execution by themselves. *(Inferred — from reading every route module; I did not attempt exploitation.)*

**But it removes a step from any chain that has a write primitive.** `reload_app` runs `force_reload=True`, deliberately re-importing app source from disk (`apps.py:191-193`, added for #1005). Any *other* way to land a file in the apps directory — a sibling container sharing the volume, a Samba/File Editor share in the add-on scenario, an app of the user's own that writes files, a compromised CI push — is converted from "wait for a restart" into "trigger execution on demand." *(Inferred; the chain is plausible and the mechanism is real, but no such write primitive was found in hassette itself.)*

**On a shared VPS, the "otherwise fine" premise is what fails.** Other containers on the same Docker bridge, or another tenant's process, reach `0.0.0.0:8126` without traversing the firewall. Firewalling the public interface does not close that path — only a credential (or a loopback bind) does.

### Things to worry about beyond "add a credential check"

These are specific to this codebase, not generic hardening advice.

1. **The auth token must be `SecretStr`, or `/api/config` discloses the credential that protects it.** `GET /api/config` dumps the entire `HassetteConfig`. Masking is driven by Pydantic's `writeOnly`/`format: password` markers, which only appear for `SecretStr`. A plain `str` field named `auth_token` would be returned verbatim to any authenticated client — and, worse, would be in the response the moment auth is misconfigured. Declaring it `SecretStr` gets both masking layers for free. *(Direct — from reading `config_view.py:74-98` and the existing `token` field.)*

2. **A token in a query string lands in uvicorn's access log.** `uvicorn.Config` is constructed in `core/web_api_service.py:65-73` with no `access_log=False` and no `log_config=` override, so uvicorn's default access logger is active and logs the full request line including the query string. It goes to stdout → the Docker container log → (in the add-on) the Supervisor log viewer that the user reads in the HA UI. *(Supported: the config call site has no override, and uvicorn's documented default is `access_log=True`. I did not run the server to observe a logged line.)* Note the blast radius is bounded: `LogCaptureHandler`/`LogPersistenceHandler` attach to the `"hassette"` logger (`core/logging_service.py:60,97`), which does not receive `uvicorn.access` records — so a leaked token would **not** be served back through `/api/logs/recent`. Still disqualifying for the WS design.

3. **Use `secrets.compare_digest`.** A naive `==` on a token is a remote timing oracle. Stdlib, zero cost, no new dependency.

4. **Adding a *cookie* creates a CSRF requirement that does not exist today.** Right now CSRF is meaningless — there is no credential for a cross-site request to ride. `SameSite=Strict` plus the fact that all mutations are POST/PUT covers the ordinary case. But note `cors_origins` defaults to `http://localhost:3000` and `http://localhost:5173` with `allow_credentials=True`: those are *same-site* with `localhost:8126`, so `SameSite=Lax` would not block them. Any local dev server on those ports could ride a session cookie. A bearer header is inherently CSRF-immune (a cross-origin page cannot set it without a preflight CORS refuses).

5. **`allow_credentials=True` + a `"*"` origin.** The audit's finding #8, still open. Starlette rejects the combination at request time with a confusing error rather than at startup. Cheap to add a config validator.

6. **Health endpoints must stay reachable.** The documented compose healthcheck is `curl -sf http://127.0.0.1:8126/api/health/live` (`docs/pages/getting-started/docker/snippets/docker-compose.yml:20`), and ADR-0005's T1 points the add-on watchdog at the same URL. Gating `/api/health/live` breaks both.

---

## Feasibility Analysis

### What would need to change

| Area | Files | Effort | Risk |
|---|---|---|---|
| Config | `src/hassette/config/models.py` (`WebApiConfig` + validators), `hassette.schema.json` regen | Low | Low — additive fields |
| Auth core | New `src/hassette/web/auth.py` (token resolution, `compare_digest`, trusted-peer check), new exceptions in `src/hassette/exceptions.py` | Low | Low |
| Wiring | `src/hassette/web/app.py` (one `add_middleware` or router-level `dependencies=[...]`), `src/hassette/web/dependencies.py` (`AuthDep`) | Low | **Medium — 89 commits touch `web/` ; high-churn area, merge conflicts likely** |
| Token provisioning | `src/hassette/core/web_api_service.py` or a small helper — generate + persist `<data_dir>/.web_api_token` at 0600, log once | Low | Medium — first-run behavior, file permissions, add-on `/data` semantics |
| WebSocket | `src/hassette/web/routes/ws.py` — pre-`accept()` check, ~6 lines | Low | Low |
| Login exchange | New route `POST /api/auth/session`; a minimal login view in the SPA | Medium | Medium — new UI surface |
| Frontend | `frontend/src/api/client.ts` (one central `apiFetch`), a 401 → login redirect, `use-websocket.ts` (no change if cookie-based) | Low | Low — client is centralized |
| CLI | `src/hassette/cli/client.py` — read token from config/file/`--token`, attach header | Low | Low |
| Tests | `src/hassette/test_utils/web_mocks.py` (stub gains the new fields), `tests/integration/web_api/conftest.py:61-66` (one fixture), `tests/e2e/conftest.py` (`base_url`/`browser_context_args`) | Medium | **High if auth defaults on in tests — 380+ functions**; low if the stub defaults it off and a dedicated suite covers auth |
| Docs | `docs/pages/web-ui/index.md` (rewrite the "No authentication" warning), `cli/configuration.md`, `getting-started/docker/*`, `troubleshooting.md` | Medium | Low |

### What already supports this

- **`Authorization` is already in the CORS `allow_headers` list** (`app.py:58`). No CORS change needed for a bearer scheme.
- **The frontend HTTP client is one function.** `apiFetch` (`client.ts:16`) is the single fetch call site; every request routes through it. One `credentials: "same-origin"` and one 401 handler covers the whole SPA.
- **Both the SPA and the WS are same-origin.** `client.ts` uses relative `/api`; `use-websocket.ts` builds from `location.host`. A cookie is attached automatically to both by the browser with **zero code change** in `use-websocket.ts`.
- **`SecretStr` + two-layer masking is an established, tested pattern** (`config_view.py`, `tests/system/test_web_api.py:75-93`). A new secret field inherits it by declaring the right type.
- **The `Depends()` idiom is pervasive.** `HassetteDep`, `RuntimeDep`, etc. are already how routes get their collaborators — an `AuthDep` slots into an existing convention rather than inventing one.
- **The integration test client is one fixture** (`tests/integration/web_api/conftest.py:61-66`). ~211 tests are covered by one edit.
- **No new dependency is needed.** FastAPI 0.136.3 ships `fastapi.security` (`APIKeyHeader`, `HTTPBearer`); `secrets` and `hmac` are stdlib. A JWT scheme *would* need a new dep (`pyjwt`/`python-jose`, neither present) — one more reason not to reach for one.

### What works against this

- **No middleware precedent.** The first custom middleware in the project. Middleware ordering versus `CORSMiddleware` matters (CORS must run outermost so preflight `OPTIONS` is answered *before* the auth check rejects it, otherwise browsers report opaque CORS failures instead of 401s).
- **No global exception handler.** Every error-to-status mapping today is hand-written inline. An auth failure needs its own explicit mapping; there is no central place to register it.
- **`InvalidAuthError` is taken** (`exceptions.py:140`) and means something else: HA rejected *hassette's* outbound token. It is a `FatalError` subclass wired into `websocket_service.py`'s `NON_RETRYABLE` tuple (line 64) and its restart spec. Reusing the name would be semantically wrong and would collide with existing `except InvalidAuthError` handling at `websocket_service.py:428`. New exceptions must be plain `HassetteError` subclasses under different names.
- **`lifespan="off"`** in the uvicorn config means FastAPI startup events don't run. Any init-on-start work (loading/generating the token) must hook `WebApiService.on_initialize()` / `serve()`, not a FastAPI lifespan.
- **`WebApiService.restart_spec` is TRANSIENT (3/60s).** In-process-only auth state (a session table, nonce store) is wiped on a service restart, silently logging every browser out. Argues for stateless or file-backed credentials.
- **The e2e suite is the sharp edge.** 165 Playwright tests navigate `base_url` with no credentials (`tests/e2e/conftest.py:298-359`), and `tests/e2e/test_websocket.py` uses a real browser WebSocket that *cannot* carry a header. Whatever the design, e2e must be able to establish the credential the way a browser does.
- **The `0.0.0.0` default is load-bearing for Docker** — see [Default Bind](#default-bind).

---

## Options Evaluated

### Option A (recommended): Static bearer token, on by default, auto-generated; browser exchanges it once for a session cookie

**How it works.**

The credential of record is a single high-entropy static token — one operator, one secret. `WebApiConfig` gains `auth_token: SecretStr | None = None` and `auth_enabled: bool = True`. Resolution order at startup: explicit config/env value → the persisted file at `<data_dir>/.web_api_token` → generate `secrets.token_urlsafe(32)`, write it 0600, and log it once at INFO with a copy-paste-ready URL. That last branch is the important one: it means a fresh install is authenticated **with zero user configuration**, which is what makes keeping the `0.0.0.0` bind defensible.

Every `/api/*` route is default-deny except `/api/health/live` and `/api/health/ready`. Non-browser clients (CLI, curl, scripts, monitoring) send `Authorization: Bearer <token>`; the check is `secrets.compare_digest`. That covers the CLI with a one-line header addition in `cli/client.py`.

The browser is the interesting case, because a native `WebSocket` cannot send that header. So the SPA does the exchange once: a minimal login view POSTs the token to `POST /api/auth/session`, which validates it and replies `Set-Cookie: hassette_session=<value>; HttpOnly; SameSite=Strict; Path=/; Secure-when-https`. From then on the browser attaches the cookie automatically to same-origin `fetch` **and** to the `/api/ws` handshake. `use-websocket.ts` needs no change at all; `client.ts` needs `credentials: "same-origin"` and a 401 → show-login handler. The session value should be derived from the token (e.g. an HMAC over a random session id keyed by the token) rather than stored in a dict, so a `WebApiService` restart doesn't log everyone out.

A third config field, `web_api.trusted_proxies: tuple[str, ...] = ()`, marks peer IPs whose requests are treated as already authenticated because an upstream authenticated them. This is the ingress answer (`172.30.32.2`) and simultaneously the answer for the reverse-proxy-with-basic-auth deployment the docs already recommend (`docs/pages/web-ui/index.md:23-24`). Entries parse as IPs or CIDRs via `ipaddress` at config load, so a typo fails at startup, not at request time.

Finally, a startup guard: if `auth_enabled = false` **and** `host` is not loopback, refuse to start with a message naming both settings. This is the issue's AC #3 satisfied through its "or require explicit opt-in to bind on non-loopback interfaces" branch, without breaking anyone.

**Pros**
- Nothing breaks for existing Docker users. The bind stays `0.0.0.0`; `docker run -p 8126:8126` keeps working; the compose healthcheck against `/api/health/live` keeps working.
- Zero-configuration security. The user upgrades, reads one log line, pastes a token once. Compare to "change your bind, then figure out why the UI stopped loading."
- The WS problem is solved by the *same* mechanism as REST, with no header smuggling, no query string, no first-message handshake. `use-websocket.ts` is untouched.
- Bearer-header clients are CSRF-immune by construction; cookie clients are protected by `SameSite=Strict` on a single-page same-origin app that has no cross-site flows to preserve.
- Ingress works with no hassette-visible credential and no add-on-user-facing config, which is exactly what ADR-0005's D1/T5 wanted.
- No new dependencies.
- `trusted_proxies` serves the add-on and the reverse-proxy user with one field — it is not add-on-specific code, which is the bar ADR-0005 set for the other prereqs.

**Cons**
- Two credential transports (header + cookie) is more surface than one. Each needs its own test.
- A login view is new UI. Small, but it is a screen that must handle a wrong token, a cleared cookie, and the ingress case where it should never appear.
- The persisted token file lands in `/data`, which the add-on includes in HA backups. A backup now contains a live credential. Mitigable (regenerate on restore, or note it in DOCS.md), but real.
- The cookie `Path` interacts with prereq-01's base-path work — see [Concerns](#concerns).
- Rotating the token invalidates all sessions with no in-app "regenerate" affordance in v1 (delete the file and restart).

**Effort estimate:** Medium. The auth core, config, WS check, and CLI are each small and independent. The login view and the test-suite plumbing are where the time goes. Sequencing as verifiable units: (1) config fields + token resolution + startup guard, no enforcement; (2) enforcement + integration tests, stub defaults auth off; (3) WS check; (4) login view + cookie + one e2e; (5) CLI; (6) docs.

**Dependencies:** None. FastAPI's `fastapi.security` and stdlib `secrets`/`hmac`/`ipaddress` cover it.

### Option B (lightweight alternative): Header-only bearer token, no cookie; WS token via `Sec-WebSocket-Protocol`

**How it works.** Same static token, same `compare_digest`, same default-deny. But no session endpoint and no cookie. The SPA holds the token in memory (prompted once, optionally persisted to `sessionStorage`) and attaches it in `apiFetch`. For the WebSocket, the token rides the one header a browser *can* set — `new WebSocket(url, ["hassette.bearer." + token])` — and the server reads it from `Sec-WebSocket-Protocol` and echoes the accepted subprotocol back.

**Pros**
- One credential transport, one code path, materially less to test.
- Strictly CSRF-immune; no cookie, no `SameSite` reasoning, no interaction with the `cors_origins` localhost defaults.
- No login-session concept at all — nothing to invalidate on a `WebApiService` restart.
- No cookie `Path` interaction with prereq-01's ingress base-path work.

**Cons**
- Subprotocol smuggling is a known-but-ugly workaround: it abuses a header whose purpose is protocol negotiation, and it confuses proxies and debugging tools. The HA ingress proxy's subprotocol forwarding behavior would need verification before committing.
- Storing a long-lived credential in `sessionStorage` puts it in reach of any XSS. `HttpOnly` cookies exist precisely to prevent that. The SPA renders user-authored log messages and app source, so XSS is not a purely theoretical concern here.
- Requires touching `use-websocket.ts`, which Option A does not.
- The e2e suite must inject the token into both the page context *and* the WS constructor.

**Effort estimate:** Small-to-Medium — genuinely less code than Option A, but the subprotocol path needs verification against the ingress proxy that Option A's cookie does not.

**Dependencies:** None.

### Considered and rejected: delegate auth entirely to a reverse proxy

This is what the docs recommend today (`docs/pages/web-ui/index.md:23-24`). It is not sufficient, for three specific reasons. First, it does nothing for the shared-VPS case — a sibling container reaches `0.0.0.0:8126` directly without passing through Caddy. Second, ADR-0005 already rejected the equivalent posture for the add-on's direct-port path. Third, it pushes the entire security model onto a component hassette does not ship, test, or document beyond one sentence — which for a `release:v1.0.0` issue is not a security model, it is a disclaimer. It remains a good *complement* (and `trusted_proxies` supports it), not a substitute.

---

## prereq-03's Fate

**Recommendation: fold prereq-03 into this work as `web_api.trusted_proxies` and close it as a standalone deliverable.**

The reasoning, in order of weight:

1. **Its stated purpose evaporates.** Prereq-03 exists *because* there is no auth — its own doc says so in as many words: *"Since the web API is unauthenticated, the guard is what makes 'ingress-only' actually mean supervisor-authenticated-only inside the add-on's docker network"* (`prereq-03-ingress-source-guard.md:12-15`). With real auth, "ingress-only" is enforced by the credential, not by the peer address.

2. **A peer-IP allowlist is a *weaker* guarantee than a token, not an additive one.** The threat prereq-03 defends against is a sibling add-on on the shared `hassio` Docker bridge reaching `hassette:8126` directly, bypassing ingress. Against that adversary, an IP check is defeated by IP spoofing on a bridge network (feasible for a container with `NET_RAW`); a token is not. Stacking a weaker check on a stronger one adds a config field, a middleware, and a failure mode without adding a guarantee. *(Inferred — the spoofing claim is standard Docker bridge behavior; I did not test it against a Supervisor network.)*

3. **`trusted_proxies` is strictly better than `allowed_client_ips` for the add-on's own escape hatch.** Under prereq-03's design, opting into the host port drops the guard entirely and reproduces today's unauthenticated LAN exposure — which is why ADR-0005 has to document that path as unauthenticated. Under `trusted_proxies`, mapping the host port leaves LAN clients needing a token. The add-on gets *safer*, and ADR-0005's "documented as unauthenticated" caveat can be retired.

4. **Two guards, two ways to get it wrong.** With both fields, `run.sh` sets two things that must agree; a mismatch either locks out ingress or opens the door. One field, one decision.

**The one counterargument, stated fairly:** HA's add-on docs say *"Only connections from `172.30.32.2` must be allowed. You should deny access to all other IP addresses within your app server."* That is a documented requirement, and `trusted_proxies` does not deny non-listed peers — it just makes them present a token. If that requirement is enforced in add-on review, or if belt-and-braces is wanted anyway, add a boolean `web_api.deny_untrusted_peers: bool = False` to the *same* middleware rather than a second IP-list field. That is roughly ten additional lines and preserves the one-field, one-decision property. I would build the boolean only if add-on review actually asks for it — note that with `ports: 8126/tcp: null` (the shipped default per ADR-0005), nothing outside the container can reach the port anyway except the gateway and other containers on the network.

**Concrete downstream edits this implies:**
- `prereq-03-ingress-source-guard.md` → marked superseded, pointing at this brief.
- `prereq-04-addon-repo-skeleton.md:26` and `research.md:182` — `run.sh` step 4 exports `HASSETTE__WEB_API__TRUSTED_PROXIES` instead of `ALLOWED_CLIENT_IPS`. It should set this **unconditionally** (the ingress gateway is always trusted), not conditionally on the port-mapping query — which also removes the `hassio_api: true` / `addons/self/info` lookup from `run.sh` entirely, simplifying prereq-04.
- `research.md:266` — *"the direct-port path remains unauthenticated by design in v0.1"* becomes false. ADR-0005 needs a follow-up note or a superseding ADR.
- `research.md:293` open question, *"Ingress + `hassette` CLI"* — partially answered: with a token the CLI works over the mapped port from anywhere, no ingress-aware transport needed.

---

## WebSocket Auth

Answering question 4 concretely.

**Recommended mechanism: read the session cookie (or a bearer header, for non-browser clients) from the upgrade request and validate it *before* `websocket.accept()`.**

```
# src/hassette/web/routes/ws.py — before the existing accept() at line ~86
if not authorize_ws(websocket, hassette.config.web_api):
    await websocket.close(code=1008)   # 1008 = policy violation
    return
await websocket.accept()
```

Starlette exposes `websocket.cookies` and `websocket.headers` on the `WebSocket` object during the handshake, so this is a pre-accept check with no protocol gymnastics. Non-browser clients (`websockets.connect(..., additional_headers={"Authorization": ...})`, as used by `tests/system/test_web_api.py:132`) send the bearer header; browsers send the cookie. Both paths converge on the same validator.

Why the alternatives lose, for reasons specific to this codebase:

- **Token in a query param (`/api/ws?token=…`)** — uvicorn's access logger is on by default and logs the query string (see threat model item 2). In the add-on that log is displayed in the HA Supervisor UI. Disqualifying, and it would additionally require passing `access_log=False` or a redacting `log_config` to `uvicorn.Config`, which is a real cost for a real regression in observability.
- **`Sec-WebSocket-Protocol` smuggling** — works, and is Option B's answer, but it is unnecessary once a cookie exists, and its behavior through the Supervisor's ingress proxy is unverified.
- **First-message auth** (accept, then wait for an `{"type":"auth"}` frame) — this is what hassette itself does as a *client* against Home Assistant (`core/websocket_service.py:812-820`), so there is precedent. But it means holding a half-authenticated accepted socket, and the current handler starts an `anyio` task group immediately after `accept()` (`ws.py:85-109`) — adding a pre-task-group auth state machine is strictly more code than a pre-accept check, for no gain.

**Through the ingress proxy.** Under ingress the browser is inside the HA frontend, already authenticated by the Supervisor, and the peer address hassette sees is `172.30.32.2`. With `trusted_proxies` containing that address, the WS check short-circuits before any cookie is consulted — the add-on user never sees a hassette credential. HA's ingress supports WebSockets natively (`research.md:107`), and no hassette-level token needs to survive the proxy hop.

**For e2e tests.** `tests/e2e/test_websocket.py` drives a real browser WebSocket, so the header path is unavailable — which is precisely the constraint the cookie is chosen to satisfy. The fixture sets the cookie directly (`context.add_cookies([...])` in a `browser_context_args`/context fixture) and both the SPA's REST calls and its WS connect work unchanged. That is a clean, small change to `tests/e2e/conftest.py`.

---

## Default Bind

Answering question 5. **Recommendation: do not change the default.** Keep `host = "0.0.0.0"` and make the *default posture* safe by having auth on by default, backed by a startup guard.

### Why flipping the default breaks Docker

A container that binds `127.0.0.1` is not reachable through Docker's published-port mapping — `docker-proxy` forwards to the container's bridge address, not its loopback. Every user following the documented compose file (`docs/pages/getting-started/docker/snippets/docker-compose.yml:12-13`, `ports: "8126:8126"`) would silently lose access on upgrade, with "connection refused" and no log line explaining it. The Dockerfile sets no `HASSETTE__WEB_API__HOST`, so the container relies entirely on the field default — there is nothing to insulate them. *(This is standard Docker port-publishing behavior; I did not empirically verify it against this image — see Open Questions.)*

The container's own healthcheck (`curl -sf http://127.0.0.1:8126/api/health/live`) would keep passing, so Docker would report the container **healthy** while the UI was unreachable. That is the worst possible failure shape.

Two docs pages actively teach the current behavior and would become wrong: `docs/pages/getting-started/docker/troubleshooting.md:76-91` ("Use `8126:8126` to accept connections from other devices on your network") and `docs/pages/getting-started/docker/index.md:61` ("the web UI is available at `http://localhost:8126`").

### Why "detect the container and bind 0.0.0.0 there" is worse

Container detection (`/.dockerenv`, cgroup sniffing) is unreliable across runtimes and is exactly the kind of implicit magic that produces "why is it binding differently on my machine" bug reports. It also fails the goal: a container binding `0.0.0.0` is the state we were trying to avoid.

### What to do instead

- **Keep `host = "0.0.0.0"`.** The bind is not the vulnerability; the missing credential is.
- **Auth on by default with an auto-generated token.** The default install becomes authenticated rather than narrow. This is the substantive answer to the user's motivation — the port stays reachable from their own network, but reaching it is not the same as using it.
- **Refuse to start when `auth_enabled = false` and `host` is non-loopback**, with an error naming both settings and the two ways out. This satisfies #1117's AC #3 via its explicit "or require explicit opt-in to bind on non-loopback interfaces with a clear warning" branch.
- **Rewrite the docs warning.** `docs/pages/web-ui/index.md:17-24` currently says "no built-in authentication… for local-only access set `host = 127.0.0.1`." That block inverts: the token is the primary control, the loopback bind becomes an optional extra layer, and `trusted_proxies` becomes the documented reverse-proxy story.
- **Update the four tests that hardcode the bind** only if it changes — under this recommendation, `tests/unit/test_config_models.py:377` and `tests/e2e/mock_fixtures.py:897` need no edit at all, and `tests/unit/cli/test_client.py:80` (which tests the `0.0.0.0`→`127.0.0.1` rewrite) stays valid either way.

### Add-on interaction

Under ingress the add-on container must bind an address the gateway can reach, so `0.0.0.0` inside the container is required regardless. A loopback default would force `run.sh` to override it — one more env var and one more way for the add-on to break. Keeping `0.0.0.0` is the add-on-compatible choice.

---

## Concrete Implementation Shape

Answering question 6, with the add-on seam called out explicitly.

### Config (`src/hassette/config/models.py`, `WebApiConfig`)

```
auth_enabled: bool = True
    """Require a credential for API and UI access."""
auth_token: SecretStr | None = None
    """Static bearer token. When unset, a token is generated on first start and
    persisted to <data_dir>/.web_api_token."""
trusted_proxies: tuple[str, ...] = ()
    """Peer IPs/CIDRs whose requests are already authenticated upstream
    (HA ingress gateway, or a reverse proxy that performs auth)."""
```

`auth_token` **must** be `SecretStr` — that is what makes `/api/config` mask it (see threat model item 1). `trusted_proxies` entries parse through `ipaddress` in a `field_validator` so a typo fails at config load. Env names follow the existing nesting: `HASSETTE__WEB_API__AUTH_TOKEN`, `HASSETTE__WEB_API__TRUSTED_PROXIES`. Regenerate `hassette.schema.json`.

Add a validator (or a startup check) for the still-open audit finding #8: reject `"*"` in `cors_origins` while `allow_credentials=True`.

### Credential lifecycle

Resolution happens in `WebApiService.on_initialize()` — **not** a FastAPI lifespan, because `lifespan="off"` is passed to `uvicorn.Config` (`core/web_api_service.py:69`).

1. `config.web_api.auth_token` set → use it.
2. Else `<data_dir>/.web_api_token` exists → read it.
3. Else generate `secrets.token_urlsafe(32)`, write with mode `0o600`, and log once at INFO with the full URL (the Jupyter pattern).

### New / changed files

| Change | File |
|---|---|
| Create | `src/hassette/web/auth.py` — token resolution, `compare_digest` check, `trusted_proxies` peer check, cookie mint/verify, `authorize_ws()` |
| Create | `src/hassette/web/middleware.py` — the auth ASGI middleware (this is the file prereq-03 planned to create; it now holds auth instead of the IP allowlist) |
| Modify | `src/hassette/web/app.py` — register the middleware **inside** CORS so preflight `OPTIONS` still gets a CORS response |
| Modify | `src/hassette/web/dependencies.py` — `AuthDep` for any route that wants explicit gating |
| Modify | `src/hassette/web/routes/ws.py` — pre-`accept()` check |
| Create | `src/hassette/web/routes/auth.py` — `POST /api/auth/session` |
| Modify | `src/hassette/exceptions.py` — new `HassetteError` subclasses (**not** `InvalidAuthError`, which is taken and is a `FatalError`) |
| Modify | `src/hassette/config/models.py`, `hassette.schema.json` |
| Modify | `src/hassette/core/web_api_service.py` — token resolution in `on_initialize`, startup guard |
| Modify | `src/hassette/cli/client.py` — attach the header; add `--token` and read the token file |
| Modify | `frontend/src/api/client.ts` — `credentials: "same-origin"`, 401 handling |
| Create | `frontend/src/` — minimal login view |
| Modify | `src/hassette/test_utils/web_mocks.py` — stub the new `web_api` fields (and `model_dump.return_value`) |
| Modify | `tests/integration/web_api/conftest.py`, `tests/e2e/conftest.py` |
| Modify | `docs/pages/web-ui/index.md`, `docs/pages/cli/configuration.md`, `docs/pages/getting-started/docker/*`, `docs/pages/troubleshooting.md` |

### Test strategy — keep the blast radius small

Default `create_hassette_stub()` to `auth_enabled=False`. All ~211 integration and ~165 e2e tests then pass unchanged, and auth gets its own dedicated coverage instead of being smeared across 380 assertions:

- New `tests/integration/web_api/test_auth.py` — no credential → 401; wrong token → 401; correct bearer → 200; cookie → 200; `trusted_proxies` peer → 200; health endpoints open without a credential; WS rejected with close code 1008 without a credential and accepted with one.
- New system test asserting the plaintext auth token never appears in `GET /api/config`, mirroring `tests/system/test_web_api.py:75-93`.
- One e2e covering login → cookie → REST + WS, with the cookie set via `context.add_cookies`.

### The seam: safe now vs. add-on revisits

**Safe to build now, add-on-compatible, no #71 dependency:** every item in the table above. `trusted_proxies` is a general-purpose field that serves reverse-proxy users independently of the add-on; the auth core, WS check, bind guard, CLI, and docs have no ingress coupling.

**Requires an #71 revisit (each small, each an improvement):**
- `prereq-03` is superseded. Its file should say so.
- `prereq-04`'s `run.sh` step 4 simplifies — export `HASSETTE__WEB_API__TRUSTED_PROXIES='["172.30.32.2","127.0.0.1"]'` unconditionally; drop the `addons/self/info` port-mapping query, and possibly `hassio_api: true` from the manifest with it.
- ADR-0005's "direct-port path remains unauthenticated by design in v0.1" and `research.md:266` need updating — that path is now authenticated, and `ports_description` in the manifest sketch (`research.md:158`) should stop saying "unauthenticated."
- **prereq-01 interaction (new, previously unnoted):** under ingress the SPA is served at `/api/hassio_ingress/<token>/`, so a `Set-Cookie` with `Path=/` would scope to the whole HA origin and collide across add-ons. Under the recommended design this never fires — ingress requests short-circuit on `trusted_proxies` and no cookie is ever minted — but if the two features are ever both active, the cookie `Path` must derive from `X-Ingress-Path`, the same header prereq-01 injects into `<base href>`. Worth a line in prereq-01.

### Rate limiting

**Recommendation: skip it, and document why** — #1117's AC #4 explicitly permits this. Once a credential is required, the mutation endpoints are only reachable by the operator, and rate-limiting the operator's own scripts protects nobody. Brute-forcing a 256-bit `token_urlsafe(32)` over HTTP is not a realistic attack, so throttling failed auth attempts is also unnecessary. Two things *are* worth doing in its place, because they are unbounded-resource issues that exist independently of auth: cap concurrent WebSocket clients (`RuntimeQueryService.register_ws_client` adds to an unbounded set), and note that `PUT /api/logs/level` can drive persisted-log volume.

---

## Prior Art

Answering question 7 briefly; three findings are transferable.

**Jupyter Notebook** is the closest analogue and validates the recommended shape almost exactly: token authentication is the *default* security model, a token is generated at first run and printed to the terminal in a copy-paste URL, and a one-time token in the URL is exchanged for a browser cookie, after which the token is discarded from the URL. That is Option A, shipped and battle-tested for a decade. `jupyter notebook list` (surfacing the running server's token) also suggests a `hassette status`-adjacent affordance worth considering.

**Home Assistant's own ingress model** confirms the trusted-proxy approach: the developer docs state *"Users are previously authenticated via Home Assistant. Authentication is not required"* and *"Only connections from `172.30.32.2` must be allowed."* Add-ons are expected to trust the gateway, not to implement their own auth for the ingress path — which is what `trusted_proxies` encodes.

**The browser WebSocket constraint** is universal, not a hassette quirk: the `WebSocket` constructor takes only a URL and a subprotocol array, so every real-time platform routes around it. The three known patterns are query string, `Sec-WebSocket-Protocol` smuggling, and first-message auth; the cookie is the fourth and is the one that requires no client-side workaround at all for a same-origin app. Query-string tokens are widely flagged for exactly the reason that disqualifies them here — they land in infrastructure logs.

---

## Concerns

### Technical risks

- **Middleware ordering versus CORS.** If the auth middleware runs outside `CORSMiddleware`, preflight `OPTIONS` requests get a 401 with no CORS headers and browsers report an opaque CORS failure rather than an auth failure. Since Starlette applies middleware in reverse-registration order, this needs a deliberate choice and a test — and there is no existing middleware to pattern-match against.
- **`/api/config` disclosing the auth token.** Concrete, high-impact, and entirely prevented by declaring the field `SecretStr`. Guard it with a test that asserts the plaintext never appears in the response body, mirroring the existing HA-token system test.
- **The e2e suite is the integration risk, not the production code.** 165 tests navigate a URL with no credential. If auth defaults on in `create_hassette_stub()`, they all break at once and the failure is a wall of red that obscures real regressions. Defaulting the stub off is the mitigation, and it is a deliberate trade (auth is then covered by a small dedicated suite rather than incidentally by every test).
- **`web/` is high-churn** — 89 commits, with recent work in `#1495`, `#1500`, `#1464`, `#1438`. Expect rebases.
- **Token-file permissions across platforms.** `0o600` is meaningful on Linux (the only supported deployment surface for Docker/add-on) and largely cosmetic on Windows. Not a blocker; worth not over-claiming in the docs.

### Complexity risks

- **Two credential transports.** Header for machines, cookie for browsers. Each needs its own tests, its own failure messages, and its own line in the docs. Option B trades this away at the cost of `sessionStorage`-resident credentials.
- **A login screen is a new UX surface** with its own states (wrong token, expired cookie, ingress-should-never-show-this). Small, but it is the first authentication UI in the project.
- **`trusted_proxies` is an auth *bypass*.** Any bypass is a footgun — a user who copies a `trusted_proxies` line from a forum post without understanding it can disable auth for a whole subnet. The docs need to be blunt about this, and the config validator should probably reject obviously-wrong entries like `0.0.0.0/0`.

### Maintenance risks

- Every new route inherits the default-deny posture automatically if it's middleware-based; if it's `Depends()`-based per-router, a future router added to `app.py` could be forgotten. **Prefer middleware for the default-deny**, precisely so the failure mode is "accidentally protected" rather than "accidentally open."
- The auth token in `/data` means it is in HA backups (the add-on) and in the Docker volume. Restore semantics need one sentence somewhere.
- ADR-0005 and three prereq documents become partially stale the moment this ships. Leaving them stale is how the add-on epic gets built against a superseded design.

---

## Open Questions

- [ ] **Verify the Docker loopback claim empirically.** Build the image with `HASSETTE__WEB_API__HOST=127.0.0.1`, run with `-p 8126:8126`, and confirm the host cannot reach it while the container healthcheck still passes. The recommendation against flipping the default rests on this, and I reasoned about it rather than ran it.
- [ ] **Confirm uvicorn's access log actually emits the query string in this configuration.** The config call site passes no `access_log`/`log_config` override and uvicorn's documented default is on, but I did not start the server and read a log line. If it turns out to be suppressed, the argument against query-param WS tokens weakens (it does not vanish — proxies and browser history still log URLs).
- [ ] **Does the HA Supervisor ingress proxy forward `Set-Cookie` and cookie headers cleanly, and does it forward `Sec-WebSocket-Protocol`?** Under the recommended design the cookie never crosses ingress (trusted-proxy short-circuit), so this is only load-bearing if Option B is chosen or if the short-circuit is later removed. **Unknown:** I searched the HA developer add-on presentation docs, which document only `X-Ingress-Path` and the `172.30.32.2` restriction. Nothing about cookie or subprotocol forwarding was found there.
- [ ] **Do any `X-Remote-User-*` headers arrive through ingress?** Community threads suggest the Supervisor can pass HA user identity to add-ons via headers during ingress session creation, but the official presentation docs do not document them. Not needed for this design (single operator, no per-user identity), but it would be the hook if per-user attribution is ever wanted. **Unknown** — searched HA developer docs and community threads; found discussion, no authoritative header list.
- [ ] **Should `hassette status` print the token (Jupyter's `jupyter notebook list` affordance)?** Convenient; also means the token appears in terminal scrollback. Product call.
- [ ] **What is the token-rotation story?** v1 answer is "delete `<data_dir>/.web_api_token` and restart." Is a `hassette` CLI subcommand worth it, or is that gold-plating for one operator?
- [ ] **Should the WS client set be capped?** `RuntimeQueryService.register_ws_client` adds to an unbounded set. Independent of auth, but it is the kind of thing this issue is the natural moment to fix.
- [ ] **#708 overlap.** Plain-`str` secrets in user `AppConfig` classes leak through `/api/config` regardless of auth. Auth reduces the exposure to authenticated clients, which is most of the risk, but does not fix the underlying type-driven-masking gap. Worth deciding whether #708 rides along or stays separate.

---

## Recommendation

**Build Option A, and do not change the default bind.**

The honest read of the threat model is that #1117's title has the emphasis slightly wrong. The bind address is not the vulnerability — the missing credential is. Changing `0.0.0.0` to `127.0.0.1` would break every documented Docker deployment (silently, while the healthcheck still reports green) and would still leave the API unauthenticated for everyone who then has to re-open it, which is everyone who wants to reach it from their own network. That is precisely the user's stated use case, so a loopback default fails the actual requirement while imposing the full breakage cost. *(This is my assessment, and it contradicts AC #3's first branch — but AC #3's second branch, "or require explicit opt-in to bind on non-loopback interfaces with a clear warning when binding publicly without auth", is exactly what I'm recommending, so the issue as written already permits it.)*

Auth on by default with an auto-generated token inverts the problem correctly: a fresh install is secure without configuration, existing deployments keep working, and the operator reads one log line. Jupyter has shipped this exact model for a decade, which is about as much validation as a design like this can get.

On the token-vs-cookie question the user flagged as open: **the user's leaning toward token/API-key auth is right, and the evidence supports it** — a static bearer token is the correct credential of record for a single-operator tool with a CLI. But it does not survive contact with the browser `WebSocket` API on its own, and that is not a preference, it is a constraint. The cookie in Option A is not a competing auth scheme; it is the transport that lets the same token reach a native `WebSocket`, and it costs one endpoint plus one `Set-Cookie`. Session/cookie auth *as the primary model* — usernames, passwords, a session store — is the thing to reject, and I do: it adds a user database to a system with exactly one user, and `WebApiService`'s TRANSIENT restart spec would silently log that user out on every service restart.

On prereq-03: **close it and build `trusted_proxies` instead.** Its own design document says it is not authentication and points at this issue as the real fix. Building both means the add-on carries a weaker guard alongside a stronger one, with two config fields that must agree. `trusted_proxies` additionally makes the add-on's optional host port *authenticated* rather than "documented as unauthenticated," which retires a caveat ADR-0005 currently has to carry.

Two things I would not do: rate limiting (AC #4 explicitly allows documenting it out of scope, and with a credential in place it protects nobody), and container-detection magic for the bind (unreliable, and it fails the goal anyway).

The one thing that makes me want a prototype before full commitment is the e2e suite. 165 Playwright tests, a real browser WebSocket, and a cookie that has to be established the way a browser establishes it — that is where this design either works cleanly or turns into a fixture mess. It is a half-day spike, and it is worth doing before writing the login view.

### Suggested next steps

1. **Spike the e2e cookie path first** — set a session cookie via `context.add_cookies` in `tests/e2e/conftest.py`, confirm both `apiFetch` and the browser `WebSocket` in `test_websocket.py` authenticate through it. This is the riskiest assumption; find out cheaply.
2. **Verify the Docker loopback claim** (open question 1). It is the load-bearing fact under the "don't change the default bind" recommendation, and it takes ten minutes.
3. **Write the design doc via `/mine-define`**, settling: the cookie value derivation (HMAC vs. stored), whether `deny_untrusted_peers` ships in v1, and the health-endpoint gating boundary.
4. **Sequence the implementation as verifiable units** — config + token resolution + startup guard (no enforcement) → enforcement + integration tests → WS → login view + e2e → CLI → docs. Each lands green.
5. **Update the add-on design artifacts in the same wave**: mark `prereq-03` superseded, edit `prereq-04`'s `run.sh` list, add a note to ADR-0005 and `research.md:266`, and add the cookie-`Path` line to `prereq-01`. Leaving them stale is how #71 gets built against a design that no longer holds.
6. **Decide #708's fate** — plain-`str` app-config secrets leak regardless of auth, and this is the moment to either fix it or explicitly defer it.

---

## Addendum: Hardening Considerations Beyond the Core Design (2026-08-03)

Added after a follow-up conversation pressure-testing Option A against the failure pattern seen in several self-hosted *arr-app incidents: a single global credential, mass-scanned and found via Shodan/Censys fingerprinting, giving full read+write once located. Hassette's design is structurally close enough to that shape (one static token, full read+actuation, no scoping) that these are worth deciding now rather than discovering after ship.

### A1. TLS is a hard requirement for the VPS deployment case, not an implementation detail

Option A's cookie is `Secure`-when-https — conditional, not mandated. For the user's actual deployment (hassette on a VPS, accessed from a separate home network), traffic crosses the open internet. A bearer token or session cookie sent over plain HTTP is sniffable by anyone positioned on that path (ISP, VPS host's network segment, a compromised hop). A 256-bit random token provides no protection if it's transmitted in cleartext — TLS and auth are not substitutes for each other, they're both required.

**This is not hassette's job to implement** — it's a reverse-proxy concern, and the docs already point at one (`docs/pages/web-ui/index.md:23-24`, "place Hassette behind a reverse proxy... Caddy, nginx, and Traefik all work"). But that line is a name-drop with no example and no explicit statement that TLS is required, not optional, once auth ships. **Action:** the docs rewrite in the Concrete Implementation Shape's file list (`docs/pages/web-ui/index.md`) should gain a concrete Caddy (or Traefik) snippet terminating TLS and reverse-proxying to `:8126`, plus an explicit statement that running Option A's auth over plain HTTP on a non-loopback bind defeats its own purpose.

### A2. The first-run token exchange should be a login form, not a clickable magic-link URL

Jupyter's pattern (which Option A borrows) prints a URL with `?token=...` embedded, meant to be clicked. That puts the token in **browser history**, not just server logs — a distinct leak vector from the query-string-in-access-log concern already covered in [WebSocket Auth](#websocket-auth). This is a known, live critique of Jupyter's own model. For hassette: show the generated token in the startup log as a **value to paste into a login form field** (`POST`ed in the request body), not as a clickable URL with the token embedded. Same one-time-log-line UX, none of the browser-history exposure. This changes one UI detail in the login-view work item, not the overall design.

*(Secrets ending up committed to git — `.env` files, `hassette.toml` with an inline token, pushed to a public homelab-dotfiles repo — is the other classic vector behind mass *arr-app leaks. Already adequately covered by existing docs: `docs/pages/getting-started/ha_token.md`, `docker/dependencies.md`, `core-concepts/configuration/index.md`. No new brief action needed here.)*

### A3. `/api/docs` and `/api/openapi.json` are unauthenticated fingerprinting surface

Verified in code: `FastAPI(docs_url="/api/docs", openapi_url="/api/openapi.json")` (`app.py:48-49`) — neither is gated by anything, and neither appears in this brief's [endpoint inventory](#current-state) or in any existing audit. `/api/health/live` has to stay open for Docker/watchdog healthchecks, and that's an acceptable, minimal fingerprint (confirms "something is listening," not what it is or what it exposes). `/api/docs` and `/api/openapi.json` are a different order of exposure — they hand an unauthenticated scanner the complete endpoint map, including ones an attacker might not otherwise guess (`/api/apps/{key}/source`, `/api/logs/level`). **Action:** these two routes fall under the same default-deny middleware as everything else in the [Concrete Implementation Shape](#concrete-implementation-shape); the health endpoints remain the only carve-out.

### A4. No blast-radius containment if the token leaks — name this trade-off explicitly

Option A has one credential with full read (config, source, HA `base_url`, logs) and full actuation (start/stop/reload, trigger jobs) — no scoping, no read-only mode, no per-client identity or revocation in v1. This is an accepted trade-off for a single-operator tool (adding RBAC or multi-token scoping would be exactly the enterprise pattern this project's context correctly avoids), but it raises the stakes on A1/A2/A5 — since there's no defense-in-depth once the token is out, everything upstream of that (transport security, exchange mechanism, visibility into misuse) carries more weight than it would in a system with tiered permissions. Worth stating in the design doc as a deliberate decision, not a gap that got missed.

### A5. No visibility if a leaked token gets used

Today, nothing surfaces "an unrecognized client just triggered `reload_app` at 3am" anywhere the operator would see it — uvicorn's access log is the only record, it's not in the persisted telemetry DB (deliberately, per [threat model item 2](#things-to-worry-about-beyond-add-a-credential-check)), and nobody reads it proactively. **Action:** log authenticated mutation actions (start/stop/reload/trigger/log-level-change) with source IP through the app's own `"hassette"` logger at INFO, so they flow into `/api/logs/recent` and the dashboard's log view — cheap, and it means misuse is at least visible somewhere the operator is likely to glance, not just in an access log nobody reads. Small addition to the `web/auth.py` / route-handler work already scoped.

### A6. A trivial per-IP throttle on the auth exchange, for hygiene not confidentiality

The brief's rate-limiting recommendation (skip it — [Rate limiting](#rate-limiting)) is correct for *authenticated* traffic: a 256-bit token isn't brute-forceable and rate-limiting the operator's own scripts protects nobody. But any VPS with an open port draws constant background scanning-bot traffic regardless of whether any exploit is possible. A cheap per-IP throttle specifically on `POST /api/auth/session` (and bearer-auth failures) isn't a security control — it's what keeps routine internet noise from filling logs and burying the real signal from A5. Small, and orthogonal to the "skip rate limiting" decision, which still stands for everything else.

### A7. Fold #708 into this work — it's the same failure mode by a different door

Issue #708 ("Harden config endpoint secret redaction and restore frontend reveal toggle") predates the current code: its description assumes a regex key-name deny-list, but the codebase has since moved to schema-driven masking (`mask_values()`, `config_view.py:74`, keyed off Pydantic's `writeOnly`/`format: password`). The issue's literal description is stale — but the underlying problem it tracks is identical to [threat model item 1](#things-to-worry-about-beyond-add-a-credential-check): masking only fires for fields explicitly typed `SecretStr`; a plain `str` field an app author uses for a real credential still returns in full through `/api/config`.

Auth narrows this from "anyone on the network" to "anyone with the token" — a real reduction, but not a fix, and it's the single most direct answer to "how do I avoid leaking every credential the way that *arr app did." **Recommendation: decide #708's fate in the same design pass as this issue** rather than leaving it as a someday-maybe (this was already an open question in the original brief; this addendum resolves it toward "fold in, don't defer").

---

## Addendum 2: Challenge Resolution (2026-08-03)

`/mine-challenge` was run against this brief (including Addendum 1) with explicit framing to weigh "what did we miss" as heavily as "is this the right direction." Three critics (Skeptical Senior Engineer, Adversarial Reviewer, Operational Resilience Critic) independently converged on the same root vulnerability from different angles, plus surfaced 12 further findings — 2 CRITICAL, 4 HIGH, 7 MEDIUM, 0 Likely Invalid. Full findings, evidence, and reasoning: `/tmp/claude-mine-challenge-5S21s0/challenge-results.md` (session-local; resolutions below are self-contained and don't require that file to act on). Decisions below were made by the user inline; each supersedes or extends the corresponding section of the main brief.

### CRITICAL

**C1 (challenge Finding 1) — `trusted_proxies` trust boundary was unspecified; uvicorn's own default proxy-header handling is a second, unaudited bypass path.** Resolved: apply both fixes together. (a) `trusted_proxies` compares against the raw ASGI `scope["client"]` peer address only — never `X-Forwarded-For` or any client-suppliable header; add a test asserting a spoofed `X-Forwarded-For: 172.30.32.2` from an untrusted direct peer is rejected exactly like any other unauthenticated request. (b) Explicitly pass `proxy_headers=False` to `uvicorn.Config` in `web_api_service.py`, so hassette's `trusted_proxies` is the *only* proxy-trust mechanism in the request path — no second, env-var-triggered one (`FORWARDED_ALLOW_IPS`) silently layered underneath that nothing in hassette's schema or docs mentions. This is a **precondition** for C2/H1's "wire into `forwarded_allow_ips`" resolution below — (b) must land first since H1 reuses this same mechanism for scheme-forwarding.

**C2 (challenge Finding 2) — the brief's headline "secure without configuration" claim doesn't hold for the VPS scenario without TLS; TLS was a docs bullet, not a code-level guard.** Resolved: both. (a) Add a startup warning when `host` is non-loopback **and** `trusted_proxies` is empty (no evidence of a fronting proxy at all) — names TLS explicitly, mirrors the existing `auth_enabled`+bind guard in spirit but as a warning, not a hard block (hassette can't detect a terminating proxy, so it can't refuse to start). (b) Retitle the Recommendation section's framing from "secure without configuration" to "**authenticated** without configuration; secure only when paired with TLS for any non-loopback bind" — the design doc should carry this framing from the start rather than the stronger claim.

### HIGH

**H1 (challenge Finding 3) — the cookie's `Secure`-when-https flag silently never activates behind a sibling reverse-proxy container.** Resolved: wire `trusted_proxies` into uvicorn's `forwarded_allow_ips` so `X-Forwarded-Proto` is honored (and thus `request.url.scheme` correctly reflects HTTPS) only from peers already in the trust list. Rejected the simpler "set `Secure` unconditionally" alternative: it would silently break the plain-HTTP LAN-only deployment the docs currently support (`host = "127.0.0.1"` or any LAN bind with no TLS/reverse proxy) — browsers refuse to send `Secure` cookies over plain HTTP at all, so that path would produce an unexplained login loop for a legitimate, currently-documented use case. This resolution depends on C1(b) shipping first (same mechanism, same field).

**H2 (challenge Finding 5) — the WebSocket reconnect loop can't distinguish an auth rejection (close code 1008) from a transient disconnect; retries forever with no "please log in again" state.** Resolved: `use-websocket.ts` branches on `event.code === 1008` (and/or caps consecutive-failure count below some minimum connection duration) and, on that condition, stops the backoff loop and redirects full-page to the new login view (the login view itself is new work scoped in the original Concrete Implementation Shape — "a minimal login view in the SPA" — not an existing page). Full-page redirect chosen over an inline prompt: simpler to build and reason about since there's no existing page state to preserve, and the login view doesn't exist yet either way.

**H3 (challenge Finding 6) — an unhandled token-file read/write failure can crash `WebApiService` into an infinite 5-minute restart-cooldown loop, taking `/api/health/live` down with it.** Resolved: on startup, treat a corrupt/unreadable token file the same as "file doesn't exist" — regenerate a fresh token and log at ERROR so the regeneration is visible on stdout during the incident; the service stays up rather than crashing. Ships alongside the atomic-write fix regardless of this branch decision: write the token to a temp file in the same directory and `os.replace()` into place (mode `0o600` preserved), eliminating the torn-write case that produces the corrupt-read failure mode in the first place.

### MEDIUM

**M1 (challenge Finding 7) — no session/cookie TTL specified; a leaked cookie is valid forever until the token is manually rotated.** Resolved: short default TTL (a few hours), embedded as an issuance timestamp in the HMAC payload and checked at validation time (stays stateless, survives `WebApiService` TRANSIENT restarts) — **and** exposed as a config field (`web_api.session_ttl` or similar) so the operator can widen it if hourly re-login is too much friction for their setup. Default short, user-adjustable — not hardcoded either direction.

**M2 (challenge Finding 8) — `trusted_proxies` is operationally fragile for the self-managed-reverse-proxy case (IP churn on container recreate, hostnames like `"caddy"` rejected outright by `ipaddress`-only validation), distinct from the add-on's fixed-IP case.** Resolved: scope `trusted_proxies` v1 to the add-on ingress case only (the single, HA-documented, review-gated `172.30.32.2` / `127.0.0.1` values). Self-managed reverse-proxy users are not left without a path — they authenticate through the normal bearer/cookie flow same as any other client, which needs no `trusted_proxies` entry for a proxy that isn't itself doing pre-auth. Keeps the field's threat model coherent: one controlled value, not one controlled and one drifting.

**M3 (challenge Finding 12) — losing the token file (volume not migrated, `docker compose down -v`, switching from explicit-config to file-based) looks identical to a normal rotation; no signal explains why auth suddenly changed.** Resolved: minimal fix only — log at INFO which of the three resolution branches fired (explicit config / persisted file / freshly generated) on every startup, not just when generating. The stronger fix (persisted token fingerprint/creation-timestamp surfaced in the CLI or dashboard) is explicitly deferred, not silently dropped — worth revisiting if operators report confusion in practice.

### Auto-applied (no trade-off, folded in directly)

- **Finding 4** — `POST /api/auth/session` is a third explicit exemption from default-deny, alongside `/api/health/live` and `/api/health/ready`. It performs its own body-based token validation rather than header/cookie validation; a browser with no cookie yet must be able to reach it to obtain one. Add a test asserting it's reachable with zero credentials and correctly rejects a wrong token via the route handler, not the middleware.
- **Finding 9** — the Addendum 1 (A6) per-IP auth-throttle has a hard dependency on C1's proxy-header trust chain: without it, every request's observed peer is the proxy's own address, not the real client's, so a per-IP throttle either locks out the operator or does nothing against real scanner traffic. Note this as a blocking prerequisite (A6 cannot ship correctly before C1), not an independent decide-later item.
- **Finding 10** — drop `--token <value>` as a literal CLI argument (visible in `ps aux`/`/proc/<pid>/cmdline` and shell history for the process's lifetime). CLI credential input is the token file (already in the design) or `HASSETTE__WEB_API__AUTH_TOKEN`/a `--token-file <path>` flag — never a secret as a bare CLI argument. Matches the project's existing convention for the HA token itself.
- **Finding 11** — added to Open Questions (alongside the Docker loopback claim and the uvicorn access-log claim): confirm that `websocket.close(code=1008)` before `accept()` actually rejects the handshake cleanly under this project's specifically-configured `ws="websockets-sansio"` backend (a deliberate, non-default choice — verified at `web_api_service.py:71`), not uvicorn's default backend. Needs the same short empirical spike already proposed for the loopback claim before this becomes the shipped implementation.
- **Finding 13** — extend Addendum 1's A5 (misuse-visibility logging) to also log denied-auth events, not just successful mutations. Rate-limited/coalesced, not per-attempt (e.g., "12 failed auth attempts from 203.0.113.4 in the last 5 minutes"), routed through the same `"hassette"` logger so it lands in `/api/logs/recent` and the dashboard — the strongest signal of active credential misuse (a run of 401s) currently has zero visibility path, and M2's throttle would make that traffic quieter without this fix making it more visible anywhere the operator reads.

---

## Sources

- [Security in the Jupyter notebook server](https://jupyter-notebook.readthedocs.io/en/v6.5.2/security.html) — token generated at first run, printed to terminal, one-time URL token exchanged for a browser cookie
- [Home Assistant add-on presentation / ingress docs](https://developers.home-assistant.io/docs/add-ons/presentation/) — `X-Ingress-Path`, "Authentication is not required", "Only connections from `172.30.32.2` must be allowed"
- [WebSocket authentication patterns](https://websocket.org/guides/authentication/) — the browser `WebSocket` constructor cannot set custom headers; query string / subprotocol / first-message trade-offs
- [websockets library — Authentication](https://websockets.readthedocs.io/en/stable/topics/authentication.html) — same constraint, library-level treatment
- [Securing WebSocket connections using the Sec-WebSocket-Protocol header](https://www.textcontrol.com/blog/2025/11/20/securing-websocket-connections-in-aspnet-core-using-sec-websocket-protocol-header/) — the subprotocol-smuggling pattern used in Option B
- [Home Assistant Supervisor — Proxy and Ingress](https://deepwiki.com/home-assistant/supervisor/6.3-proxy-and-ingress) — ingress session-based authentication, user context headers
