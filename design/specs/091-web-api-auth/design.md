# Design: Web API Authentication and Safe Default Bind

**Date:** 2026-08-03
**Status:** archived
**Scope-mode:** hold
**Research:** design/research/2026-08-03-web-api-auth/research.md (includes Addendum 1: hardening gaps, and Addendum 2: challenge resolution)

!!! Superseded in part — auth precedence (issue #1530)

    This document describes the trusted-peer match as an unconditional short-circuit ahead of the
    bearer/cookie check (FR#2, and "Architecture → Middleware and routing"). That ordering shipped
    and was later found to make `trusted_proxies` and bearer-token API access mutually exclusive on
    one host: a wrong or malformed `Authorization` header from a trusted peer was accepted, since
    the peer match returned before the token was ever compared.

    Issue #1530 inverted it. A *presented* `Authorization` header is now authoritative and fails
    closed on any invalid form; peer trust and the session cookie apply only when no header was
    presented. The precedence lives in one `resolve_auth_outcome()` in `web/auth.py`, shared by
    `DefaultDenyMiddleware` and `authorize_ws()`. Everything below is left as the original record —
    read `web/auth.py` for the current ordering.

## Problem

Hassette's web API has no authentication of any kind. Mutation endpoints (`start`/`stop`/`reload` an app, `trigger` a scheduled job, `PUT /api/logs/level`), source-disclosure endpoints (`/source`, `/config`), and the WebSocket feed are all reachable by any network peer that can reach the port — which, on the default `0.0.0.0` bind, is anyone on the same LAN, Docker bridge network, or (for a VPS deployment) potentially the wider internet.

The real risk is not primarily information disclosure. Hassette holds a long-lived, typically full-admin Home Assistant token. An unauthenticated peer can force hassette to execute the operator's own automation code on demand (`reload_app` + `trigger`), which is indirect actuator control of the operator's home — locks, lights, garage doors — mediated through hassette's own credential. For a hassette instance running on a personal VPS and reached from a home network (the case that prompted this issue), that gap needs to close before wider exposure is safe. `GET /api/apps/{app_key}/source`, `GET /api/apps/{app_key}/config`, and `GET /api/config` add reconnaissance value (entity IDs, device IPs, HA `base_url`, filesystem paths) on top of that.

Filed as GitHub issue #1117 (`priority:high`, `release:v1.0.0`, `size:large`), escalated from a 2026-03 audit finding after a 2026-06 retrospective confirmed it as "worse" — the source-disclosure endpoint, the handshake-free WebSocket, and the `0.0.0.0` default bind were all still present.

## Goals

- Every mutation endpoint, `/source`, `/config`, and `/api/ws` require a credential before responding.
- A fresh install is authenticated with zero required configuration — the operator does not have to read documentation or set anything before the API is protected.
- An operator running a forward-auth gateway in front of hassette (a Home Assistant add-on's ingress proxy, or a self-managed setup like Caddy + tinyauth + pocket-id, or Authelia) can let that gateway be the credential check, without hassette needing its own separate login for gateway-authenticated traffic.
- Binding non-loopback with no evidence of a fronting proxy produces a loud startup warning naming TLS explicitly — the operator is told, not left to discover it.
- The CORS `allow_credentials=True` + wildcard-origin footgun (audit finding, AC #5) is rejected at config load, not left as a silent misconfiguration.
- Existing Docker/Compose deployments keep working unchanged after upgrading, modulo reading one new log line for their generated token.

## Non-Goals

- RBAC, multi-user accounts, per-user identity, or multi-tenant isolation. Hassette is a single-operator tool; `trusted_proxies` intentionally does not carry identity from the fronting gateway.
- OAuth/OIDC, JWT-based sessions, or hassette acting as its own identity provider. Delegate that entirely to the operator's own forward-auth gateway via `trusted_proxies` if they want it.
- Rate limiting on mutation endpoints. Documented out per issue #1117's AC #4 — once a credential is required, rate-limiting the operator's own scripts protects nobody, and brute-forcing a 256-bit token over HTTP is not realistic.
- Multiple, individually-revocable API tokens (the GitHub-PAT/Gitea-token model). This is genuinely the norm for full-dashboard self-hosted apps with a real user base, but a single shared token is the accepted trade-off for hassette's single-operator scope. Worth revisiting if hassette gains a broader operator base.
- User-chosen passwords, password hashing, a claim/setup wizard, or any related account-creation flow. Explored and rejected during design — see Alternatives Considered.
- Token-rotation CLI tooling and a token-fingerprint/creation-timestamp display in the CLI or dashboard. Both deferred, not dropped — `hassette status` could grow this later if operators report confusion after losing a token.
- Issue #708 (secret redaction hardening for `/api/config`). Related — same "don't leak a credential to an authenticated caller" concern — but stays a separate follow-up issue, not folded into this implementation.
- Live/per-request DNS re-resolution for `trusted_proxies` hostname entries. Periodic re-resolution (see Architecture) is in scope; per-request resolution was rejected as a DNS-rebinding risk with no real benefit over a periodic refresh.

## User Scenarios

### Operator: Runs a forward-auth gateway (tinyauth+pocket-id, Authelia, or the future HA add-on's ingress)

- **Goal:** Reach the hassette dashboard through their existing SSO layer, without a second login.
- **Context:** Hassette sits behind a reverse proxy that already gates access (passkey login via pocket-id, or HA Supervisor's own ingress auth).

#### Browsing the dashboard through the gateway

1. **Operator opens the dashboard URL** (proxied through Caddy/Traefik + the forward-auth gateway, or through HA's ingress).
   - Sees: the gateway's own login (passkey prompt, or nothing at all if already authenticated to HA) — never a hassette-specific login screen.
   - Then: the request reaches hassette from the gateway's known address (a Compose sibling container, or HA's fixed `172.30.32.2`).
2. **Hassette's auth middleware checks the request's peer address** against `trusted_proxies`.
   - Decides: peer matches a trusted entry → request proceeds with no further credential check. Peer doesn't match → default-deny applies, same as any other unauthenticated request.
   - Then: dashboard loads normally; WebSocket connects normally (also peer-checked, pre-`accept()`).

### Operator: No forward-auth gateway (default / bare Docker install)

- **Goal:** Get a working, protected dashboard without configuring anything.
- **Context:** Fresh install or upgrade, `docker run`/`docker compose up`, no reverse proxy.

#### First start after install or upgrade

1. **Hassette starts.** No `auth_token` configured, no token file exists yet.
   - Sees (in `docker logs`/console): a one-time INFO line with a generated token and a ready-to-use URL.
   - Then: the token is persisted to `<data_dir>/.web_api_token` (mode `0600`, atomic write).
2. **Operator opens the dashboard**, is redirected to a minimal login view.
   - Decides: pastes the token from the log/file into the login form.
   - Then: `POST /api/auth/session` validates it, sets an `HttpOnly`/`SameSite=Strict` session cookie. `Secure` is set when hassette's own auth code (not uvicorn) trusts the request's `X-Forwarded-Proto` header — which it only does when the direct peer matches `trusted_proxies` — and that header says `https`; otherwise `Secure` is unset (see Architecture, "Cookie `Secure` flag").
3. **Ongoing use:** the browser attaches the cookie automatically to REST calls and the WebSocket handshake. No further prompts until the cookie's TTL expires (short default, configurable), at which point the flow repeats.

### Operator or script: CLI / non-browser API access

- **Goal:** Run `hassette` CLI commands or a script against the API without a browser.
- **Context:** SSH session on the VPS, a cron job, a monitoring script.

#### Authenticating a CLI call

1. **CLI reads the credential** from `HASSETTE__WEB_API__AUTH_TOKEN` (env) or the token file — never from a literal `--token <value>` CLI argument (shell-history/`ps`-exposure risk).
2. **CLI attaches `Authorization: Bearer <token>`** to every request.
   - Then: same default-deny middleware validates it via `secrets.compare_digest`; 200 on match, 401 otherwise.

### Operator: Binds non-loopback with no proxy and no TLS

- **Goal:** N/A — this is the misconfiguration case the design must catch, not a scenario the operator intends.
- **Context:** `host` set to `0.0.0.0` (or any non-loopback address), `trusted_proxies` empty — no evidence of a fronting proxy at all.

#### Startup warning

1. **Hassette starts.**
   - Sees: a WARNING-level log line naming both risks explicitly — the bind is reachable beyond localhost, and there's no evidence of TLS termination in front of it. Auth itself is still on (the token still protects the API); the warning is about transport security, not about disabling the service.
   - Then: hassette starts normally — this is a warning, not a hard block (hassette cannot detect a TLS-terminating proxy it doesn't know about).

## Functional Requirements

- **FR#1** Every `/api/*` route rejects requests with no valid credential and no trusted-proxy match, except `GET /api/health/live`, `GET /api/health/ready`, and `POST /api/auth/session`.
- **FR#2** A request whose direct ASGI peer address matches a configured `trusted_proxies` entry (IP, CIDR, or resolved hostname) is treated as authenticated, with no token or cookie required.
- **FR#3** `trusted_proxies` matches only the raw `scope["client"]` peer address — never `X-Forwarded-For` or any other client-suppliable header.
- **FR#4** Uvicorn's own default proxy-header trust (`proxy_headers=True`) is explicitly disabled (`proxy_headers=False`) so `trusted_proxies` is the only proxy-trust mechanism in the request path.
- **FR#5** `trusted_proxies` hostname entries are resolved via DNS at startup and re-resolved on a periodic interval via `Scheduler.run_every()` — not on every request, and not only once at startup.
- **FR#6** A request with a valid `Authorization: Bearer <token>` header (verified via `secrets.compare_digest`) is authenticated.
- **FR#7** A request with a valid session cookie is authenticated; the cookie is minted by `POST /api/auth/session` on a correct bearer token and is stateless (HMAC-derived, keyed by the token, with an embedded issuance timestamp).
- **FR#8** The session cookie is rejected once its embedded issuance timestamp exceeds a configurable TTL (short default).
- **FR#9** On first start with no `auth_token` configured and no existing token file, hassette generates a token (`secrets.token_urlsafe(32)`), persists it atomically (temp file + `os.replace()`, mode `0600`) to `<data_dir>/.web_api_token`, and logs it once at INFO with a ready-to-use URL.
- **FR#10** A corrupt or unreadable existing token file is treated the same as "no file exists" — a fresh token is generated and an ERROR-level log line makes the regeneration visible; the service does not crash.
- **FR#11** The WebSocket handler rejects an unauthenticated/untrusted connection before calling `accept()` — no data flows, no application code runs. The pre-accept code sends `close(code=1008)`, but on this project's `ws="websockets-sansio"` backend that manifests to the client as a rejected handshake (HTTP 403-equivalent), not a delivered WS close frame carrying code 1008 — see "WebSocket auth" in Architecture.
- **FR#12** The frontend WebSocket reconnect logic stops its backoff loop when a connection attempt is rejected before ever opening (a rejected handshake — detected as "closed before `onopen` fired", since code `1008` never actually reaches the browser on this backend) and redirects to the login view, instead of retrying indefinitely.
- **FR#13** Hassette refuses to start if `auth_enabled=false` and `host` is not a loopback address.
- **FR#14** Hassette logs a WARNING at startup when `host` is non-loopback and `trusted_proxies` is empty (no evidence of a fronting proxy), naming TLS explicitly.
- **FR#15** Config load rejects `cors_origins` containing `"*"`. (`allow_credentials=True` is a fixed, hardcoded value in this codebase — `web/app.py:56` — not a configurable field; the validator's job is the wildcard-origin check unconditionally, since the dangerous combination is otherwise always present.)
- **FR#16** Successful authenticated mutation actions (start/stop/reload/trigger/log-level-change) are logged via the existing `"hassette"` logger with source IP.
- **FR#17** Failed authentication attempts are logged as a rate-limited/coalesced WARN (not per-attempt) when they exceed a threshold from a given source in a window. The counted signal is **any outgoing 401 response**, not only requests the middleware itself rejected — an exempt route still traverses the middleware, so `POST /api/auth/session`'s own body-validation failure (the primary token-guessing surface) is counted by the same rule with no shared state between the two modules. Auth is the only source of 401 in this application, so there is nothing else to miscount.
- **FR#18** The CLI reads the credential from the token file or `HASSETTE__WEB_API__AUTH_TOKEN`; no CLI flag accepts a literal token value as a bare argument.
- **FR#19** `GET /api/config` never discloses the plaintext `auth_token` (masked the same way the existing HA `token` field is masked).
- **FR#20** When a request's direct peer (raw `scope["client"]`, never uvicorn-rewritten — `proxy_headers` stays `False`) matches `trusted_proxies`, hassette's own auth code reads that request's `X-Forwarded-Proto` header directly to decide whether the original connection was HTTPS, for the sole purpose of setting the session cookie's `Secure` flag. Untrusted peers' `X-Forwarded-Proto` is never consulted for anything. This is hassette application logic, not uvicorn's `ProxyHeadersMiddleware` — the two mechanisms (auth-bypass peer check, and `Secure`-flag scheme check) both read the same raw, unrewritten `scope["client"]`, so they cannot disagree or interfere with each other.
- **FR#21** Hassette logs at INFO which of the three token-resolution branches fired (explicit config value, existing token file, freshly generated) on every startup — not only when generating a new token.
- **FR#22** A request authenticated by a session cookie whose remaining lifetime has fallen below half of `session_ttl` receives a freshly minted cookie on the response (sliding renewal), so an actively-used dashboard never hits a login form mid-session while the absolute lifetime of any single cookie value stays bounded by `session_ttl`. Requests authenticated by bearer token or trusted-proxy match do not mint or renew a cookie.
- **FR#23** The default-deny middleware gates the `/api/` path prefix only. The static SPA bundle served by the same app (`web/app.py:73-94` — the `/` shell, the `/assets` and `/fonts` mounts, and the catch-all's static-file branch) is reachable without a credential, because the login view is itself part of that bundle and must load before any credential exists. The bundle carries client code and route names only — no operator data, no config values, no entity IDs — so this is not the same disclosure class as the `/api/docs` surface deliberately closed above.

## Edge Cases

- **`trusted_proxies` DNS resolution failure at startup or on periodic refresh** — a hostname entry that fails to resolve fails loudly (same posture as an invalid IP/CIDR literal today), not a silent skip. On periodic refresh specifically: a transient resolution failure keeps the last-known-good resolved address rather than dropping trust immediately, to avoid a flaky DNS blip locking out the proxy.
- **Sibling proxy container recreated mid-run** (new IP, same hostname) — trusted access updates on the next periodic refresh interval, not instantly. This is a bounded window (minutes), not an indefinite restart requirement.
- **Token file write failure** (permissions, read-only filesystem, full disk) at first-generation time — startup fails loudly, naming the exact path and OS error. Silently falling back to an ephemeral in-memory token would mean every `WebApiService` restart (it is `RestartType.TRANSIENT`) mints a new token, invalidating whatever the operator just configured.
- **Concurrent requests during token regeneration** (corrupt-file recovery path) — not a realistic race in practice since this only happens once at startup, before the service accepts traffic; no locking needed beyond the atomic file write itself.
- **`POST /api/auth/session` with a correct token but no existing cookie** — this route is itself exempt from default-deny (it performs its own body-based token validation) so the bootstrap doesn't deadlock.
- **A `trusted_proxies` entry that's wrong or too broad** (e.g., a typo'd CIDR, or `0.0.0.0/0`) — this is a real footgun (an auth *bypass*, not an additive check); the config validator rejects obviously-wrong entries, and documentation states plainly that a bad entry disables auth for whatever it matches.
- **Health endpoints must stay reachable unauthenticated** regardless of any other state — the Docker healthcheck (`curl -sf http://127.0.0.1:8126/api/health/live`) and the future add-on watchdog both depend on this.
- **Existing `docker run -p 8126:8126` deployments after upgrade** — the bind stays `0.0.0.0` (unchanged); the operator sees a new log line with a generated token on first start post-upgrade, and the dashboard/API now returns 401 until that token is provided. This is an intentional, documented behavior change — not a regression, but worth a clear changelog/upgrade note.
- **`/api/docs` and `/api/openapi.json`** — currently unauthenticated (`FastAPI(docs_url=..., openapi_url=...)`, `app.py:48-49`), fall under the same default-deny as everything else; only the three FR#1 exemptions are carve-outs.
- **An open WebSocket outlives the cookie that authorized it** — cookies are only sent in the HTTP upgrade request, so a socket's view of its credential is frozen at `accept()` and sliding renewal (FR#22) never reaches it. Authorization is therefore checked at connect only; a tab left open and idle keeps receiving live updates after its cookie's TTL has passed. Accepted deliberately: re-auth happens on every reconnect (`WebApiService` is `RestartType.TRANSIENT`, so restarts are routine; network blips and tab reloads do the rest), and the alternatives are worse — any periodic or scheduled re-check re-validates the *connect-time* cookie, so it would close the socket of an actively-used dashboard whose browser already holds a renewed one, sending an authenticated operator to a login form. Documented as a known limitation rather than papered over.
- **`auth_enabled=false` alone is never sufficient to start** — `WebApiConfig.host` defaults to `"0.0.0.0"` (`config/models.py:342`), which is non-loopback, so FR#13's hard block fires for an operator (or a test fixture) that disables auth without also pinning `host` to a loopback address. This is the intended behavior, not an oversight, but it makes `auth_enabled=false` a two-field change in practice — the error message must name both settings so the second one isn't a guessing game.

## Acceptance Criteria

- **AC#1** `curl` (or an `httpx` test client) against any mutation endpoint, `/source`, `/config`, or the WS upgrade with no credential returns 401 (or WS close 1008). Maps to FR#1, FR#11.
- **AC#2** The same request with a correct `Authorization: Bearer <token>` header returns 200. Maps to FR#6.
- **AC#3** The same request with a correct session cookie returns 200. Maps to FR#7.
- **AC#4** A request whose peer matches a `trusted_proxies` IP or CIDR entry returns 200 with no credential. Maps to FR#2, FR#3.
- **AC#5** A request whose peer matches a `trusted_proxies` hostname entry (resolved at startup) returns 200 with no credential; a test simulating the hostname's IP changing between startup and a simulated periodic-refresh tick confirms the new IP becomes trusted after refresh. Maps to FR#2, FR#5.
- **AC#6** A spoofed `X-Forwarded-For: <trusted-IP>` header from an untrusted direct peer is rejected exactly like any other unauthenticated request. Maps to FR#3, FR#4.
- **AC#7** `GET /api/health/live`, `GET /api/health/ready`, and `POST /api/auth/session` (with no prior credential) are all reachable with zero credentials. Maps to FR#1.
- **AC#8** Starting hassette with `auth_enabled=false` and `host="0.0.0.0"` fails at startup with an error naming both settings. Maps to FR#13.
- **AC#9** Starting hassette with `host="0.0.0.0"` and `trusted_proxies` empty produces a WARNING log line naming TLS; starting with a non-empty `trusted_proxies` produces no such warning. Maps to FR#14.
- **AC#10** Config load with `cors_origins=("*",)` raises a validation error. Maps to FR#15.
- **AC#11** `GET /api/config` (authenticated) never contains the plaintext token value in its response body — asserted via a system test mirroring the existing HA-token non-disclosure test (`tests/system/test_web_api.py:75-93`). Maps to FR#19.
- **AC#12** A corrupted/truncated token file at startup results in a fresh token being generated, an ERROR log line, and the service reaching ready state — not a crash. Maps to FR#10.
- **AC#13** A frontend test (or manual verification) confirms the WS client stops reconnecting and navigates to the login view on receiving close code 1008, rather than retrying indefinitely. Maps to FR#12.
- **AC#14** `hassette status`/CLI commands authenticate successfully using the token file or `HASSETTE__WEB_API__AUTH_TOKEN`, and no CLI subcommand accepts a literal `--token <value>` argument (`--help` output and/or source inspection confirms). Maps to FR#18.
- **AC#15** A cookie minted more than `session_ttl` seconds ago is rejected on the next request; one minted within the TTL is accepted. Maps to FR#8.
- **AC#16** A `start`/`stop`/`reload`/`trigger`/log-level-change request from an authenticated caller produces a log line (visible via `GET /api/logs/recent`) naming the action and source IP. Maps to FR#16.
- **AC#17** A burst of failed-auth requests from one source within a window produces exactly one coalesced WARN log line (not one per attempt), visible via `GET /api/logs/recent`. Maps to FR#17.
- **AC#18** A request from a `trusted_proxies` peer with `X-Forwarded-Proto: https` results in a `Secure`-flagged cookie on the subsequent `POST /api/auth/session`; the same request from a non-trusted peer with the same header spoofed does not. Maps to FR#20.
- **AC#19** Each of the three token-resolution branches (explicit config, existing file, freshly generated) produces a distinct, identifiable INFO log line at startup — verified by exercising each branch and asserting on the log output. Maps to FR#21.
- **AC#20** A request carrying a cookie past its half-life returns a `Set-Cookie` header with a newly minted value that verifies successfully; a request carrying a fresh cookie (before its half-life) returns no `Set-Cookie` header; a request authenticated by bearer token or trusted-proxy match returns no `Set-Cookie` header. Maps to FR#22.
- **AC#21** `GET /` and a representative asset path under `/assets` return their content with no credential, while `GET /api/config` with no credential still returns 401 — the middleware gates the `/api/` prefix and nothing else. Maps to FR#23.
- **AC#22** A burst of wrong-token `POST /api/auth/session` requests from one source produces the same coalesced WARN as a burst against a gated route — the login endpoint's own 401s are counted. Maps to FR#17.

## Key Constraints

- `trusted_proxies` must compare against `scope["client"]` only — never a client-suppliable header. This is the single most consequential control in the design (Addendum 2, Finding 1/C1); do not implement header-based trust as a shortcut.
- Do not reuse `InvalidAuthError` (`exceptions.py:140`) for any new auth-failure exception — it is a `FatalError` subclass wired into `websocket_service.py`'s `NON_RETRYABLE` tuple and means "HA rejected hassette's own outbound token." New exceptions are plain `HassetteError` subclasses under different names.
- No new third-party dependencies. `fastapi.security`, stdlib `secrets`/`hmac`/`ipaddress`/`socket` cover the full design.
- Do not build password-based accounts, hashing, or a claim/setup wizard — see Non-Goals and Alternatives Considered. This was explored in depth during design and deliberately reverted.
- `trusted_proxies` hostname entries resolve periodically (via `Scheduler.run_every()`), never per-request — per-request resolution was rejected as a DNS-rebinding risk with no operational benefit over a periodic interval.
- Do not change the default `host` bind from `0.0.0.0`. Flipping it to `127.0.0.1` would silently break every documented `docker run -p`/Compose deployment (the container healthcheck would keep passing while the UI became unreachable). Safety comes from auth-on-by-default plus the startup guard (FR#13/FR#14), not from the bind address.

## Dependencies and Assumptions

- **Docker Compose embedded DNS**: `trusted_proxies` hostname resolution assumes the container running hassette can resolve sibling-service hostnames via Compose's embedded resolver. If hassette starts before the target service registers its DNS record (no `depends_on` ordering guarantee), the first resolution attempt may fail — mitigated by the periodic-refresh design (FR#5), which will pick it up on the next tick rather than requiring a restart.
- **HA Supervisor's ingress gateway address (`172.30.32.2`) is stable** per HA's own add-on documentation — this is an external assumption inherited from ADR-0005, not something hassette controls.
- **The HA add-on epic (#71) design artifacts need a parallel documentation update** (ADR-0005, `prereq-03-ingress-source-guard.md`, `prereq-04-addon-repo-skeleton.md`) — sequenced as a follow-up to this implementation, not a blocker for it, since those artifacts describe unreleased add-on work. See Replacement Targets.
- **`WebApiService.depends_on` (currently `[RuntimeQueryService, TelemetryQueryService]`, `core/web_api_service.py:28`) must gain `SchedulerService`**, and `WebApiService` needs a child `Scheduler` (via `self.add_child(Scheduler)`, the established pattern for a framework service that needs periodic scheduling — cf. `StateProxy`) to drive the periodic `trusted_proxies` DNS-refresh job (FR#5). Not yet present in the codebase; part of this implementation, not an external dependency.
- **Two claims from the research brief still need empirical verification before or during implementation** (not resolved at design time): Docker's loopback-bind-unreachable-from-host behavior (underpins the "don't change the default bind" recommendation), and whether `websocket.close(code=1008)` before `accept()` behaves cleanly under this project's specific `ws="websockets-sansio"` uvicorn backend. See Open Questions.

## Architecture

### Credential model

Two independent trust mechanisms, checked in order by a single default-deny ASGI middleware:

1. **Trusted proxy** (`web_api.trusted_proxies: tuple[str, ...] = ()`) — the recommended path for any operator running a forward-auth gateway in front of hassette (a self-managed setup like Caddy + tinyauth + pocket-id, Authelia, or the future HA add-on's ingress). Entries are IPs, CIDRs, or hostnames. IP/CIDR entries parse via `ipaddress` at config load (fails loudly on a typo). Hostname entries resolve via `socket.getaddrinfo` — once at startup, then periodically via a `Scheduler.run_every()` job (interval: a few minutes) that re-resolves and swaps in the current address set. This generalizes the add-on's fixed `172.30.32.2` case and the self-managed reverse-proxy case (where a Compose sibling container's IP can drift on recreate) under one mechanism, without requiring the operator to pin a static Compose IP.

   The middleware compares only the raw ASGI `scope["client"]` peer address against this set — never `X-Forwarded-For` or any other header. `uvicorn.Config` in `WebApiService.serve()` (`core/web_api_service.py:65-73`) gains an explicit `proxy_headers=False`, so hassette's own `trusted_proxies` check is the only proxy-trust mechanism in the request path — uvicorn's own default `ProxyHeadersMiddleware` (which would otherwise silently trust `X-Forwarded-For` from whatever `FORWARDED_ALLOW_IPS` resolves to, default `"127.0.0.1"`) is disabled outright.

2. **Bearer token / session cookie** — the always-available fallback for installs with no proxy in front. A single static token (`web_api.auth_token: SecretStr | None = None`), resolved in `WebApiService.on_initialize()` in this order: explicit config/env value → `<data_dir>/.web_api_token` → generate `secrets.token_urlsafe(32)`, write atomically (temp file + `os.replace()`, mode `0600`). Whichever branch fires, hassette logs at INFO which one it was (FR#21) — not only the generate branch — so an operator who loses a previously-working token file (volume not migrated, `docker compose down -v`) sees "loaded existing file" vs. "generated a new one" as distinguishable, not silent, events. `auth_token` is declared `SecretStr` specifically so `GET /api/config` masks it via the same `mask_values()` mechanism (`web/config_view.py:74-98`) that already masks the HA token — this is not optional, it's what prevents the credential that protects `/api/config` from being disclosed *by* `/api/config`.

   Non-browser clients (CLI, scripts) send `Authorization: Bearer <token>`, checked via `secrets.compare_digest` (timing-safe). Browsers exchange the token once via `POST /api/auth/session` for an `HttpOnly`/`SameSite=Strict` cookie — necessary because the native browser `WebSocket` API cannot set custom headers, so the cookie is what lets the same credential authenticate both REST calls and the WS handshake with zero special-casing in `use-websocket.ts`. The cookie value is derived via HMAC (keyed by the token) over a random session id plus an embedded issuance timestamp, checked against a configurable TTL at validation time — stateless, so it survives `WebApiService`'s `RestartType.TRANSIENT` restarts without a server-side session table.

`session_ttl` bounds the lifetime of any single cookie *value*, not the length of a working session: once a cookie passes its half-life, the next request it authenticates comes back with a freshly minted replacement (FR#22). An operator actively using the dashboard is never interrupted, while a cookie that leaks stops working within `session_ttl` of the moment it was minted. This matters because the TTL is the only revocation lever in the design — the cookie is derived from the token, so revoking one session means rotating the token, which invalidates every session and every script. Without renewal, a genuinely short TTL would mean re-pasting the token out of `docker logs` on a fixed interval for as long as the dashboard is open, which is why "short default" alone was not a sufficient answer.

### Cookie `Secure` flag

This mechanism is deliberately **not** built on uvicorn's `proxy_headers`/`forwarded_allow_ips` machinery, because that machinery conflicts with the peer-check design above: `ProxyHeadersMiddleware` is the outermost ASGI layer, wrapping the app *before* hassette's own middleware ever runs — if it rewrote `scope["client"]` from `X-Forwarded-For` for trusted peers, hassette's own `trusted_proxies` check (which needs the *direct, unrewritten* peer to decide the auth bypass) would never see the proxy's real address again for that request. Enabling `proxy_headers=True` to get `X-Forwarded-Proto` honored would silently break FR#2/FR#3. `proxy_headers` therefore stays `False` unconditionally (FR#4) — uvicorn never touches `scope["client"]` or `scope["scheme"]` for any request.

Instead, hassette's own auth code reads `X-Forwarded-Proto` directly from the request headers in application code (FR#20), and only trusts it when that same request's raw `scope["client"]` matches `trusted_proxies` — the identical check FR#2/FR#3 already perform, reused rather than duplicated. When trusted and `https`, `POST /api/auth/session` sets `Secure` on the minted cookie; otherwise it doesn't. This keeps the auth-bypass decision and the `Secure`-flag decision reading the same single, never-rewritten signal, so they can't contradict each other. Operators with no `trusted_proxies` entry (the no-proxy fallback case) always get a non-`Secure` cookie, matching the fact that hassette itself has no TLS support and the FR#14 startup warning already tells them why that matters.

### Middleware and routing

New `src/hassette/web/middleware.py` — a single Starlette `BaseHTTPMiddleware` subclass implementing both checks above (trusted-peer short-circuit, then bearer/cookie validation), applied default-deny to every route under the `/api/` prefix (FR#23).

`BaseHTTPMiddleware` rather than a raw ASGI middleware, because two of this middleware's responsibilities are response-side and a raw implementation would have to intercept the `send` callable for both: sliding renewal (FR#22) sets a `Set-Cookie` header on the way out, and the coalesced failed-auth counter (FR#17) reads the outgoing status so that an exempt route's own 401 is counted without a shared tracker object. `BaseHTTPMiddleware` also only sees `http`-scope requests, which is the desired behavior here — the WebSocket handshake bypasses it entirely and is gated separately by `authorize_ws()` (see WebSocket auth below), so there is no second path through this middleware to keep consistent.

The static SPA bundle (`web/app.py:73-94`) is outside the gated prefix by construction. This is deliberate and load-bearing, not an oversight: the login view is part of that bundle, so gating it would make the credential unreachable — a browser with no cookie would get 401 on the HTML document and on every asset, and the operator would have no way to present the token they just read out of `docker logs`.

Registered in `web/app.py` **inside** `CORSMiddleware` (i.e., added after CORS in the registration order, since Starlette applies middleware in reverse-registration order — CORS must be the outermost layer so a preflight `OPTIONS` request gets a proper CORS response before the auth check would otherwise reject it with an opaque error). This exact ordering claim has not been independently verified against a running app — see Open Questions.

Three explicit exemptions from default-deny: `GET /api/health/live`, `GET /api/health/ready` (existing routes, `web/routes/health.py`), and `POST /api/auth/session` (new route, `web/routes/auth.py`) — the login exchange itself must be reachable with zero prior credential, since it's the one endpoint whose entire job is validating a credential presented in the request body rather than a header or cookie.

`POST /api/auth/session`'s request body is `{"token": "<bearer-token>"}` — a `SessionRequest` model (`web/models.py`, following `LogLevelRequest`'s existing single-field request-body shape) with one field, `token: str`. Pinned here because T06 (backend) and T12 (frontend) build this route's two ends with no dependency on each other; both must target this exact field name.

`/api/docs` and `/api/openapi.json` (`FastAPI(docs_url=..., openapi_url=...)` in `web/app.py:48-49`) are **not** exempted — they fall under the same default-deny as every other route, closing the unauthenticated API-schema fingerprinting surface identified during hardening.

### WebSocket auth

`web/routes/ws.py:85-87` currently calls `websocket.accept()` unconditionally as its first line. This changes to a pre-accept check reading `websocket.cookies` (browser clients) or `websocket.headers` (non-browser clients — e.g. the `websockets` library's `additional_headers` parameter, which existing non-browser callers can use to attach `Authorization: Bearer <token>` at connect time; no existing test in this repo currently does this, so this is new test coverage, not an existing pattern being extended) via the same validator used by the HTTP middleware, closing with code `1008` (policy violation) on failure before `accept()` is ever called:

```python
if not authorize_ws(websocket, hassette.config.web_api):
    await websocket.close(code=1008)
    return
await websocket.accept()
```

**Resolved during implementation (T07):** `websocket.cookies`/`websocket.headers` are populated at this pre-accept point, but the `close(code=1008)` call itself does not survive this backend as written above. Empirically, `ws="websockets-sansio"` hardcodes any pre-accept `websocket.close` ASGI message into an HTTP 403-equivalent handshake rejection, discarding the application-supplied close code entirely — the client never observes a WS close frame carrying `1008`. A non-browser client sees a failed handshake (`websockets.exceptions.InvalidStatus`, status 403); a browser's native `WebSocket` sees `onclose` fire with code `1006` (abnormal closure) and, critically, this happens **before `onopen` ever fires** for that connection attempt. The code above is still what's implemented (`accept()` is genuinely never called, no data flows to an unauthenticated peer — the security property holds), but "delivered as WS close 1008" is not literally true on the wire; see the WebSocket reconnect paragraph below for how the frontend actually detects this.

Authorization happens at connect and is never re-checked for the life of the connection. The handler (`web/routes/ws.py:86-88`) runs the socket inside an `anyio` task group until it disconnects, and cookies only travel in the HTTP upgrade request, so a socket holds whatever credential authorized it and sliding renewal (FR#22) never reaches it. See the Edge Cases entry for why re-checking would be worse than the exposure it closes.

`frontend/src/hooks/use-websocket.ts` currently retries on every close with exponential backoff and no branch on `event.code` (`onclose` handler at `use-websocket.ts:148-158`, calling `scheduleReconnect()` at `use-websocket.ts:165-169`). **Revised per the above:** since a rejected handshake never delivers `event.code === 1008` on this backend, the actual signal used is whether `onopen` fired for the current connection attempt. A close that arrives before `onopen` ever fired for that attempt is treated as a rejected handshake (auth failure): stop the backoff loop and redirect to the new login view instead of retrying against a connection a fresh cookie won't fix. A close that arrives after `onopen` had already fired (a previously working connection dropping — network blip, server restart) keeps the existing reconnect-with-backoff behavior unchanged, regardless of close code.

### Startup guards

Two checks in `WebApiService.on_initialize()`/`serve()` (`core/web_api_service.py`):

- **Hard block**: `auth_enabled=false` and `host` not loopback → refuse to start, error naming both settings.
- **Warning, not a block** (hassette cannot detect an external TLS-terminating proxy): `host` not loopback and `trusted_proxies` empty (no evidence of a fronting proxy at all) → WARNING log line naming TLS explicitly at startup.

### CORS validator

A `field_validator`/model validator on `WebApiConfig` (or a startup check alongside the guards above) rejects `"*"` in `cors_origins`. `allow_credentials=True` is a fixed, hardcoded argument to `CORSMiddleware` in `web/app.py:56` — not a configurable field — so the dangerous `allow_credentials=True` + wildcard-origin combination is unconditionally present whenever `cors_origins` contains `"*"`; the validator does not need to check `allow_credentials` itself, only reject the wildcard. This closes the still-open audit finding (issue #1117 AC #5) at config load rather than leaving Starlette to reject it at request time with a confusing error.

### Misuse-visibility logging

Two additions routed through the existing `"hassette"` logger (`getLogger(__name__)` convention used throughout the codebase, e.g. `web/dependencies.py:21`), so they flow into `/api/logs/recent` and the dashboard's log view the same as any other framework log line:

- Successful authenticated mutation actions (start/stop/reload/trigger/log-level-change) logged with source IP at INFO.
- Failed authentication attempts logged as a rate-limited/coalesced WARN when they exceed a threshold from a given source in a window (e.g., "12 failed auth attempts from 203.0.113.4 in the last 5 minutes") — not per-attempt, to avoid reintroducing the noise problem a naive per-attempt log would cause.

The failed-attempt counter keys off **any outgoing 401**, observed on the response as it leaves the middleware, rather than off the middleware's own reject decision. This is what makes `POST /api/auth/session` countable: that route is exempt from being *blocked*, but the request still traverses the middleware, so its handler-issued 401 is visible on the way out. Counting rejections instead would leave the one endpoint whose entire job is validating a credential — the obvious target for a guessing script — as the only unmonitored surface in the design. It also means any exemption added later is covered without a second registration step. The counter exists purely to produce the WARN; it never rejects or throttles a request (rate limiting is an explicit Non-Goal), and it must evict old entries so a sustained burst cannot grow it without bound.

### CLI

`src/hassette/cli/client.py` currently builds `HassetteConfig(token=None)` for the HA token and sends no credential at all for the web API. This gains: read `HASSETTE__WEB_API__AUTH_TOKEN` (env) or `<data_dir>/.web_api_token` (file) and attach `Authorization: Bearer <token>` to every request. No CLI flag accepts a literal token value as a bare argument (visible in `ps`/shell history for the process's lifetime) — matching the project's existing posture toward the HA token itself.

## Implementation Preferences

- `AuthDep` follows the existing `Annotated[X, Depends(get_x)]` pattern in `web/dependencies.py` (`HassetteDep`, `RuntimeDep`, etc., lines 67-71) rather than inventing a new DI convention.
- `auth_token` is `SecretStr | None`, mirroring `HassetteConfig.token` (`config/config.py:142-151`) exactly, including the `.get_secret_value()`-only-at-point-of-use discipline (`config/config.py:255-257`).
- New exceptions are flat `HassetteError` subclasses (`exceptions.py`), following the existing hierarchy's convention of mostly-docstring-only classes with a custom `__init__` only when structured data needs to travel with the exception (cf. `RetryableConnectionClosedError`, `exceptions.py:89-94`).
- New `WebApiConfig` fields use the existing `Field(default=...)` + docstring-below pattern with `ui.label`/`ui.group_label` metadata where the dashboard's config editor needs it (`config/models.py:323-359`).
- No new dependencies. `fastapi.security` (`APIKeyHeader`/`HTTPBearer`, already ships with FastAPI 0.136.3) plus stdlib `secrets`, `hmac`, `ipaddress`, and `socket` cover the entire design.

## Replacement Targets

**`design/research/2026-07-07-ha-addon-architecture/prereq-03-ingress-source-guard.md`** (the `web_api.allowed_client_ips` design, not yet implemented in any shipped code) is superseded by `trusted_proxies`. This is a documentation-only replacement — no shipped code exists to migrate away from, since prereq-03 was never implemented. Concrete follow-up edits (sequenced separately, not part of this implementation, since they touch an unreleased epic's design artifacts):

- Mark `prereq-03-ingress-source-guard.md` superseded, pointing at this design doc.
- `prereq-04-addon-repo-skeleton.md`'s `run.sh` step exports `HASSETTE__WEB_API__TRUSTED_PROXIES` unconditionally (the ingress gateway is always trusted) instead of `ALLOWED_CLIENT_IPS` conditionally — this also removes the `hassio_api: true`/`addons/self/info` port-mapping lookup from `run.sh`, simplifying prereq-04.
- `design/research/2026-07-07-ha-addon-architecture/research.md:266`'s statement that "the direct-port path remains unauthenticated by design in v0.1" becomes false once this ships — needs a follow-up note. `design/adrs/0005-ha-addon-packaging.md:38` similarly documents the optional host-port path as "reproduces today's Docker trust model and is documented as unauthenticated" — also needs a follow-up note or superseding ADR once the direct port is authenticated by default.

## Migration

No schema or persistent-data migration. The only new on-disk artifact is `<data_dir>/.web_api_token` (generated on first start with no configured token), which lands in the same Docker volume that already persists `data_dir` today — no new volume mount required.

**Operational transition worth documenting explicitly**: existing deployments upgrading to this version will, on first restart, find auth turned on by default with no configured token — a generated token appears in the log, and the dashboard/API return 401 until the operator retrieves and uses it. This is an intentional behavior change (closing an active security gap), not a bug, but it will break any existing bookmark, script, or HA dashboard iframe pointed directly at the hassette UI without a credential until the operator updates it. Flag this prominently in release notes.

## Convention Examples

### Dependency injection accessor pattern

**Source:** `src/hassette/web/dependencies.py:46-71`

```python
def get_hassette(request: Request) -> "Hassette":
    return request.app.state.hassette


def get_runtime(request: Request) -> "RuntimeQueryService":
    return request.app.state.hassette.runtime_query_service


# Shared dependency type aliases — import these instead of re-defining locally.
HassetteDep = Annotated["Hassette", Depends(get_hassette)]
RuntimeDep = Annotated["RuntimeQueryService", Depends(get_runtime)]
```

`AuthDep` follows this exact shape: a plain accessor function plus an `Annotated[X, Depends(...)]` alias, added to the same "Shared dependency type aliases" block.

### `SecretStr` + masking pattern

**Source:** `src/hassette/config/config.py:142-151, 255-257`

```python
token: SecretStr | None = Field(
    default=None,
    validation_alias=AliasChoices("token", "hassette__token", "ha_token", "home_assistant_token"),
)
"""Access token for Home Assistant instance.

Stored as a :class:`~pydantic.SecretStr` so the value is masked in logs
and string representations.  Unwrap with ``token.get_secret_value()`` when
the plaintext is required (e.g. HTTP auth headers, WebSocket auth payload).
"""

@property
def auth_headers(self) -> dict[str, str]:
    if self.token is None:
        return {}
    return {"Authorization": f"Bearer {self.token.get_secret_value()}"}
```

`auth_token` on `WebApiConfig` mirrors this exactly — `SecretStr | None`, a docstring explaining the masking rationale, `.get_secret_value()` called only at the point of use (the `Authorization` header comparison / cookie minting).

### Exception hierarchy

**Source:** `src/hassette/exceptions.py:36-45, 89-94`

```python
class HassetteError(Exception):
    """Base exception for all Hassette errors."""


class FatalError(HassetteError):
    """Custom exception to indicate a fatal error in the application.

    Exceptions that indicate that the service should not be restarted should inherit from this class.
    """


class RetryableConnectionClosedError(ConnectionClosedError):
    """Custom exception to indicate that the WebSocket connection was closed but can be retried."""

    def __init__(self, msg: str, *, close_code: int | None = None) -> None:
        super().__init__(msg)
        self.close_code = close_code
```

New auth exceptions are plain `HassetteError` subclasses (not `FatalError` — an auth failure should not crash or block-restart the service), mostly docstring-only, with a custom `__init__` only if structured data needs to travel (unlikely here — a 401/403 mapping doesn't need it).

### Router pattern

**Source:** `src/hassette/web/routes/health.py` (full file)

```python
"""Health and status endpoints."""

from fastapi import APIRouter, Response

from hassette.web.dependencies import RuntimeDep
from hassette.web.mappers import readiness_response_from, system_status_response_from
from hassette.web.models import LivenessResponse, ReadinessResponse, SystemStatusResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=SystemStatusResponse)
async def get_health(runtime: RuntimeDep) -> SystemStatusResponse:
    """Return the full system status. Always HTTP 200 while the process can serve."""
    return system_status_response_from(runtime.get_system_status())
```

New `web/routes/auth.py` follows this shape: `APIRouter(tags=["auth"])`, `response_model=` on every route, registered in `web/app.py` with `app.include_router(auth_router, prefix="/api")` alongside the existing routers.

### Test fixture pattern

**Source:** `tests/integration/web_api/conftest.py:1-60`

```python
@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance for the FastAPI app."""
    return create_hassette_stub(
        run_web_ui=False,
        states={...},
        old_snapshot=AppStatusSnapshot(running=[instance], failed=[]),
        app_action_mocks=True,
    )


@pytest.fixture
def app(mock_hassette, runtime_query_service):
    """Create a FastAPI app with mocked dependencies."""
    return create_fastapi_app(mock_hassette)
```

`create_hassette_stub()` gains an `auth_enabled` parameter, defaulting to `False`, so the existing ~211 integration and ~165 e2e tests pass unchanged; `tests/integration/web_api/test_auth.py` explicitly passes `auth_enabled=True` to exercise the new behavior.

## Alternatives Considered

**User-chosen password + setup wizard (Uptime Kuma / Portainer model)** — explored in depth during discovery. Rejected: this pattern is standard for full-dashboard self-hosted apps in general, but reopens a genuine security problem for hassette's typical *unattended* start (Docker/systemd/VPS reboot, not an interactive first-run): the setup wizard is open to whoever reaches it first, and the gap between "container starts" and "operator opens the dashboard" can be minutes to days, unlike Portainer's assumption of an interactive first run. A loopback-only wizard plus a CLI claim command was designed as a mitigation but added password hashing, weak-password validation, and concurrent-claim handling — real new complexity solving a problem the simpler token+cookie fallback already handles adequately for hassette's single-operator scope.

**Native HTTP Basic Auth prompt instead of a custom login form** — considered as a way to avoid building custom login UI (the browser's own credential prompt would appear instead). Not chosen: the custom login view was already scoped in the original research brief, and Addendum 2's WS-reconnect fix (FR#12) is built around redirecting to that view specifically. Revisiting this trade later is cheap if the custom login view proves to be more work than expected.

**Delegate auth entirely to a reverse proxy, no hassette-side auth at all** — this is what the docs currently recommend (`docs/pages/web-ui/index.md:23-24`). Rejected in the original research: it does nothing for a sibling container on the same Docker bridge reaching the port directly, bypassing the proxy entirely — exactly the case `trusted_proxies` closes. Remains a good complement, not a substitute.

**Multiple, individually-revocable API tokens (GitHub-PAT / Gitea-token model)** — confirmed as the actual norm for comparable full-dashboard self-hosted apps (Nextcloud, Gitea, Grafana, Immich). Deferred rather than built now: a single shared token is simpler and adequate for a solo operator; the gap (can't revoke one leaked script's credential without invalidating the browser session too) is real but acceptable at this scope. Worth revisiting if hassette's operator base broadens.

**`allowed_client_ips` (prereq-03's original design)** — a peer-IP allowlist with no credential requirement, existing only as an unimplemented HA-add-on-epic design artifact. Superseded by `trusted_proxies` + a real credential requirement; see Replacement Targets.

## Test Strategy

### Required Test Types

Unit (new validator/matcher logic — `trusted_proxies` IP/CIDR/hostname parsing, HMAC cookie mint/verify, config validators — each is single-module logic). Integration (the full auth flow crosses the FastAPI app, middleware, and dependency layers — `tests/integration/web_api/`). E2E (the browser-facing login → cookie → REST + WS flow is a genuine cross-layer user-facing workflow, and this repo has Playwright infrastructure already exercising the WS surface).

### Existing Tests to Adapt

- `src/hassette/test_utils/web_mocks.py` — `create_hassette_stub()` gains an `auth_enabled` parameter (default `False`) so the existing ~211 `tests/integration/web_api/` tests and ~165 `tests/e2e/` Playwright tests keep passing unchanged.
- `tests/integration/web_api/conftest.py:61-66` — the shared `app` fixture may need a variant or parameter for auth-enabled tests.
- `tests/e2e/conftest.py:298-359` — `base_url`/`browser_context_args` fixtures need a path to set the session cookie directly (`context.add_cookies([...])`) for the one new auth-covering e2e test, rather than driving the login form for every existing test.
- `tests/system/test_web_api.py:75-93` — the existing HA-token non-disclosure system test is the template for AC#11's new auth-token non-disclosure assertion, not itself modified.
- `tests/unit/cli/test_client.py:80` — tests the existing `0.0.0.0`→`127.0.0.1` CLI rewrite; unaffected by this change, confirmed still valid.

### New Test Coverage

- `tests/integration/web_api/test_auth.py` (new): no credential → 401 (FR#1, AC#1); wrong bearer token → 401; correct bearer → 200 (FR#6, AC#2); correct cookie → 200 (FR#7, AC#3); expired cookie (TTL exceeded) → 401 (FR#8, AC#15); `trusted_proxies` IP/CIDR peer → 200 (FR#2, AC#4); `trusted_proxies` hostname peer → 200, including a simulated periodic-refresh tick after the resolved IP changes (FR#5, AC#5); spoofed `X-Forwarded-For` from an untrusted peer → still 401 (FR#3/FR#4, AC#6); spoofed `X-Forwarded-Proto: https` from an untrusted peer does not produce a `Secure` cookie, but a genuine `https` header from a trusted peer does (FR#20, AC#18); health + login routes reachable with zero credentials (FR#1, AC#7); CORS `"*"` rejected at config load (FR#15, AC#10).
- `tests/integration/web_api/test_ws_endpoint.py` (existing file, extended): WS connection rejected with close code 1008 pre-`accept()` when unauthenticated (FR#11, AC#1); accepted when authenticated via cookie and via `Authorization` header (the latter using the `websockets` library's `additional_headers` parameter — new coverage, no existing precedent to extend).
- New unit tests for `web/middleware.py`, `web/auth.py` (token resolution, atomic write, corrupt-file recovery — FR#9/FR#10, AC#12; distinct log line per resolution branch — FR#21, AC#19), and the `trusted_proxies` config validator (unit-level, isolated from the FastAPI app).
- New system test (mirroring `tests/system/test_web_api.py:75-93`) asserting the plaintext `auth_token` never appears in `GET /api/config` (FR#19, AC#11).
- New unit tests for both startup guards: `auth_enabled=false` + non-loopback `host` refuses to start (FR#13, AC#8); non-loopback `host` + empty `trusted_proxies` produces the WARNING log line, non-empty `trusted_proxies` suppresses it (FR#14, AC#9).
- New integration tests asserting a mutation action produces a source-IP-tagged log entry (FR#16, AC#16) and a burst of failed-auth attempts from one source produces one coalesced WARN, not one per attempt (FR#17, AC#17) — both verified via `GET /api/logs/recent`.
- One new e2e test (`tests/e2e/`) covering login → cookie set → authenticated REST call → authenticated WS connect, with the cookie injected via `context.add_cookies` rather than driving the login form UI (FR#7, FR#12 partial — the reconnect-on-1008 behavior is better covered at the unit/component level for `use-websocket.ts` given Playwright's limited ability to simulate a server-initiated close mid-test).
- Frontend unit/component test for `use-websocket.ts`'s new `event.code === 1008` branch (FR#12, AC#13).
- CLI test confirming `hassette` commands attach the bearer token from file/env and that no subcommand exposes a literal `--token <value>` argument (FR#18, AC#14).
- Sliding-renewal coverage (FR#22, AC#20): a cookie past its half-life comes back renewed, a fresh one does not, and neither a bearer-authenticated nor a trusted-proxy-authenticated request mints one.
- Middleware-scope coverage (FR#23, AC#21): `GET /` and an `/assets` path return content with no credential while `GET /api/config` still returns 401 — the test that would catch a middleware accidentally gating the login view's own assets.
- Login-endpoint brute-force coverage (FR#17, AC#22): a burst of wrong-token `POST /api/auth/session` requests produces the same coalesced WARN as a burst against a gated route.

### Tests to Remove

No tests to remove — this is purely additive.

## Documentation Updates

- `docs/pages/web-ui/index.md:17-24` — the existing "No authentication" warning block is rewritten: the token/trusted-proxy model is the primary control, the loopback bind becomes an optional additional layer, and `trusted_proxies` becomes the documented path for a self-managed reverse-proxy/forward-auth setup (naming Caddy/Traefik/nginx + a forward-auth layer like Authelia or tinyauth as the recommended pairing, alongside the existing HA add-on ingress case). Include a concrete reverse-proxy TLS-termination snippet — the current doc only name-drops "Caddy, nginx, and Traefik all work" with no example.
- `docs/pages/cli/configuration.md` — document `HASSETTE__WEB_API__AUTH_TOKEN`, the token-file location, and the CLI's credential-resolution order.
- `docs/pages/getting-started/docker/index.md` and `docs/pages/getting-started/docker/troubleshooting.md` — both currently describe unauthenticated access; update to reflect the token flow and the upgrade-transition behavior (Migration section above).
- `docs/pages/web-ui/health-endpoints.md` — the "Aggregate status" section (`GET /api/health`) and its table row ("Human inspection... manual checks") don't mention a credential today. `/api/health` is not one of FR#1's three exemptions — unlike `/api/health/live` and `/api/health/ready`, it now requires the same bearer token, cookie, or trusted-proxy match as any other `/api/*` route. Update the table and the "Aggregate status" section to say so; the `/live`/`/ready` sections and the Quick Check (which already only uses `/api/health/live`) are unaffected.
- `hassette.schema.json` — regenerate after the new `WebApiConfig` fields land.
- `docs/screenshots.yml` + `docs/_static/web_ui_*.png` — add a manifest entry for the login view and regenerate any screenshot whose page changed, per `.claude/rules/design-completeness.md`. This depends on the demo stack authenticating (see Impact), which is why that plumbing ships in this PR rather than as follow-up.
- `design/adrs/0005-ha-addon-packaging.md`, `design/research/2026-07-07-ha-addon-architecture/prereq-03-ingress-source-guard.md`, `prereq-04-addon-repo-skeleton.md` — see Replacement Targets. Sequenced as a follow-up, not blocking this implementation.
- CHANGELOG: this is a `feat!`-worthy behavior change (auth on by default) — needs a clear breaking-change note per `.claude/rules/changelog-quality.md`, written at PR-creation time per the project's changelog-timing convention.

## Impact

### Changed Files

- **Create** `src/hassette/web/middleware.py` — default-deny ASGI middleware (trusted-peer check + bearer/cookie validation)
- **Create** `src/hassette/web/auth.py` — token resolution, atomic write, `compare_digest` check, `trusted_proxies` peer/hostname matching, cookie mint/verify, `authorize_ws()`
- **Create** `src/hassette/web/routes/auth.py` — `POST /api/auth/session`
- **Modify** `src/hassette/web/app.py` — register the middleware inside `CORSMiddleware`; do not exempt `/api/docs`/`/api/openapi.json`
- **Modify** `src/hassette/web/dependencies.py` — `AuthDep`
- **Modify** `src/hassette/web/routes/ws.py` — pre-`accept()` check
- **Modify** `src/hassette/exceptions.py` — new `HassetteError` subclasses (never `InvalidAuthError`)
- **Modify** `src/hassette/config/models.py` — `WebApiConfig` gains `auth_enabled`, `auth_token`, `trusted_proxies`, `session_ttl`; new CORS wildcard+credentials validator
- **Modify** `src/hassette/core/web_api_service.py` — token resolution in `on_initialize`; both startup guards; `proxy_headers=False` on `uvicorn.Config`; periodic `trusted_proxies` DNS-refresh job via `Scheduler.run_every()`
- **Modify** `src/hassette/cli/client.py` — attach bearer token from file/env; no literal `--token` argument
- **Modify** `frontend/src/api/client.ts` — `credentials: "same-origin"`; add a `postSession()` that bypasses the shared 401 policy
- **Modify** `frontend/src/lib/query-client.ts` — 401 → redirect to login, via `QueryCache.onError`
- **Modify** `frontend/src/hooks/use-websocket.ts` — stop-and-redirect on close code 1008
- **Create** new frontend login view (SPA)
- **Modify** `scripts/docker/ha-demo.yml` — fixed `HASSETTE__WEB_API__AUTH_TOKEN` for the demo stack
- **Modify** `scripts/capture_screenshots.py` — authenticate the telemetry poll and the browser session
- **Modify** `docs/screenshots.yml` — manifest entry for the login view
- **Modify** `src/hassette/test_utils/web_mocks.py` — `create_hassette_stub(auth_enabled=False, ...)`
- **Modify** `tests/integration/web_api/conftest.py`, `tests/e2e/conftest.py`
- **Create** `tests/integration/web_api/test_auth.py`
- **Modify** `hassette.schema.json` (regenerated)

### Behavioral Invariants

- `GET /api/health/live` and `GET /api/health/ready` remain reachable with zero credentials, unconditionally — the Docker healthcheck and the future add-on watchdog both depend on this.
- The default `host` bind stays `0.0.0.0` — existing `docker run -p`/Compose deployments must not lose network reachability after upgrading.
- `Authorization` remains in the CORS `allow_headers` list (`app.py:58`) — no CORS regression for the bearer scheme.
- Existing HA-token masking behavior (`config_view.py:74-98`) is unchanged; the new `auth_token` field reuses it, doesn't modify it.
- The static SPA bundle (`/`, `/assets/*`, `/fonts/*`) stays reachable with no credential — the login view lives there, so gating it would make the entire dashboard unreachable rather than merely protected.
- `mise run demo` and `scripts/capture_screenshots.py` keep working end-to-end. Auth stays *on* in the demo stack (it uses a fixed known token, not `auth_enabled=false`), so the demo and every regenerated doc screenshot reflect the behavior operators actually get — including the new login view, which becomes capturable rather than invisible.
- The Docker healthcheck (`docs/pages/getting-started/docker/snippets/docker-compose.yml:20`) polls `/api/health/live`, an FR#1 exemption, and is unaffected.

### Blast Radius

- `src/hassette/web/` is high-churn (89 commits at time of research, recent work in #1495, #1500, #1464, #1438) — expect rebases during implementation.
- The HA add-on epic (#71) design artifacts become partially stale the moment this ships (see Replacement Targets) — needs a coordinated follow-up, not left to drift silently.
- Every existing hassette deployment sees a behavior change on upgrade (auth turns on by default) — this is the intended fix, but it's a real operational event for every current user, not a transparent no-op upgrade.

## Open Questions

- [x] **Verify the middleware-ordering claim** (auth middleware registered inside `CORSMiddleware` so preflight `OPTIONS` gets a CORS response before an auth rejection) against a running FastAPI app before or during implementation — this is the first custom middleware in the project, with no existing pattern to check it against. **Resolved (T05):** confirmed correct via a passing `OPTIONS` preflight integration test against the real app.
- [x] **Verify `websocket.cookies`/`websocket.headers` availability pre-`accept()`** under this project's specific `ws="websockets-sansio"` uvicorn backend — confirm the pre-accept close(1008) pattern works cleanly (doesn't raise, doesn't silently complete-then-close in a way that changes what the frontend's `onclose` observes) before this becomes the shipped implementation. **Resolved (T07), CONTESTED → accepted:** `websocket.cookies`/`websocket.headers` are populated pre-accept as needed. The close(1008) pattern does *not* work cleanly as literally specified — this backend turns it into an HTTP 403-equivalent handshake rejection, never delivering a WS close frame with code 1008 to the client. The security property (no data flows, `accept()` never called) holds; see the WebSocket auth section above and T12 for the frontend-side consequence (detecting a rejected handshake via "closed before `onopen` fired" instead of `event.code === 1008`).
- [ ] **Verify Docker's loopback-bind-unreachable-from-host behavior empirically** (build the image with `HASSETTE__WEB_API__HOST=127.0.0.1`, run with `-p 8126:8126`, confirm the host cannot reach it while the container healthcheck still passes) — this is the load-bearing fact under "don't change the default bind."
- [ ] **Whether HA add-on store review requires denying all non-`trusted_proxies` peers outright** (vs. merely requiring a token from them) — if add-on review raises this, a `web_api.deny_untrusted_peers: bool = False` field on the same middleware is a small addition; not built speculatively.
