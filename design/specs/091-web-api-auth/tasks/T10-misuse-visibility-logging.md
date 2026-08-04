---
task_id: "T10"
title: "Log successful mutation actions and coalesce failed-auth WARNs"
status: "planned"
depends_on: ["T05"]
implements: ["FR#16", "FR#17", "AC#16", "AC#17"]
---

## Summary

Adds two log-visibility behaviors, both routed through the existing `"hassette"` logger so they
appear in `/api/logs/recent` and the dashboard's log view: successful authenticated mutation actions
(start/stop/reload/trigger/log-level-change) get an INFO line with the source IP, and failed
authentication attempts get a rate-limited/coalesced WARN when they exceed a threshold from one
source in a window — not one log line per attempt, which would reintroduce a noise problem. There is
no existing coalescing-log pattern in this codebase to reuse (confirmed during Phase 2 exploration);
this is net-new logic, not an import of an existing utility.

## Target Files

- modify: `src/hassette/web/middleware.py` — coalesced failed-auth WARN logging
- modify: `src/hassette/web/routes/apps.py` — success logging for start/stop/reload
- modify: `src/hassette/web/routes/scheduler.py` — success logging for trigger
- modify: `src/hassette/web/routes/logs.py` — success logging for log-level change
- modify: `tests/integration/web_api/test_auth.py` — coverage for both logging behaviors
- read: `src/hassette/web/dependencies.py:21` — `getLogger(__name__)` convention already used throughout `web/`

## Prompt

Read design.md's `## Architecture → Misuse-visibility logging` section in full, and FR#16, FR#17.

For **successful mutation logging (FR#16)**: in each of `web/routes/apps.py` (start/stop/reload
handlers), `web/routes/scheduler.py` (trigger handler), and `web/routes/logs.py` (log-level-change
handler), add an INFO log line on success, via the existing `"hassette"` logger
(`getLogger(__name__)`, the convention used throughout `web/dependencies.py:21` and elsewhere),
naming the action taken and the source IP (from the raw `scope["client"]`, the same signal T03/T05
already extract — reuse it, don't re-derive it separately).

For **failed-auth coalescing (FR#17)**: in `web/middleware.py` (T05), when a request is rejected for
lacking valid credentials, do not log per-attempt. Instead, track failed attempts per source address
in a bounded in-memory structure (a simple counter with a time window is sufficient — no persistence
needed, this resets on restart which is acceptable for a misuse-visibility signal) and emit exactly
one coalesced WARN when a source exceeds a threshold within a window (design.md's example: "12 failed
auth attempts from 203.0.113.4 in the last 5 minutes"). Pick concrete threshold/window values
consistent with that example (e.g., 10 attempts / 5 minutes) and document the choice in a comment or
docstring — there's no existing pattern in this codebase to derive them from (confirmed during
exploration; `bus/rate_limiter.py`'s `RateLimiter` is for handler-call debounce/throttle via
`asyncio.Task` cancellation, not log-line suppression, and is not reusable here).

Extend `tests/integration/web_api/test_auth.py` with: a mutation action (e.g. `POST
/api/apps/{app_key}/start` with valid credentials) produces a log line naming the action and source
IP, retrievable via `GET /api/logs/recent`; a burst of failed-auth requests from one source within
the window produces exactly one coalesced WARN (not N per-attempt lines), also retrievable via `GET
/api/logs/recent`.

## Focus

- No existing coalescing/rate-limited-log utility exists in this codebase — build the counting logic
  directly in `web/middleware.py`, scoped to what FR#17 needs (a simple sliding or fixed window
  counter per source address). Don't go looking for a nonexistent shared utility, and don't
  over-engineer this into a general-purpose rate limiter — the design's Non-Goals explicitly excludes
  rate limiting on mutation endpoints; this counter exists purely for the WARN log, it does not
  reject or throttle any request.
- The source-IP extraction for both FR#16 and FR#17 should reuse whatever T03/T05 already use to read
  `scope["client"]` — don't add a second, possibly-inconsistent way of reading the peer address.
- Keep the in-memory failed-attempt tracker bounded (e.g., evict old entries) — this runs for the
  life of the process; an unbounded per-source dict is a slow memory leak under sustained attack
  traffic, even though DoS mitigation itself is out of scope.

## Verify

- [ ] FR#16: Integration test confirms a successful `start`/`stop`/`reload`/`trigger`/log-level-change request produces an INFO log line naming the action and source IP, visible via `GET /api/logs/recent`.
- [ ] FR#17: Integration test confirms a burst of failed-auth requests exceeding the threshold from one source within the window produces exactly one coalesced WARN log line, not one per attempt.
- [ ] AC#16: Same integration test as FR#16, phrased at the AC's exact scenario (a `start`/`stop`/`reload`/`trigger`/log-level-change request from an authenticated caller).
- [ ] AC#17: Same integration test as FR#17, phrased at the AC's exact scenario (a burst of failed-auth requests from one source within a window produces exactly one coalesced WARN).
