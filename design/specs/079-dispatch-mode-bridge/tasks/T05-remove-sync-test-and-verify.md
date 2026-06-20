---
task_id: "T05"
title: "Delete sync test and verify behavior on the real surface"
status: "done"
depends_on: ["T03", "T04"]
implements: ["FR#10", "AC#4", "AC#5", "AC#7", "AC#8"]
---

## Summary

With both subsystems migrated to the single shared constant, delete the now-vacuous
sync test, then prove the refactor is behavior-preserving on the real surface
(system + e2e) — not unit tests alone, since this touches core dispatch. Confirm the
patch points actually fire at the patched value by running the stall-watch tests.

## Target Files

- delete: `tests/unit/core/test_stall_threshold_sync.py`
- read: `src/hassette/execution_mode.py`
- read: `src/hassette/bus/listeners.py`
- read: `src/hassette/core/scheduler_service.py`
- read: `design/specs/079-dispatch-mode-bridge/design.md`

## Prompt

1. Delete `tests/unit/core/test_stall_threshold_sync.py` outright — with one
   `STALL_THRESHOLD_SECONDS` in `execution_mode.py`, the "two constants stay equal"
   invariant is vacuous. Confirm nothing else imports the symbols it referenced
   (`from hassette.bus.listeners import STALL_THRESHOLD_SECONDS` /
   `from hassette.core.scheduler_service import STALL_THRESHOLD_SECONDS` still resolve
   via the module-local imports, so any other test importing them keeps working).
2. Confirm the patch points fire at the patched value by RUNNING the stall-watch
   tests (do not reason about it): the bus test patches
   `bus.listeners.STALL_THRESHOLD_SECONDS` and the scheduler test patches
   `scheduler_service.STALL_THRESHOLD_SECONDS`; both must still cause the watchdog to
   fire at 0.05s and the warn spy to receive 0.05.
3. Run the full unit + integration suite for the affected areas
   (`tests/integration/bus/`, `tests/integration/test_scheduler_mode.py`,
   `tests/unit/bus/`, `tests/unit/core/`, `tests/unit/scheduler/`).
4. Run the core-change pre-ship gates: `uv run nox -s system` and
   `uv run nox -s e2e`. Per CLAUDE.md, unit/integration tests alone are insufficient
   for changes under `src/hassette/core/` and bus dispatch — they mock the very
   `task_bucket.spawn` boundary where a future-bridge regression would hide.
   Note the py3.11 + coverage `async_raise` deadlock per project memory — keep
   coverage off the C-blocked-worker shutdown combo.
5. Run `uv run pyright` on the changed files and confirm it is clean.

Capture full output to a temp file (the suites are large) and report pass/fail with
evidence, not "should pass".

## Focus

- This is the verification task — its value is the evidence, not new code. The only
  source change is the test deletion.
- `nox -s system` requires Docker; `nox -s e2e` requires Playwright/Chromium. If
  either environment is unavailable locally, say so explicitly and flag that the
  core-change gate (AC#7) could not be fully satisfied locally — do not silently
  skip it or mark it green.
- Behavioral invariants to confirm unchanged (FR#10): SINGLE suppression, RESTART
  cancel-and-replace, QUEUED serialization, newest-drop-at-cap, PARALLEL
  fire-and-forget, the `QUEUED_ACCEPTED`-no-hang drain, and the stall WARNING
  level/shape (the logged duration now reflects the armed threshold — identical in
  production at 60.0s, per the design's Behavioral Invariants note).

## Verify

- [ ] FR#10: full affected unit + integration suites pass, confirming every overlap
      mode, the QUEUED_ACCEPTED-no-hang path, and the stall WARNING behavior are
      unchanged.
- [ ] AC#4: `tests/unit/core/test_stall_threshold_sync.py` is deleted and nothing
      references it; the suite collects cleanly without it.
- [ ] AC#5: the bus and scheduler stall-watch tests fire at the patched threshold
      (verified by running them, not by inspection).
- [ ] AC#7: `uv run nox -s system` and `uv run nox -s e2e` pass locally (or the
      unavailability of Docker/Playwright is explicitly flagged).
- [ ] AC#8: `uv run pyright` is clean for the changed files.
