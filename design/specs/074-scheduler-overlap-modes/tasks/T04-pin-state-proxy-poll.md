---
task_id: "T04"
title: "Pin the state-proxy poll job to single mode"
status: "planned"
depends_on: ["T01"]
implements: ["FR#15", "AC#13"]
---

## Summary

The state-proxy poll (`load_cache` via `run_every`) is the only framework-tier scheduled job. Under
the new framework→`parallel` default it could run concurrent `load_cache` calls on overrun. Pin it
to `mode="single"` so polls never overlap within a scheduler lifecycle, preserving today's
skip-if-running behavior.

## Prompt

Implement design.md "Architecture §7 (Migrate the one framework caller)" and FR#15.

1. **`src/hassette/core/state_proxy.py`** (the `run_every` call at line ~93 in
   `subscribe_to_events`): pass `mode="single"` to the `self.scheduler.run_every(self.load_cache,
   ...)` call.

2. **Test (same task).** An integration test asserting that in steady state (no reconnect), an
   overrunning `load_cache` poll does not run concurrently — the second tick is suppressed while the
   first is in flight (FR#15/AC#13). Drive an overrun by holding `load_cache` open (e.g. an
   `asyncio.Event`) and advancing the scheduler; assert only one concurrent invocation.

Scope is exactly this caller. Do NOT change the framework default itself (it is `parallel` by design
— T01), and do NOT add a cancel-and-wait path to `dequeue_job` (the reconnect-window overlap is an
accepted, documented limitation mitigated by `load_cache`'s internal lock — design FR#15).

## Focus

- `state_proxy.py:78-99` `subscribe_to_events`: it cancels any existing `poll_job` via
  `dequeue_job` then schedules a new one. `load_cache` already guards itself with
  `async with self.lock`, which mitigates the reconnect-window overlap — so the steady-state
  `single` pin is the invariant being asserted, NOT the reconnect race (design narrowed AC#13 to
  steady state).
- The poll interval is `self.hassette.config.state_proxy_poll_interval_seconds`; polling is skipped
  when `config.disable_state_proxy_polling` is set.
- `run_every` gains the `mode` parameter in T01 — this task depends on that.
- Integration test harness: `HassetteHarness` wires real components (see `tests/TESTING.md`); the
  state-proxy poll test likely belongs near existing state-proxy tests — grep `tests/` for
  `state_proxy`/`load_cache`/`poll_job`.

## Verify

- [ ] FR#15: the state-proxy poll job is scheduled with `mode="single"`.
- [ ] AC#13: in steady state, an overrunning poll does not run `load_cache` concurrently (second tick suppressed while the first is in flight).
