---
task_id: "T04"
title: "Build Tier 2 protect-loop monkeypatch (intercept + raise)"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#5", "FR#6", "FR#8", "FR#12", "AC#4", "AC#5", "AC#9", "AC#10"]
---

## Summary
Build the Tier 2 call-site guard: a `protect_loop`-style monkeypatch over a curated set of blocking primitives that, when one is called on the loop thread, captures the offending line, names the app via the marker, and responds per the resolved behavior — intercepting before the blocking call proceeds. Tier 2 defaults on in `dev_mode` and off in production; an explicit flag enables it in prod. Install and teardown must be idempotent, reversible, and test-isolated so patches never leak.

## Prompt
Implement Tier 2 from `design/specs/074-blocking-io-detection/design.md`, `## Architecture` → "Tier 2 — call-site interception". Read `## Key Constraints` (no prod-default raise; no patch leakage) first.

1. **Guard module** — `src/hassette/core/block_io_guard.py` (this may already hold the T01 resolver; co-locate). Provide `install(loop_thread_id, ...)` and `uninstall()` that patch and restore a curated primitive set seeded from HA's `block_async_io.py`: `builtins.open`, `time.sleep`, `socket.socket.connect`/`recv`/`send`, `os.listdir`/`scandir`/`walk`, `glob.glob`. Keep the primitive list as data in one place (auditable), not scattered patches.
2. **Thread-id gate** — each wrapper checks `threading.get_ident() == loop_thread_id`. Off-thread calls (executor offload) pass straight through to the original, untouched. On a loop-thread hit: resolve behavior (T01 resolver), capture the offending line via `capture_source_location()` / `capture_registration_source()` (`utils/source_capture.py`), read the marker (T02) for app attribution, then respond — `IGNORE` passes through, `WARN`/`ERROR` emit `HassetteBlockingIOWarning` (`ERROR` raises via the user's `filterwarnings("error")`); under the dev default filter the warning surfaces as a raised exception *before* the blocking call runs.
3. **Enablement** — Tier 2 is active when `blocking_io.deep_detection_enabled` is `True`, or `None` and `dev_mode` is on. In production (`dev_mode` off) it stays off unless `blocking_io.allow_deep_detection_in_prod` is `True`. Mirror the `allow_reload_in_prod` gating precedent.
4. **Install/teardown** — install in `src/hassette/core/core.py` `run_forever` after line 449 (alongside the T03 watchdog install), gated on the enablement rule. Uninstall on shutdown, restoring every original. Install must be idempotent (double-install is a no-op); uninstall must leave zero residual patches.
5. **Tests** — unit + integration. In `dev_mode`, `time.sleep` on the loop thread raises before sleeping (AC#5); in prod without the flag, it does not raise and nothing is patched (AC#5, AC#10). A sync handler (run via the executor, off-thread) doing blocking I/O is NOT flagged (AC#4 — the warning side; the no-DB-row side is verified in T06). After shutdown, no primitive remains patched and a re-install is clean (AC#9, FR#12). Use a fixture that guarantees teardown even on test failure so patches never leak into other tests.

This task does NOT persist events to the DB (T05 wires that). Expose the detected event structure for T05 to consume.

## Focus
- **Patch leakage is the top risk.** The repo's tests are sensitive to cross-test state. Wrap install/uninstall in a context manager or autouse fixture with guaranteed teardown; assert originals are restored. HA's lesson: always tear down after tests.
- Thread-id gating is what makes executor offload (`TaskBucket.run_in_thread` / `make_async_adapter`, and `logging_service` shutdown) invisible to Tier 2 — those run on worker threads. Never relax the gate (FR#8).
- C-extension/C-driver blocking (numpy, psycopg2) cannot be caught here — that's Tier 1's job. Don't try to patch C internals; document the boundary honestly (the concept page in T06).
- `core.py:449` has `_loop_thread_id`; pass it into `install`. Tier 2 install sits next to the T03 watchdog install — coordinate so both gate cleanly and both tear down on shutdown.
- Behavior resolution and the marker come from T01/T02 — import, don't reimplement.
- Capture full test output to a tmp file; do NOT run `pytest -n auto`.

## Verify
- [ ] FR#5: Each patched primitive, when called on the loop thread, responds per the resolved behavior at the call site before the blocking call proceeds; a unit test covers at least `time.sleep` and `open`.
- [ ] FR#6: Tier 2 is active by default in `dev_mode` and inactive in production unless `allow_deep_detection_in_prod` is set; tests cover both modes.
- [ ] FR#8: A blocking call on a worker thread (executor offload) passes through unflagged — a test asserts no warning fires off the loop thread.
- [ ] FR#12: Install is idempotent and uninstall restores every original; a test asserts no patched primitive remains after teardown.
- [ ] AC#4: A sync handler doing blocking I/O via the executor produces no Tier 2 warning (no-row side verified in T06).
- [ ] AC#5: In `dev_mode`, loop-thread `time.sleep` raises `HassetteBlockingIOWarning` before sleeping; in prod without the flag it does not raise.
- [ ] AC#9: After shutdown, no primitive remains patched and a second install is clean.
- [ ] AC#10: With `allow_deep_detection_in_prod` unset in production, no primitives are patched.
