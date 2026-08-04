---
task_id: "T08"
title: "Wire startup guards, proxy_headers=False, and periodic trusted-proxy refresh"
status: "planned"
depends_on: ["T01", "T02", "T03"]
implements: ["FR#4", "FR#5", "FR#13", "FR#14", "AC#8", "AC#9"]
---

## Summary

Wires the pieces built in T01-T03 into `WebApiService`'s actual startup sequence: calls T02's token
resolution in `on_initialize()`, adds `WebApiService.depends_on = [..., SchedulerService]` and a
child `Scheduler` (following `StateProxy`'s established pattern) to periodically re-resolve
`trusted_proxies` hostname entries via T03's refresh function, sets `proxy_headers=False` explicitly
on the `uvicorn.Config`, and adds the two startup guards: a hard block when `auth_enabled=false` and
`host` isn't loopback, and a WARNING (not a block) when `host` isn't loopback and `trusted_proxies`
is empty.

## Target Files

- modify: `src/hassette/core/web_api_service.py` — `depends_on`, child `Scheduler`, startup guards, `proxy_headers=False`, token resolution call
- modify: `tests/unit/core/test_web_api_service.py` — unit tests for the new wiring
- read: `src/hassette/core/state_proxy.py:142,255-261` — `self.add_child(Scheduler)` + `run_every()` pattern to follow

## Prompt

Read design.md's `## Architecture → Startup guards` in full, plus FR#4, FR#5, FR#13, FR#14, and the
Dependencies and Assumptions entry about `WebApiService.depends_on` gaining `SchedulerService`.

In `src/hassette/core/web_api_service.py`:

1. Add `SchedulerService` to `WebApiService.depends_on` (currently `[RuntimeQueryService,
   TelemetryQueryService]` at line 28).
2. In `on_initialize()` (currently lines 49-56), add a child `Scheduler` via `self.add_child(Scheduler)`
   — follow `StateProxy`'s exact pattern at `core/state_proxy.py:142` (`self.scheduler =
   self.add_child(Scheduler)`).
3. Call T02's token resolution function, so the resolved token (and its INFO branch log) actually
   fires on real startup, not just in T02's unit tests.
4. Call T03's hostname-resolve function once at startup, then schedule it to re-run periodically via
   `self.scheduler.run_every(...)` — follow `StateProxy._install_poll_job`'s pattern at
   `state_proxy.py:255-261` (`if_exists="skip"`, `mode="single"`) for the periodic job registration.
   Pick an interval of "a few minutes" per design.md's Architecture section (e.g. 5 minutes) — this
   is FR#5's periodic-refresh glue; T03 already built the pure resolve/refresh logic this calls into.
5. In `serve()` (currently lines 58-90), add `proxy_headers=False` explicitly to the
   `uvicorn.Config(...)` call (currently lines 65-73, which has no `proxy_headers` argument today) —
   this disables uvicorn's own `ProxyHeadersMiddleware`, which would otherwise silently trust
   `X-Forwarded-For` from whatever `FORWARDED_ALLOW_IPS` resolves to (default `"127.0.0.1"`) and
   rewrite `scope["client"]` before T03's trusted-peer check ever sees the real peer.
6. Add the hard-block startup guard: if `config.web_api.auth_enabled is False` and `host` (from
   `config.web_api.host`) is not a loopback address, refuse to start — raise an error naming both
   settings explicitly (not a generic message).
7. Add the warning-only startup check: if `host` is not loopback and `config.web_api.trusted_proxies`
   is empty, log a WARNING naming TLS explicitly (per design.md's User Scenarios "Binding
   non-loopback with no proxy and no TLS" flow) — this does not block startup; auth (the token/cookie
   mechanism) is still on and protecting the API, the warning is about transport security only.

## Focus

- `StateProxy` is the concrete precedent for "a framework service that needs periodic scheduling via
  a child `Scheduler`" — mirror its shape exactly rather than inventing a new pattern.
- The hard-block guard (step 6) and the warning-only check (step 7) are different severities for a
  similar-sounding condition — don't conflate them. Step 6 fires only when auth is explicitly
  disabled; step 7 fires regardless of auth state whenever there's no evidence of a fronting proxy.
- `proxy_headers=False` is a one-line addition to an existing `uvicorn.Config(...)` call — don't
  restructure the surrounding `serve()` method beyond what's needed for this line and the guards.
- Loopback-address checking: use the stdlib `ipaddress` module's `is_loopback` property (parse
  `host` as an `ipaddress.ip_address` first) rather than a hand-rolled string comparison against
  `"127.0.0.1"` — `host` could be `"localhost"` or another loopback form.

## Verify

- [ ] FR#4: Unit test confirms `WebApiService.serve()` constructs `uvicorn.Config` with `proxy_headers=False` (inspect the call, e.g. via mock/spy on `uvicorn.Config`).
- [ ] FR#5: Unit test confirms `on_initialize()` schedules a periodic job via `self.scheduler.run_every(...)` that calls T03's refresh function, in addition to calling it once at startup.
- [ ] FR#13: Unit test confirms `WebApiService` raises a startup error naming both `auth_enabled` and `host` when `auth_enabled=False` and `host="0.0.0.0"`.
- [ ] FR#14: Unit test confirms a WARNING log line naming TLS is emitted when `host="0.0.0.0"` and `trusted_proxies=()`, and confirms no such warning fires when `trusted_proxies` is non-empty.
- [ ] AC#8: Unit test confirms starting with `auth_enabled=false` and `host="0.0.0.0"` fails at startup with an error naming both settings (same test as FR#13, phrased at the AC's exact scenario).
- [ ] AC#9: Unit test confirms the WARNING fires for empty `trusted_proxies` with non-loopback host, and does not fire when `trusted_proxies` is non-empty (same test as FR#14, phrased at the AC's exact scenario).
