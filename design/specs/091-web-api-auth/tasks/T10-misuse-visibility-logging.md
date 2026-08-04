---
task_id: "T10"
title: "Log successful mutation actions with source IP"
status: "done"
depends_on: ["T05", "T11"]
implements: ["FR#16", "AC#16"]
---

## Summary

Adds source-IP-tagged INFO logging for successful authenticated mutation actions
(start/stop/reload/trigger/log-level-change), routed through the existing `"hassette"` logger so the
lines appear in `/api/logs/recent` and the dashboard's log view like any other framework log.

FR#17's coalesced failed-auth WARN is **not** part of this task — it moved into T05's middleware,
because it keys off the outgoing 401 status rather than the middleware's own reject branch, which is
what lets it also count `POST /api/auth/session`'s handler-issued 401s. See T05 for that half.

`depends_on` includes T11 purely for write serialization: T06, T10, and T11 all extend
`tests/integration/web_api/test_auth.py`, and T10/T11 would otherwise be dispatchable in parallel
onto the same file. T10 has no functional dependency on T11's assertions.

## Target Files

- modify: `src/hassette/web/routes/apps.py` — success logging for start/stop/reload
- modify: `src/hassette/web/routes/scheduler.py` — success logging for trigger
- modify: `src/hassette/web/routes/logs.py` — success logging for log-level change
- modify: `tests/integration/web_api/test_auth.py` — coverage for both logging behaviors
- read: `src/hassette/web/dependencies.py:21` — `getLogger(__name__)` convention already used throughout `web/`

## Prompt

Read design.md's `## Architecture → Misuse-visibility logging` section in full, and FR#16.

In each of `web/routes/apps.py` (start/stop/reload handlers), `web/routes/scheduler.py` (trigger
handler), and `web/routes/logs.py` (log-level-change handler), add an INFO log line on success, via
the existing `"hassette"` logger (`getLogger(__name__)`, the convention used throughout
`web/dependencies.py:21` and elsewhere), naming the action taken and the source IP (from the raw
`scope["client"]`, the same signal T03/T05 already extract — reuse it, don't re-derive it
separately).

Extend `tests/integration/web_api/test_auth.py` with: a mutation action (e.g. `POST
/api/apps/{app_key}/start` with valid credentials) produces a log line naming the action and source
IP, retrievable via `GET /api/logs/recent`.

Do not add failed-auth counting here. T05 owns it, on the response side of its middleware.

## Focus

- The source-IP extraction should reuse whatever T03/T05 already use to read `scope["client"]` —
  don't add a second, possibly-inconsistent way of reading the peer address.
- Log at the point the action succeeded, not at request entry. A line saying an app was reloaded
  should not appear for a request that 500'd partway through the reload.
- This task is deliberately small. If you find yourself editing `web/middleware.py`, you are building
  T05's half of the misuse-visibility work — stop and check T05, which already owns it.

## Verify

- [ ] FR#16: Integration test confirms a successful `start`/`stop`/`reload`/`trigger`/log-level-change request produces an INFO log line naming the action and source IP, visible via `GET /api/logs/recent`.
- [ ] AC#16: Same integration test as FR#16, phrased at the AC's exact scenario (a `start`/`stop`/`reload`/`trigger`/log-level-change request from an authenticated caller).
