# Tests: integration/bus

## Available fixtures (this directory's conftest.py)

- `bus_harness` — yields `(HassetteHarness, Hassette, Bus)` with bus + scheduler + state_proxy + state_registry wired, state proxy marked ready, and a stubbed API (`get_states_raw` returns `[]`)

## Shared helpers

- `from hassette.test_utils import HassetteHarness` — builder used directly by `bus_harness`; seed state via `harness.seed_state()`
- This directory's `helpers.py` also exposes `seed`, `fire`, `pump_event_loop`, `ENTITY`, and `EVENT_LOOP_YIELDS` — shared by `test_execution_modes.py` and `test_execution_modes_guards.py` for overlap-mode dispatch tests.

## Key conventions

- `bus_harness` starts and stops the harness itself (`await harness.start()` / `await harness.stop()`) — don't wrap it in another harness context manager.
- `DURATION = 0.2` (200ms) is the module's standard short wait for debounce/throttle timing assertions.
