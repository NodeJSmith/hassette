---
task_id: "T13"
title: "Add e2e test covering login, cookie, authenticated REST and WS"
status: "planned"
depends_on: ["T06", "T07", "T08", "T11", "T12"]
implements: ["FR#7"]
---

## Summary

Adds one new Playwright e2e test proving the whole assembled system works against a real running
stack: cookie injected directly via `context.add_cookies` (not by driving the login form UI, per
design.md's Test Strategy — the login form itself isn't covered here, this is about the
cookie-authenticated session working end-to-end), followed by an authenticated REST call and an
authenticated WebSocket connection. This is the highest-altitude test in the whole feature — it's the
one that would catch a regression no unit or integration test could (e.g., a cookie that verifies
correctly in isolation but the browser never actually sends due to a `SameSite`/`Secure` mismatch
against the real serving origin).

## Target Files

- create: `tests/e2e/test_auth_flow.py` (or add to an existing relevant e2e test file, if a more
  appropriate one exists — check `tests/e2e/` for a file already covering dashboard-load or
  WS-connection e2e tests)
- read: `tests/e2e/conftest.py:113-120` — `create_hassette_stub(...)` call for e2e mocks
- read: `tests/e2e/conftest.py:403-441` — the fixture-selection comment block and `live_server_ws`,
  the **WebSocket-capable** server fixture (`ws="websockets-sansio"`). This is the one this test
  needs; no new fixture is required for cookie injection, since `context.add_cookies` is a native
  Playwright API.

## Prompt

Read design.md's `## Test Strategy → New Test Coverage`'s e2e bullet in full, and the note explaining
why the login form itself isn't driven here (Playwright's limited ability to simulate a
server-initiated close mid-test makes the reconnect-on-1008 behavior better covered at the
unit/component level, which T12 already did).

Add a new Playwright e2e test that: mints a valid session cookie directly (via the same mechanism
T04/T11 use, or by calling `POST /api/auth/session` once with a known test token before the browser
test starts) and injects it into the browser context via `context.add_cookies([...])`; navigates to
the dashboard and confirms it loads (proving the cookie authenticates the initial REST calls); and
confirms the WebSocket connects successfully (proving `authorize_ws()`, T05/T07, accepts the same
cookie pre-`accept()`).

**Use `live_server_ws`, not `live_server`.** The default `live_server` fixture
(`tests/e2e/conftest.py:335-341`) starts uvicorn with `ws="none"` to dodge a `websockets.legacy`
`DeprecationWarning` that `filterwarnings=["error"]` would turn into a failure — WebSocket upgrades
are simply not served there, so the WS half of this test cannot pass against it. `live_server_ws`
(around lines 409-441) is the function-scoped fixture that runs `ws="websockets-sansio"`, which is
both the backend production uses (`core/web_api_service.py:71`) and the one T07's pre-`accept()`
close(1008) behavior was verified against. The comment block at lines 403-411 documents this split;
read it before wiring fixtures.

**Also, a citation in the design doc is inaccurate**: design.md's Existing Tests to Adapt section
references a `browser_context_args` fixture in `tests/e2e/conftest.py:298-359` for cookie injection.
That fixture does not exist (confirmed during Phase 2 exploration) — use `context.add_cookies([...])`
directly; no new fixture needs to be added for this.

## Focus

- This test needs the full stack: T06 (login route to mint a real cookie against), T07 (WS pre-accept
  auth), T08 (WebApiService actually starting with auth wired), T11 (proves the pieces compose
  correctly at the integration level before this even more expensive e2e test runs), and T12 (the
  frontend must send the cookie and connect the WS correctly).
- Do not drive the login form UI in this test — inject the cookie directly, per the design's own
  rationale (this keeps the e2e suite fast and avoids the flakier form-interaction path for a
  property that's already covered by T12's component test).
- Check `tests/e2e/` for an existing file already covering dashboard-load or WS-connection scenarios
  before creating a new file — if one exists, this test may fit there better than as a standalone
  file, following whatever the repo's existing e2e file-organization convention is.

## Verify

- [ ] FR#7: Playwright e2e test, running against `live_server_ws` (not `live_server`, which serves no WebSockets), confirms a cookie injected via `context.add_cookies` authenticates both a REST dashboard load and a WebSocket connection against the real running stack, without driving the login form.
