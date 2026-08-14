# Tests: integration/bus

## Available fixtures (this directory's conftest.py)

- `bus_harness` — yields `(HassetteHarness, Hassette, Bus)` with bus + scheduler + state_proxy + state_registry wired, state proxy marked ready, and a stubbed API (`get_states_raw` returns `[]`)

## Shared helpers

- `from hassette.test_utils import HassetteHarness` — builder used directly by `bus_harness`; seed state via `harness.seed_state()`
- This directory's `helpers.py` also exposes `seed`, `fire`, `pump_event_loop`, `ENTITY`, and `EVENT_LOOP_YIELDS` — shared by `test_execution_modes.py` and `test_execution_modes_guards.py` for overlap-mode dispatch tests.
- `seed(harness, entity_id, state_value, *, attributes=None, last_changed=None)` — widened to accept optional `attributes`/`last_changed`, forwarded to `make_state_dict`. Used where a test only needs entity_id/state_value/attributes/last_changed instead of building a full state dict and calling `harness.seed_state()` directly.
- `make_collector(hassette)` — returns `(handler, received, fired)`: an async handler that appends every received `RawStateChangeEvent` to `received` and signals `fired` (an `asyncio.Event`) via `hassette.task_bucket.post_to_loop` each time it runs. Replaces the repeated list+Event+handler+`wait_for` boilerplate. Only usable for `on_state_change`/`on_attribute_change` registrations — the handler is hard-typed to `RawStateChangeEvent`, so it does not fit `bus.on(topic=...)` registrations with other payload types or `on_error` callback patterns (confirmed by trial adoption during design; see `design/specs/097-dedupe-bus-test-scaffolding/design.md`). Currently adopted only in `test_bus_duration.py` and `test_bus_immediate.py`.

## Key conventions

- `bus_harness` starts and stops the harness itself (`await harness.start()` / `await harness.stop()`) — don't wrap it in another harness context manager.
- `DURATION = 0.2` (200ms) is the module's standard short wait for debounce/throttle timing assertions.
