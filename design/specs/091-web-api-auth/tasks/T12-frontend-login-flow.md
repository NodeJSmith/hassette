---
task_id: "T12"
title: "Add frontend login view, credentialed fetch, and WS stop-on-1008"
status: "planned"
depends_on: []
implements: ["FR#12", "AC#13"]
---

## Summary

Adds the browser-side half of the login flow: `frontend/src/api/client.ts` sends cookies with every
request and redirects to a new login view on 401; a new `frontend/src/pages/login.tsx` lets the
operator paste the token from the startup log and exchanges it for a session cookie via `POST
/api/auth/session`; `frontend/src/hooks/use-websocket.ts` stops its reconnect backoff loop and
redirects to the login view when the WebSocket closes with code `1008`, instead of retrying
indefinitely against a connection a fresh cookie won't fix. This task has no runtime dependency on
the backend tasks (T01-T11) — it's pure frontend code, independently developable and testable via
mocked fetch/WebSocket.

## Target Files

- modify: `frontend/src/api/client.ts` — `credentials: "same-origin"`, 401 → redirect to login
- create: `frontend/src/pages/login.tsx` — new login view
- create: `frontend/src/pages/login.test.tsx` — component test
- modify: `frontend/src/app.tsx` — route wiring for the new login page
- modify: `frontend/src/hooks/use-websocket.ts` — stop-and-redirect on close code 1008
- modify: `frontend/src/hooks/use-websocket.test.tsx` (or equivalent existing test file, if present) — new test for the 1008 branch
- read: `frontend/src/pages/not-found.tsx` — closest existing precedent for a simple standalone page + route wiring
- read: `frontend/src/app.tsx:242-288` — `preact-router`-style `<Route>` registration, catch-all pattern

## Prompt

Read design.md's `## User Scenarios → Operator: No forward-auth gateway` (steps 2-3, the login flow
from the operator's perspective) and FR#12, and the Architecture section's WebSocket auth paragraph
covering `use-websocket.ts`.

In `frontend/src/api/client.ts` (`apiFetch<T>`, currently lines 16-39, with no `credentials` option
set today), add `credentials: "same-origin"` to the `fetch(...)` call (lines 18-24) so the session
cookie is sent automatically on every request. Add 401 handling: on a 401 response, redirect to the
new login route rather than letting `ApiError` propagate generically as it does for every other
non-ok response today.

Create `frontend/src/pages/login.tsx` following the existing page co-location convention (a
`.tsx` + matching `.test.tsx`, per `frontend/src/pages/not-found.tsx` and its siblings): a minimal
form where the operator pastes the token from the startup log/`docker logs` output, submits it to
`POST /api/auth/session`, and on success is redirected to the main dashboard. Wire the new route into
`frontend/src/app.tsx`'s route list (currently lines 242-288, `preact-router`-style `<Route path="..."
component={...} />`), following the same registration shape as the existing pages.

In `frontend/src/hooks/use-websocket.ts`, the `onclose` handler (currently lines 148-158) takes no
`event` parameter and unconditionally calls `scheduleReconnect()` (defined at lines 165-169, called
from `onclose` at line 157) on every close. Change this to accept the close `event`, check
`event.code === 1008`, and on that condition: stop the backoff loop (do not call
`scheduleReconnect()`) and redirect to the new login route instead — retrying against a connection
that a fresh cookie won't fix wastes the backoff cycle and never recovers on its own. For any other
close code, keep the existing reconnect behavior unchanged.

## Focus

- No login/auth page exists anywhere in `frontend/src/` today (confirmed during Phase 2 exploration)
  — there is no existing pattern to extend, only `not-found.tsx` as the closest structural precedent
  for "a standalone page with its own route."
- This task is independently developable from the backend — write it against mocked
  `fetch`/`WebSocket` in tests, not a live backend. T13 (e2e) is where the frontend and full backend
  are proven to work together against a real running stack.
- Per `.claude/rules/design-completeness.md`, this PR must carry visual evidence for the new login
  view (a Screenshots section in the PR body, or the `no-visual-change` label if genuinely not
  applicable) — flag this for the PR-creation step, not something to resolve in this task file
  itself.

## Verify

- [ ] FR#12: Component/unit test confirms `use-websocket.ts`'s `onclose` handler, on receiving `event.code === 1008`, does not call `scheduleReconnect()` and instead redirects to the login route; confirms other close codes still trigger the existing reconnect behavior unchanged.
- [ ] AC#13: Frontend component test confirms the WS client stops reconnecting and navigates to the login view on close code 1008, rather than retrying indefinitely.
