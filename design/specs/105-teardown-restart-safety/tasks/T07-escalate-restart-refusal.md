---
task_id: "T07"
title: "Escalate ServiceWatcher restart refusal"
status: "planned"
depends_on: ["T05", "T06"]
implements: ["FR#8", "FR#9", "FR#12", "AC#6"]
---

## Summary

Route typed restart refusal from ServiceWatcher's ordinary backoff and cooldown recovery through one fatal path. Make
root shutdown independent of telemetry delivery, retain the existing overlap guard until escalation completes, and use
the process-latched fatal reason/root shutdown signal to prevent delayed or duplicate recovery attempts.

## Target Files

- read: `design/specs/105-teardown-restart-safety/design.md`
- modify: `src/hassette/core/service_watcher.py`
- modify: `tests/unit/core/test_service_watcher_coverage.py`
- modify: `tests/unit/core/test_service_watcher_exhausted.py`
- modify: `tests/unit/core/test_fatal_shutdown.py`
- modify: `tests/integration/test_service_watcher.py`
- read: `tests/unit/core/conftest.py`

## Prompt

Implement `Architecture → ServiceWatcher refusal`. Add one typed refusal handler and catch `RestartRefusedError` before
generic restart exceptions in both `execute_restart()` and `cooldown_and_retry()`. The handler must synchronously record
the first fatal reason, directly call `request_shutdown()` on Hassette before telemetry, best-effort emit one CRASHED
event carrying the existing exception fields, log event-dispatch failure, and return without retry/cooldown scheduling.
Hold `_restarting` until reason, shutdown request, and event attempt finish. Add admission checks to `restart_service()`,
`execute_restart()`, and `cooldown_and_retry()` at entry and immediately before every `restart()` call; a fatal reason or
root shutdown request must stop recovery. Preserve generic exception handling, RestartSpec budgets, backoff, cooldown
limits, and readiness reset on clean recovery. Write integration regressions for both refusal paths first.

## Focus

- Do not call full `hassette.shutdown()` inline from the refusal handler; request shutdown so `run_forever()` owns root
  teardown and fatal exit behavior.
- Event dispatch is telemetry, not the control path. Its failure cannot undo fatal reason or shutdown signaling.
- A duplicate FAILED/CRASHED event after `_restarting` clears is suppressed by `fatal_shutdown_reason` or the root
  shutdown event, not by a new watcher state machine.
- Cooldown budget reset must not occur after fatal admission closes.
- Existing `shutdown_if_crashed()` remains valid for unrelated CRASHED events and must not become the refusal path.

## Verify

- [ ] FR#8: `uv run pytest tests/unit/core/test_service_watcher_coverage.py tests/integration/test_service_watcher.py -q` proves watcher escalation preserves typed refusal identity and report details in the existing exception fields.
- [ ] FR#9: `uv run pytest tests/unit/core/test_service_watcher_exhausted.py tests/integration/test_service_watcher.py -q` proves clean recovery retains existing backoff, budget, cooldown, and readiness-reset behavior.
- [ ] FR#12: `uv run pytest tests/unit/core/test_service_watcher_coverage.py tests/unit/core/test_fatal_shutdown.py tests/integration/test_service_watcher.py -q` proves both refusal paths converge on one fatal reason/root shutdown request with no later restart or cooldown.
- [ ] AC#6: `uv run pytest tests/integration/test_service_watcher.py -q` proves backoff and cooldown refusal each call restart once, successful delivery emits exactly one CRASHED event, dispatch failure cannot prevent shutdown, and a duplicate trigger after the handler returns emits no second CRASHED event or recovery attempt.
