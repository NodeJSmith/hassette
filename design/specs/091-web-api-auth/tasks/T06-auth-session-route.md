---
task_id: "T06"
title: "Add POST /api/auth/session route and AuthDep"
status: "planned"
depends_on: ["T04", "T05"]
implements: ["AC#7"]
---

## Summary

Creates `src/hassette/web/routes/auth.py` with the login exchange endpoint: `POST
/api/auth/session` validates a bearer token in the request body and, on success, mints a session
cookie (T04) and sets it in the response. Adds `AuthDep` to `web/dependencies.py` following the
existing accessor pattern, and registers the new router in `web/app.py`. This is the route T05's
middleware already exempts by path — this task makes that exemption meaningful by giving the path a
working handler.

## Target Files

- create: `src/hassette/web/routes/auth.py` — `POST /api/auth/session`
- modify: `src/hassette/web/dependencies.py` — add `AuthDep`
- modify: `src/hassette/web/app.py` — `app.include_router(auth_router, prefix="/api")`
- modify: `tests/integration/web_api/test_auth.py` — tighten T05's placeholder assertion, add login-route tests
- read: `src/hassette/web/routes/health.py` — full file, router pattern to follow
- read: `src/hassette/web/routes/scheduler.py` — full file, router pattern for a more complex handler
- read: `src/hassette/web/dependencies.py:46-71` — accessor + `Annotated[X, Depends(...)]` pattern

## Prompt

Read design.md's `## Architecture → Middleware and routing` (the exemption rationale) and `##
Convention Examples → Dependency injection accessor pattern` and `→ Router pattern`, plus the Edge
Case "`POST /api/auth/session` with a correct token but no existing cookie."

In `src/hassette/web/dependencies.py`, add `AuthDep` to the existing "Shared dependency type aliases"
block (currently lines 67-71, following `HassetteDep`, `RuntimeDep`, `TelemetryDep`, `SchedulerDep`,
`ApiDep`): a plain accessor function `get_resolved_auth_token(request: Request) -> str` that returns
`request.app.state.auth_token` (a sibling attribute to the existing `request.app.state.hassette` —
see Focus below for why it lives there rather than through `hassette`), plus
`AuthDep = Annotated[str, Depends(get_resolved_auth_token)]`. Route handlers pass this resolved token
string directly into T04's bearer-check and cookie-mint functions.

In the new `src/hassette/web/routes/auth.py`, following `web/routes/health.py`'s shape
(`APIRouter(tags=["auth"])`, `response_model=` on the route): implement `POST /api/auth/session`
accepting a token in the request body (not a header — this route's entire job is validating a
credential presented in the body, since it's the one endpoint that must be reachable with zero prior
credential per FR#1's exemption). On a correct token (checked via T04's bearer-check function),
mint a session cookie (T04) and set it on the response as `HttpOnly`/`SameSite=Strict`, with `Secure`
set per T04's Secure-flag decision function (reading the request's raw peer + `X-Forwarded-Proto`).
On an incorrect token, return 401 — this route performs its own body-based validation and is exempt
from the middleware's default-deny, so it must reject bad credentials itself.

Register the router in `web/app.py`: `app.include_router(auth_router, prefix="/api")`, alongside the
existing 9 routers (health, apps, logs, executions, bus, config, ws, telemetry, scheduler).

In `tests/integration/web_api/test_auth.py` (created by T05), tighten the placeholder assertion for
`POST /api/auth/session` from "not 401" to "reachable with zero credentials and returns a real
response" (a request with a correct token body should now return 2xx and set a cookie; the bare
"reachability" check for AC#7 no longer needs to tolerate a 404). Add a test for the correct-token →
cookie-set case and the incorrect-token → 401 case — both need the app built with a known token value
(`create_fastapi_app(mock_hassette, auth_token="test-token-value")`, the `auth_token` parameter T05
adds to `web/app.py`) rather than the shared `app` fixture's default `None`, so there's a concrete
value to assert "correct" against.

## Focus

- This route is exempt from T05's middleware by path, but must do its own credential validation in
  the handler body — it is not "no auth at all," it's "auth validated inline instead of by the
  middleware."
- `AuthDep`'s accessor function follows the exact same one-line-body shape as `get_hassette`/
  `get_runtime` (`web/dependencies.py:46-53`) — do not add extra logic in the accessor itself; any
  validation logic belongs in `web/auth.py` (T02/T04), not in the dependency accessor.
- `AuthDep` reads `request.app.state.auth_token`, **not** `request.app.state.hassette.<something>`.
  There is no public accessor for `WebApiService` on `Hassette`/`Core` today — only a private
  `_web_api_service` attribute (`core/core.py:130,223`) — so this repo threads the resolved token
  through `create_fastapi_app(hassette, auth_token=...)` instead (T05 adds this parameter to
  `web/app.py`, which sets `app.state.auth_token` as a sibling to the existing `app.state.hassette`).
  T08 is the caller that passes the real resolved value in production
  (`create_fastapi_app(self.hassette, auth_token=self._resolved_auth_token)` inside `serve()`); test
  fixtures pass a known test token the same way.
- `web/routes/scheduler.py` is the reference for a router with more than a trivial handler body
  (`db_degrades_to(response)` context manager for DB-backed handlers) — this route has no DB
  dependency, so that pattern doesn't apply here, but the file confirms the general
  `APIRouter(...)` + `response_model=` + `HTTPException` shape to follow.

## Verify

- [ ] AC#7: Integration test confirms `GET /api/health/live`, `GET /api/health/ready` are reachable with zero credentials, and `POST /api/auth/session` with a correct token in the body (no prior credential) returns a successful response with a session cookie set.
