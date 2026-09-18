---
task_id: "T02"
title: "Add integration tests for Bus.wait_for()"
status: "done"
depends_on: ["T01"]
implements: ["AC#6"]
---

## Summary
Add integration tests that exercise `wait_for` with real Bus wiring via `HassetteHarness`. These tests verify the primitive works end-to-end with real event dispatch — not just mocked components. The key test is the arm-before-fire composition pattern with `call_service`.

## Target Files
- read: `src/hassette/bus/bus.py`
- read: `tests/integration/bus/conftest.py`
- read: `tests/integration/bus/test_bus.py`
- create: `tests/integration/bus/test_wait_for.py`

## Prompt
Add integration tests in `tests/integration/bus/test_wait_for.py` using `HassetteHarness` for real Bus wiring.

### Tests to write

1. **Real Bus event dispatch resolves wait_for** — register a `wait_for`, dispatch a matching event through the Bus, assert the returned event matches.

2. **Arm-before-fire composition with call_service (AC#6)** — the critical test:
   - `create_task(bus.wait_for("state_changed", where=..., timeout=5))`
   - Call `api.call_service(...)` (via `RecordingApi`)
   - Emit the corresponding `state_changed` event through the Bus
   - `await` the task and assert it returns the matching event
   - This tests the documented composition pattern end-to-end.

3. **WhereClause filtering with real dispatch** — register a `wait_for` with a predicate, dispatch non-matching events (no resolution), then dispatch a matching event (resolves).

4. **Concurrent waits with real dispatch** — two `wait_for` calls on the same topic with different predicates, dispatch events that match each independently.

### Patterns to follow

Read `tests/integration/bus/conftest.py` and `tests/integration/bus/test_bus.py` for the existing integration test patterns. Use `HassetteHarness` to wire the real Bus, and follow the existing fixture and assertion conventions.

For `call_service` interaction, use `RecordingApi` — check `tests/support/factories.py` for `make_recording_api`.

## Focus
- Integration tests use `HassetteHarness`, which wires real components (bus, scheduler, state proxy). See `tests/TESTING.md` for the full guide.
- The arm-before-fire test (AC#6) is the most important — it validates the documented composition pattern that motivated issue #528.
- Use `create_state_change_event` from `tests/support/helpers.py` to build the events.
- `HassetteHarness` exposes `bus` and `api` directly.

## Verify
- [ ] AC#6: The arm-before-fire composition pattern (`create_task(wait_for(...))`, then service call, then `await task`) correctly resolves when the event is emitted
