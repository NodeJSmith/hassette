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
indefinitely against a connection a fresh cookie won't fix. `App()` in `app.tsx` is changed to
render `/login` as a standalone tree, bypassing its normal always-mounted shell (`WebSocketEffect`,
`TelemetryHealthEffect`, `Sidebar`, `StatusBar`) entirely — without this, an unauthenticated visit to
`/login` would immediately trigger the very 401s/1008-close this task is built to handle, before the
operator has a credential. This task has no runtime dependency on the backend tasks (T01-T11) — it's
pure frontend code, independently developable and testable via mocked fetch/WebSocket.

## Target Files

- modify: `frontend/src/api/client.ts` — `credentials: "same-origin"`; add `postSession()`
- modify: `frontend/src/lib/query-client.ts` — 401 → redirect to login, via `QueryCache.onError`
- create: `frontend/src/pages/login.tsx` — new login view
- create: `frontend/src/pages/login.test.tsx` — component test
- modify: `frontend/src/app.tsx` — branch `App()`'s return to bypass the shell for `/login`
- modify: `frontend/src/app.test.tsx` — test confirming `/login` does not mount the shell
- modify: `frontend/src/hooks/use-websocket.ts` — stop-and-redirect on close code 1008
- modify: `frontend/src/hooks/use-websocket.test.tsx` (or equivalent existing test file, if present) — new test for the 1008 branch
- read: `frontend/src/pages/not-found.tsx` — closest existing precedent for a simple standalone page + route wiring
- read: `frontend/src/app.tsx:69-296` — `App()` in full: hooks (lines 69-158), the always-mounted shell (`WebSocketEffect`, `TelemetryHealthEffect`, `Sidebar`, `StatusBar`) wrapping the routed `Switch` (lines 241-289)

## Prompt

Read design.md's `## User Scenarios → Operator: No forward-auth gateway` (steps 2-3, the login flow
from the operator's perspective) and FR#12, and the Architecture section's WebSocket auth paragraph
covering `use-websocket.ts`.

In `frontend/src/api/client.ts` (`apiFetch<T>`, currently lines 16-39, with no `credentials` option
set today), add `credentials: "same-origin"` to the `fetch(...)` call (lines 18-24) so the session
cookie is sent automatically on every request. Leave `apiFetch`'s error behavior alone — it keeps
throwing `ApiError` for every non-ok response exactly as it does today.

**Put the 401 → login redirect in `frontend/src/lib/query-client.ts`, not in `apiFetch`.** The app
already builds its client through `createQueryClient()` (line 12, called from `app.tsx:71`), so a
`QueryCache`-level `onError` that checks for `ApiError` with `status === 401` and navigates to
`/login` is both the idiomatic TanStack Query location for cross-cutting error policy and the one a
reader will look in. A fetch helper that navigates is a reader-load trap: "what can send me to
/login?" stops being answerable from any call site.

Also add a `postSession(token: string)` to `client.ts` that calls `fetch` directly, sending
`{"token": token}` as the JSON body — this is the pinned wire contract from design.md's Middleware
and routing section (`SessionRequest.token` on the backend, T06) — and returns a result the caller
can branch on (success vs. rejected), rather than routing through `apiFetch`. This
is what the login form submits with. Without it, a wrong token 401s, trips whatever global 401
handling exists, and bounces the operator back to the login page with no error shown — the form
appears to do nothing when given a bad token, which is the single most likely thing a first-time
operator will do. Do **not** solve this by adding a `skipAuthRedirect` flag to `apiFetch`; that adds
a branch to a shared function for exactly one caller.

Create `frontend/src/pages/login.tsx` following the existing page co-location convention (a
`.tsx` + matching `.test.tsx`, per `frontend/src/pages/not-found.tsx` and its siblings): a minimal
form where the operator pastes the token from the startup log/`docker logs` output, submits it via
`postSession()`, renders an inline error on rejection, and on success redirects to the main
dashboard.

**Do not wire `/login` as a sibling `<Route>` inside the existing `<Switch>` (lines 241-289).** That
`Switch` sits inside `App()`'s always-mounted shell (`frontend/src/app.tsx` uses `wouter`, not
preact-router — correcting an earlier miscue) — `<WebSocketEffect />` and `<TelemetryHealthEffect />`
render unconditionally at the top of the returned JSX (around line 163), and `<Sidebar>`/`<StatusBar>`
render around the `Switch` regardless of route. A `/login` route registered the normal way would still
mount all of that: `WebSocketEffect` opens a connection the middleware immediately 1008-closes (which
this same task's own reconnect logic then redirects back to `/login`, looping), `TelemetryHealthEffect`
polls and gets 401s, and `Sidebar`/`StatusBar` fetch data that also 401s — all before the operator has
a credential.

Instead, branch `App()`'s **return statement** (not its hooks — `useLocation()` already runs
unconditionally at line 74 and gives you `location`; hooks must still all execute on every render,
only the returned JSX branches): if `location === "/login"`, return a minimal tree containing only
`<QueryClientProvider client={queryClient}>`, the existing `<Toaster .../>` (for consistent
notification styling), and `<LoginPage />` — skipping `WebSocketEffect`, `TelemetryHealthEffect`,
`Sidebar`, `StatusBar`, the drawer, and the `Switch` entirely. Otherwise, fall through to the existing
return unchanged. Place this branch after all the existing hook calls (which end just before the
current `return (` around line 160) and before that `return`.

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
  for "a standalone page with its own route." Unlike `not-found.tsx`, though, `/login` must bypass
  `App()`'s shell entirely (see Prompt) — it is not just another sibling route, since every other
  route in the `Switch` intentionally shares the authenticated shell.
- This is the one place in this task where getting the mounting wrong produces no immediate test
  failure but a real runtime bug: a login page mounted inside the normal shell would 401/1008-loop on
  first unauthenticated visit, and neither `login.test.tsx` (renders the page standalone) nor T13's
  e2e test (injects a valid cookie before ever visiting the dashboard) would catch it.
- This task is independently developable from the backend — write it against mocked
  `fetch`/`WebSocket` in tests, not a live backend. T13 (e2e) is where the frontend and full backend
  are proven to work together against a real running stack.
- Per `.claude/rules/design-completeness.md`, this PR must carry visual evidence for the new login
  view (a Screenshots section in the PR body, or the `no-visual-change` label if genuinely not
  applicable) — flag this for the PR-creation step, not something to resolve in this task file
  itself.

## Verify

- [ ] FR#12: Component/unit test confirms `use-websocket.ts`'s `onclose` handler, on receiving `event.code === 1008`, does not call `scheduleReconnect()` and instead redirects to the login route; confirms other close codes still trigger the existing reconnect behavior unchanged. Additionally, a test in `app.test.tsx` confirms rendering `App()` at the `/login` route does **not** mount `WebSocketEffect`, `TelemetryHealthEffect`, `Sidebar`, or `StatusBar` — the specific mechanism that keeps the 1008-redirect from looping back onto itself.
- [ ] AC#13: Frontend component test confirms the WS client stops reconnecting and navigates to the login view on close code 1008, rather than retrying indefinitely.
- [ ] `login.test.tsx` confirms that submitting a wrong token renders a visible error and leaves the operator on the login view — it does not silently redirect or appear to do nothing. Neither T13's e2e test (which injects a valid cookie and never submits a bad one) nor any backend test covers this path.
- [ ] The 401 redirect lives in `query-client.ts`'s `QueryCache.onError`, not inside `apiFetch` — verified by inspection, plus a test confirming `apiFetch` still throws `ApiError` on a 401 rather than navigating.
