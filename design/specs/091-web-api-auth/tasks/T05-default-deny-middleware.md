---
task_id: "T05"
title: "Add default-deny ASGI middleware and authorize_ws() helper"
status: "planned"
depends_on: ["T03", "T04"]
implements: ["FR#1", "AC#1"]
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

In `src/hassette/web/middleware.py`, implement a single ASGI middleware (Starlette
`BaseHTTPMiddleware` or a raw ASGI middleware class — follow whichever this project's FastAPI version
makes more idiomatic; check for any existing middleware pattern in the codebase first, though the
design notes this is "the first custom middleware in the project") that, for every request:

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
