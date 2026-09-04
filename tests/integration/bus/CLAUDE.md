# Tests: integration/bus

## Available fixtures (this directory's conftest.py)

- `bus_harness` — yields `(HassetteHarness, Hassette, Bus)` with bus + scheduler + state_proxy + state_registry wired, state proxy marked ready, and a stubbed API (`get_states_raw` returns `[]`)

## Shared helpers

- `from hassette.testing import HassetteHarness` — builder used directly by `bus_harness`; seed state via `harness.seed_state()`
- This directory's `helpers.py` also exposes `seed`, `fire`, `pump_event_loop`, `ENTITY`, and `EVENT_LOOP_YIELDS` — shared by `test_execution_modes.py` and `test_execution_modes_guards.py` for overlap-mode dispatch tests.
- `seed(harness, entity_id, state_value, *, attributes=None, last_changed=None)` — widened to accept optional `attributes`/`last_changed`, forwarded to `make_state_dict`. Used where a test only needs entity_id/state_value/attributes/last_changed instead of building a full state dict and calling `harness.seed_state()` directly.
- `make_collector(hassette)` — returns `(handler, received, fired)`: an async handler that appends every received `RawStateChangeEvent` to `received` and signals `fired` (an `asyncio.Event`) via `hassette.task_bucket.post_to_loop` each time it runs. Replaces the repeated list+Event+handler+`wait_for` boilerplate. Only usable for `on_state_change`/`on_attribute_change` registrations — the handler is hard-typed to `RawStateChangeEvent`, so it does not fit `bus.on(topic=...)` registrations with other payload types or `on_error` callback patterns (confirmed by trial adoption during design; see `design/specs/097-dedupe-bus-test-scaffolding/design.md`). Currently adopted only in `test_bus_duration.py` and `test_bus_immediate.py`.
- `drive_state_change(harness, entity_id, old_value, new_value)` — combines `send_state_change(...)` (dispatch the event through the bus) with `seed(...)` (sync StateProxy's cached snapshot to the same new value), the trigger pair every duration/immediate test performs after driving a transition. Only fits the common case where both calls target the same entity/new-value pair; call `send_state_change`/`seed` directly when a test seeds a different value than it dispatched, or needs other work between the two calls. Adopted in `test_bus_duration.py` and `test_bus_error_handler_combos.py` (trigger lines only — `test_bus_error_handler_combos.py`'s `_ErrorCollector` abstraction is untouched). Not adopted in `test_bus_immediate.py` — that file only ever calls `seed()` alone (registration-time snapshots for immediate-fire tests), never paired with `send_state_change`, so the pattern doesn't occur there.
- `send_live_event_and_wait_drain(hassette, bus, entity_id, old_value, new_value)` — sends a state-change event and waits for `bus.task_bucket` to drain (`wait_for(lambda: len(bus.task_bucket) == 0, ...)`), for `once=True` tests proving a second live event doesn't re-fire an already-consumed listener. Unlike `drive_state_change`, it doesn't sync StateProxy's cache and waits on task_bucket draining rather than `bus_service.await_dispatch_idle()` — the two aren't interchangeable. Adopted in `test_bus_immediate.py` and `test_bus_error_handler_combos.py`.

## File-local helpers

These live at module scope in their own test file, not in `helpers.py` — a reader scanning `helpers.py` alone won't find them. Each collapses a setup pattern specific to that one file:

- `test_bus_error_handler_combos.py` — `make_error_collector_pair()`: builds the `(app_level, per_listener)` `_ErrorCollector()` pair used by the three tests proving a per-listener `on_error` handler takes precedence over an app-level one.

## Key conventions

- `bus_harness` starts and stops the harness itself (`await harness.start()` / `await harness.stop()`) — don't wrap it in another harness context manager.
- `DURATION = 0.2` (200ms) is the module's standard short wait for debounce/throttle timing assertions.
- Many registration "arrange" blocks (`bus.on_state_change(...)`/`bus.on_attribute_change(...)`) and "trigger, wait, assert one fire" tails in `test_bus_duration.py`, `test_bus_immediate.py`, and `test_bus_error_handler_combos.py` are wrapped in `# dup-ignore-start`/`# dup-ignore-end` markers rather than extracted into helpers — each test's specific entity/predicate/duration/once/on_error kwargs (and, for tail blocks, its fire-count assertion) are the actual point of that test, and a shared helper would need as many parameters as the registration call itself. See `design/specs/097-dedupe-bus-test-scaffolding/design.md` (FR#12) for the full accounting.
