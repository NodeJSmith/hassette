# Testing — Factories & Internals

**Status:** Exists (169 lines), needs JTBD redesign — currently a flat API catalog, should lead with the common case
**Voice mode:** Reference — terse, system-as-subject
**Page type:** Reference
**Reader's job:** Build custom test data (events, states, mocks) when the harness convenience methods aren't enough.

## What was cut

Nothing removed — this is reference material and completeness matters. But
the order changes. The existing page opens with event factories, which most
readers never use directly (the harness `simulate_*` methods handle it). State
factories and `make_mock_hassette` are more commonly needed.

`RecordingApi` coverage boundary is important reference but belongs after the
factories — readers reach it when they hit a `NotImplementedError` and come
looking for what's supported.

Tier 2 re-exports section stays as a brief note at the end.

## Outline

### H2: State Factories
Most common need: build state dicts for seeding or assertions.

#### H3: make_state_dict
Raw HA-format state dict. Parameters and defaults.

#### H3: make_light_state_dict
Shorthand with brightness, color_temp. Parameter table.

#### H3: make_sensor_state_dict
Shorthand with unit_of_measurement, device_class. Parameter table.

#### H3: make_switch_state_dict
Shorthand for switch entities.

### H2: Event Factories
For building raw events when you need to bypass `simulate_*` or test
lower-level bus methods.

#### H3: create_state_change_event
Parameters: entity_id, old_value, new_value (required), rest optional.

#### H3: create_call_service_event
Parameters and example.

### H2: make_mock_hassette
Sealed `AsyncMock` with Pydantic-validated config. Standard pattern for unit
tests needing a hassette mock. Parameter table (data_dir, set_ready, set_loop,
sealed, config_overrides).

### H2: make_test_config
`HassetteConfig` without the full harness — for testing config parsing logic
directly. `data_dir` required, all other fields have test defaults. Parameter
table.

### H2: RecordingApi Coverage Boundary
What's stubbed (write methods), what's redirected (state reads to StateProxy),
what raises `NotImplementedError`. Lists of explicit stubs and redirected
methods. Note about `api.sync` recording facade.

### H2: Internal Helpers
Brief note: `create_hassette_stub`, `create_component_loaded_event`,
`create_service_registered_event`, `make_full_state_change_event` are available
from `hassette.test_utils._internal` but not in `__all__`. Stable but not
public API.

### H2: Next Steps
Links to Testing index, Time Control, Concurrency.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `testing_make_state_dict.py` | Keep | State dict factory |
| `testing_make_light_state_dict.py` | Keep | Light state factory |
| `testing_make_sensor_state_dict.py` | Keep | Sensor state factory |
| `testing_make_switch_state_dict.py` | Keep | Switch state factory |
| `testing_factory_imports.py` | Keep | Import example |
| `testing_create_state_change_event.py` | Keep | Event factory |
| `testing_create_call_service_event.py` | Keep | Service event factory |
| `factories_mock_hassette.py` | Keep | Mock hassette example |
| `testing_make_test_config.py` | Keep | Test config builder |
| `testing_sync_facade.py` | Keep | Sync facade note |

## Cross-Links

- **Links to:** Testing index, Test Harness Reference, API overview (RecordingApi boundary)
- **Linked from:** Test Harness Reference (next steps)
