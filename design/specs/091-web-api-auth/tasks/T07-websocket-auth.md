---
task_id: "T07"
title: "Add pre-accept auth check to the WebSocket handler"
status: "planned"
depends_on: ["T05"]
implements: ["FR#11", "AC#1"]
---

## Summary

Changes the WebSocket handler in `web/routes/ws.py` to check authorization (via T05's
`authorize_ws()`) before calling `accept()`, closing with code `1008` (policy violation) on failure
instead of accepting the connection first. This is the WebSocket half of the default-deny gate — the
REST half was T05/T06. This task also empirically confirms (Open Question resolved during
`/mine-plan`) that `websocket.cookies`/`websocket.headers` are populated at this pre-accept point
under this project's specific `ws="websockets-sansio"` uvicorn backend, since no existing test in
this repo exercises the pre-accept path today.

## Target Files

- modify: `src/hassette/web/routes/ws.py` — pre-`accept()` check
- modify: `tests/integration/web_api/test_ws_endpoint.py` — extended with auth coverage
- read: `src/hassette/web/auth.py` — `authorize_ws()` (added by T05)
- read: `src/hassette/core/web_api_service.py:71` — confirms `ws="websockets-sansio"` uvicorn backend choice

## Prompt

Read design.md's `## Architecture → WebSocket auth` section in full, including the code excerpt, and
FR#11, plus the Open Questions entry about `websocket.cookies`/`websocket.headers` pre-accept
availability (resolved during `/mine-plan`: fold verification into this task via its integration
test against the real backend, rather than a separate spike).

In `src/hassette/web/routes/ws.py`, the handler currently calls `websocket.accept()` unconditionally
as its first line (confirmed at lines 85-87: `@router.websocket("/ws")` at 85, `async def
websocket_endpoint(websocket: WebSocket) -> None:` at 86, `await websocket.accept()` at 87). Change
this to:

```python
if not authorize_ws(websocket):
    await websocket.close(code=1008)
    return
await websocket.accept()
```

(adapt the exact call signature to whatever `authorize_ws()` actually takes, per T05's
implementation — the design's own code excerpt is illustrative, not a literal signature). Read the
resolved token the same way the existing `runtime` accessor at `ws.py:88` does —
`websocket.app.state.auth_token` (the sibling attribute to `websocket.app.state.hassette`, set by
`create_fastapi_app()`'s `auth_token` parameter per T05/T08 — **not** `hassette.config.web_api`,
which only ever holds the raw configured value and may be `None`). Non-browser clients (CLI, scripts)
attach `Authorization: Bearer <token>` via the `websockets` library's `additional_headers` parameter
at connect time — `authorize_ws()` (T05) must check `websocket.headers` for this, in addition to
`websocket.cookies` for browser clients.

Extend `tests/integration/web_api/test_ws_endpoint.py` (existing file) with: an unauthenticated
connection attempt is rejected with close code `1008` before any application data flows, verified
against the real test client/backend (not a mock of the WebSocket protocol) — this is what confirms
the pre-accept close(1008) pattern behaves cleanly under `ws="websockets-sansio"` (doesn't raise,
doesn't silently complete-then-close in a way that changes what a real client's `onclose` would
observe); a connection with a valid cookie is accepted; a connection with a valid
`Authorization: Bearer <token>` header (via `additional_headers`, using the `websockets` library
directly rather than any existing test helper — the codebase currently has no precedent for a
non-browser WS auth test, per design.md's Test Strategy) is accepted. The positive-auth cases need a
known token value threaded into the test app the same way T06/T11 do —
`create_fastapi_app(mock_hassette, auth_token="test-token-value")` (the `auth_token` parameter T05
adds to `web/app.py`) — rather than relying on this file's existing app-construction fixture's
default.

## Focus

- The pre-accept close-with-1008 pattern is new to this codebase and explicitly flagged as unverified
  in the design — do not assume it works as described without the integration test actually passing
  against the real backend. If `websocket.cookies`/`websocket.headers` are *not* populated
  pre-accept under `ws="websockets-sansio"`, this is a genuine finding: report it rather than forcing
  a workaround silently, since it may mean the design's WS auth approach needs revision.
- `authorize_ws()` (T05) is the single source of truth for WS authorization — do not duplicate the
  trusted-peer/bearer/cookie composition logic here.
- Frontend reconnect behavior on receiving close code 1008 is T12's job (frontend), not this task's —
  this task only implements and tests the server-side close behavior.

## Verify

- [ ] FR#11: Integration test confirms an unauthenticated WebSocket connection attempt receives close code `1008` and `accept()` is never called (verified by confirming no data can be sent/received on the connection before the close).
- [ ] AC#1: Integration test (WS portion) confirms the WS upgrade with no credential results in close code `1008`, extending `tests/integration/web_api/test_ws_endpoint.py`.
