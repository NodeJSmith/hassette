---
task_id: "T05"
title: "Add default-deny ASGI middleware and authorize_ws() helper"
status: "planned"
depends_on: ["T03", "T04"]
implements: ["FR#1", "FR#17", "FR#22", "FR#23", "AC#1", "AC#17", "AC#20", "AC#21", "AC#22"]
---

## Summary

Creates `src/hassette/web/middleware.py`: a single ASGI middleware that composes T03's trusted-peer
check and T04's bearer/cookie check into one default-deny gate applied to every route, with three
explicit exemptions. Registers the middleware in `web/app.py` inside `CORSMiddleware`, and removes
the current implicit exemption of `/api/docs`/`/api/openapi.json` (they now fall under default-deny
like everything else). Also adds `authorize_ws()` to `web/auth.py`, the same validator logic exposed
in a form the WebSocket handler (T07) can call pre-`accept()`.

## Target Files

- create: `src/hassette/web/middleware.py` — default-deny ASGI middleware
- modify: `src/hassette/web/auth.py` — add `authorize_ws()`
- modify: `src/hassette/web/app.py` — register middleware inside `CORSMiddleware`; stop exempting `/api/docs`/`/api/openapi.json`; add `auth_token` parameter to `create_fastapi_app()`
- create: `tests/integration/web_api/test_auth.py` — initial default-deny + exemption tests (extended further by T11)
- read: `src/hassette/web/app.py:46-59` — current `FastAPI(docs_url=..., openapi_url=...)` call and `CORSMiddleware` registration
- read: `src/hassette/web/routes/health.py` — full file, exempted route pattern

## Prompt

Read design.md's `## Architecture → Middleware and routing` in full, and FR#1, FR#4 (context only —
FR#4's `proxy_headers=False` change is T08's job, not this task's), plus the Edge Cases entries for
health endpoints and `/api/docs`/`/api/openapi.json`.

In `src/hassette/web/middleware.py`, implement a Starlette `BaseHTTPMiddleware` subclass. Use
`BaseHTTPMiddleware` specifically, not a raw ASGI middleware class: two of this middleware's jobs are
response-side — sliding renewal (FR#22) sets a `Set-Cookie` header on the way out, and the coalesced
failed-auth counter (FR#17) reads the outgoing status — and a raw implementation would have to
intercept the `send` callable for both. `BaseHTTPMiddleware` also only receives `http`-scope
requests, which is what this design wants: the WebSocket handshake bypasses it entirely and is gated
separately by `authorize_ws()` below.

**Scope the gate to the `/api/` path prefix (FR#23).** A request whose path does not start with
`/api/` passes through untouched — no trusted-peer check, no credential check, no counting. This is
not an optimization; it is what makes the feature usable. `web/app.py:73-94` serves the entire SPA
from this same app (the `/assets` and `/fonts` `StaticFiles` mounts plus the
`@app.get("/{path:path}")` catch-all returning `index.html`), and the login view T12 builds is part
of that bundle. Gating it would 401 the HTML document and every JS/CSS asset for a browser that has
no cookie yet — the operator would have nowhere to paste the token they just read out of
`docker logs`. The bundle exposes client code and route names only, never operator data.

For every request under `/api/`:

0. If `hassette.config.web_api.auth_enabled` is `False`, let the request through unconditionally —
   no trusted-peer check, no bearer/cookie check, no exemption logic. **This is the mechanism that
   makes `create_hassette_stub(auth_enabled=False)` (T01) and `make_web_system_config`'s
   `auth_enabled=False` override (T01) actually keep the existing ~211 integration, ~165 e2e, and
   system tests passing unchanged** — design.md itself never states this bypass explicitly (it's
   assumed throughout the Test Strategy and FR#13's framing of `auth_enabled` as a real, meaningful
   toggle), so this step exists precisely to close that gap. Steps 1-3 below only run when
   `auth_enabled` is `True` (the default).
1. Checks the raw `scope["client"]` against T03's trusted-peer matcher. If trusted, let the request
   through with no further check.
2. Otherwise, checks for a valid bearer token (T04) or valid session cookie (T04) — both checked
   against the resolved token at `request.app.state.auth_token` (see below for where that's set). If
   either is valid, let the request through.
3. Otherwise, reject with 401 — **except** for exactly three paths, which bypass steps 1-3 entirely:
   `GET /api/health/live`, `GET /api/health/ready`, `POST /api/auth/session`. `/api/docs` and
   `/api/openapi.json` are explicitly **not** in this exemption list.

Then, on the response returned by `call_next`, two things happen regardless of which branch above
let the request through:

4. **Sliding renewal (FR#22).** If the request authenticated via a session cookie and T04's renewal
   predicate says that cookie is past its half-life, mint a replacement (T04) and set it on the
   response with the same `HttpOnly`/`SameSite=Strict`/`Secure` attributes T06's login route uses —
   reuse T04's Secure-flag decision function, don't re-derive the flag. Requests authenticated by
   bearer token or trusted-proxy match never mint a cookie; neither does a request whose cookie is
   still fresh. This is what keeps `session_ttl` short without making the operator re-paste the token
   on a timer: the TTL bounds the life of a cookie *value*, not the life of a session.
5. **Failed-auth counting (FR#17).** If the response status is 401, increment a per-source counter
   and emit the coalesced WARN when a source crosses the threshold. Key off the **outgoing status**,
   not off whether step 3 was the thing that rejected — an exempt route still traverses this
   middleware, so `POST /api/auth/session`'s own handler-issued 401 (T06) gets counted by this same
   rule with no shared tracker object between the two modules. Without this, the one endpoint whose
   entire job is validating a credential would be the only unmonitored surface in the design. Auth is
   the only source of 401 in this application, so there is nothing else to miscount. The counter
   never rejects or throttles anything — rate limiting is an explicit Non-Goal — and it must evict
   old entries so a sustained burst can't grow it without bound. Pick concrete threshold/window
   values consistent with design.md's example ("12 failed auth attempts from 203.0.113.4 in the last
   5 minutes"), e.g. 10 attempts / 5 minutes, and document the choice; there is no existing
   coalescing-log utility in this codebase to reuse (`bus/rate_limiter.py` is handler-call
   debounce/throttle via task cancellation, not log suppression). The 10/5-minute figure here is a
   deliberate, rounder choice, not a copy of design.md's illustrative "12" — design.md phrases its
   number as an "e.g." rather than a pinned requirement, so any concrete threshold in that ballpark
   satisfies FR#17.

In `src/hassette/web/app.py`, add a parameter `auth_token: str | None = None` to
`create_fastapi_app(hassette: "Hassette", auth_token: str | None = None) -> FastAPI` (currently line
45), and set `app.state.auth_token = auth_token` right after the existing `app.state.hassette =
hassette` (line 51) — a sibling attribute, populated the same way. This is the single place both
production code (T08's `WebApiService.serve()`, which threads in the real resolved token) and every
test fixture (which can pass a known test token, or omit it to get `None` for tests that only need
the no-credential-401 path) reach the resolved token from. There is no public accessor for
`WebApiService` on `Hassette`/`Core` today (only a private `_web_api_service` attribute,
`core/core.py:130,223`), so threading the value in as a parameter here — rather than reaching for it
through `hassette` at request time — is the design's actual mechanism, not an implementation detail
left to guesswork.

Register the middleware **inside** `CORSMiddleware` — i.e., add it to
the middleware stack after `CORSMiddleware` is added (Starlette applies middleware in
reverse-registration order, so CORS must be the outermost layer for a preflight `OPTIONS` request to
get a proper CORS response before this middleware would otherwise reject it with an opaque error).
This exact ordering claim is unverified in the design (Open Question, resolved during `/mine-plan` to
be folded into this task) — write an integration test in the new
`tests/integration/web_api/test_auth.py` that sends an `OPTIONS` preflight request to a protected
route with no credential and confirms it receives a proper CORS response (not an opaque 401 with no
CORS headers), proving the ordering is correct as implemented. If the test fails, adjust the
registration order until it passes — do not just assert the current behavior if it's wrong.

Also add `authorize_ws()` to `src/hassette/web/auth.py` — the same trusted-peer/bearer/cookie
composition as steps 1-2 above (including the same step-0 `auth_enabled` bypass — if `False`, return
authorized unconditionally, for the same reason: existing WS tests built via
`create_hassette_stub(auth_enabled=False)` must keep passing unchanged), but as a plain function
taking a `WebSocket` (reads `websocket.cookies` and `websocket.headers`) rather than an HTTP
`Request`, for T07 to call. Building this here (not duplicating the composition logic in T07) keeps
the "same validator used by the HTTP middleware" property FR#11/design.md's WebSocket auth section
requires.

Write the initial `tests/integration/web_api/test_auth.py` covering FR#1 and AC#1's REST portion: a
representative mutation endpoint (e.g. `POST /api/apps/{app_key}/start`), a source-disclosure
endpoint (`GET /api/apps/{app_key}/source`), and `GET /api/config`, each with no credential, all
return 401 (AC#1 names these three categories explicitly — test each, not just one representative
route). Each of the three exempted paths is *not* rejected by the middleware with no credential
(using `create_hassette_stub(auth_enabled=True)` from T01). Note `POST /api/auth/session` doesn't
exist as a route until T06 — assert its response is not 401 (it will be 404 until T06 lands, which
still proves the middleware let it pass through to the router rather than blocking it); T06 tightens
this assertion to 2xx once the route exists. **Also add a test confirming step 0's bypass**: the same
mutation endpoint with no credential returns 200-range (not 401) when built with
`create_hassette_stub(auth_enabled=False)` (the default) — this is the specific test that proves the
existing ~211 integration test suite (which all uses that default) keeps passing unchanged. T11
extends this same file later with bearer/cookie/trusted-proxy/CORS coverage — do not duplicate what
T11 will add; this task's tests cover only the generic deny/exempt/bypass behavior across the
specific endpoint categories AC#1 names.

## Focus

- This is the first custom middleware in the project (per design.md's own Open Questions) — there is
  no existing pattern to copy. Read Starlette/FastAPI's middleware documentation via context7 if the
  exact registration API (`app.add_middleware(...)` ordering semantics) is unclear before guessing.
- The `/api/` prefix scope is the single highest-consequence line in this task. If it is wrong in the
  restrictive direction, the dashboard does not load at all and the feature is unusable; the AC#21
  test exists specifically to catch that. Do not "tighten" it later to cover static assets.
- `app.state.auth_token` is legitimately `None` in several test configurations while
  `auth_enabled=True` — T04's checks are specified to treat `None` as never-authenticating. Don't add
  a second `None` guard here; rely on T04's, and if you see a `TypeError` from `compare_digest`, the
  bug is in T04's implementation, not a missing check in this file.
- The `/api/docs`/`/api/openapi.json` un-exemption is a deliberate behavior change (closes an
  unauthenticated API-schema fingerprinting surface) — do not add them to the exemption list even
  though `web/app.py:48-49` currently wires them as always-on FastAPI features.
- `authorize_ws()` must reuse T03's and T04's functions directly, not reimplement the composition —
  T07 depends on this exact function existing with this exact name/shape.
- `create_hassette_stub(auth_enabled=True)` (T01) is required to exercise the denied path in tests —
  the default `False` would make every request pass trivially.

## Verify

- [ ] FR#1: Integration test confirms `GET /api/apps` (a representative non-exempt route) with no credential returns 401 when `auth_enabled=True`, and each of `GET /api/health/live`, `GET /api/health/ready`, `POST /api/auth/session` returns a non-401 response with no credential; a request to `GET /api/docs` with no credential returns 401 (confirming it is no longer exempt); the same non-exempt route with no credential returns a non-401 response when `auth_enabled=False` (step 0's bypass).
- [ ] AC#1 (REST portion): Integration test confirms a mutation endpoint (`POST /api/apps/{app_key}/start`), `GET /api/apps/{app_key}/source`, and `GET /api/config`, each with no credential, all return 401. (The WS-upgrade portion of AC#1 is verified separately in T07.)
- [ ] FR#23 / AC#21: Integration test confirms `GET /` and a representative path under `/assets` return their content with no credential while `auth_enabled=True`, and that `GET /api/config` with no credential still returns 401 — the test that catches a middleware which has accidentally gated the login view's own assets.
- [ ] FR#22 / AC#20: Integration test confirms a request carrying a cookie past its half-life comes back with a `Set-Cookie` header whose new value verifies successfully; a request carrying a fresh cookie returns no `Set-Cookie`; and requests authenticated by bearer token or trusted-proxy match return no `Set-Cookie`.
- [ ] FR#17 / AC#17: Integration test confirms a burst of failed-auth requests from one source within the window produces exactly one coalesced WARN log line, not one per attempt, visible via `GET /api/logs/recent`.
- [ ] AC#22: The same test confirms a burst of wrong-token `POST /api/auth/session` requests produces that same coalesced WARN — proving the counter keys off the outgoing 401 rather than off the middleware's own reject branch, which is the whole reason the login endpoint is covered at all.
