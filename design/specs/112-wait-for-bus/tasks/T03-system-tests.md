---
task_id: "T03"
title: "Add system tests for Bus.wait_for() against real HA"
status: "done"
depends_on: ["T01"]
implements: ["AC#7", "AC#8", "AC#9"]
---

## Summary
Add system tests that exercise `wait_for` against a real Home Assistant instance via Docker. These test the full pipeline: HA state change → WebSocket → Bus dispatch → future resolution. Three scenarios: basic event resolution, timeout under real latency, and shutdown cancellation mid-wait.

## Target Files
- read: `src/hassette/bus/bus.py`
- read: `tests/system/conftest.py`
- read: `tests/system/test_bus.py`
- read: `tests/system/docker-compose.yml`
- modify: `tests/system/test_bus.py`

## Prompt
Add system tests to `tests/system/test_bus.py` (or a new `tests/system/test_wait_for.py` if the existing file is already large). These tests require Docker — they run against a real HA container.

### Tests to write

1. **AC#7: Real HA service call + wait_for resolves** — toggle an `input_boolean` entity via `api.call_service`, `wait_for` the resulting `state_changed` event. Assert the event is returned with the correct entity_id and state.

2. **AC#8: Timeout under real HA latency** — `wait_for` a state_changed event for an entity that will NOT change, with a short timeout (e.g., 2 seconds). Assert `asyncio.TimeoutError` is raised.

3. **AC#9: Shutdown mid-wait against real HA** — start a `wait_for` with `timeout=None` or a long timeout, then trigger hassette shutdown. Assert the caller is unblocked (receives `CancelledError` or the task is cancelled).

### Patterns to follow

Read `tests/system/conftest.py` for fixtures (hassette instance, HA connection, app setup). Read `tests/system/test_bus.py` for existing system-level bus test patterns. System tests use `@pytest.mark.system` (check the existing markers).

The system test Docker compose is at `tests/system/docker-compose.yml`. Tests use real HA entities — check which `input_boolean` entities are available in the test HA config.

## Focus
- System tests run with `nox -s system` and require Docker. They are NOT run locally during normal dev — CI runs them. But they need to be written correctly.
- Check `tests/system/conftest.py` for how the hassette instance and HA connection are set up. The fixtures likely provide a connected hassette with access to `bus` and `api`.
- For AC#9 (shutdown mid-wait), check how `tests/system/test_shutdown.py` triggers shutdown — follow the same pattern.
- The `input_boolean` entities available for testing depend on the HA fixtures in `tests/system/`. Check `generate_ha_fixtures.py` and the Docker compose for what's available. The existing system tests use `input_boolean.test` (see `tests/system/test_api.py:32`) — verify this entity exists in `tests/fixtures/ha-config/configuration.yaml` before writing test bodies.
- System tests may need `@pytest.mark.system` or similar marker — check existing test files.

## Verify
- [ ] AC#7: System test passes — real HA service call triggers `state_changed` event that `wait_for` captures
- [ ] AC#8: System test passes — `wait_for` with short timeout raises `TimeoutError` against real HA
- [ ] AC#9: System test passes — hassette shutdown unblocks a pending `wait_for`
