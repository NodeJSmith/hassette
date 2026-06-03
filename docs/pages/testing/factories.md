# Factories & Internals

All factory functions listed here are exported from `hassette.test_utils`.

```python
--8<-- "pages/testing/snippets/testing_factory_imports.py"
```

## State Factories

State factories build raw HA-format state dicts. The harness calls them internally for `set_state()`. Tests that need precise attribute control call them directly.

### `make_state_dict`

`make_state_dict` builds a minimal state dict in Home Assistant wire format.

```python
--8<-- "pages/testing/snippets/testing_make_state_dict.py"
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `entity_id` | required | Entity ID, e.g. `"sensor.temperature"`. |
| `state` | required | State string, e.g. `"on"`, `"25.5"`. |
| `attributes` | `None` | Attributes dict. Defaults to `{}`. |
| `last_changed` | `None` | ISO timestamp string. Defaults to now. |
| `last_updated` | `None` | ISO timestamp string. Defaults to now. |
| `context` | `None` | Context dict. Defaults to a generated UUID context. |

### `make_light_state_dict`

`make_light_state_dict` builds a state dict for a light entity with `brightness` and `color_temp` support.

```python
--8<-- "pages/testing/snippets/testing_make_light_state_dict.py"
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `entity_id` | `"light.kitchen"` | Light entity ID. |
| `state` | `"on"` | `"on"` or `"off"`. |
| `brightness` | `None` | Brightness 0–255. Omitted from attributes if not set. |
| `color_temp` | `None` | Color temperature in mireds. Omitted from attributes if not set. |
| `**kwargs` | | Extra attributes or top-level state dict fields (`last_changed`, `last_updated`, `context`). |

### `make_sensor_state_dict`

`make_sensor_state_dict` builds a state dict for a sensor entity.

```python
--8<-- "pages/testing/snippets/testing_make_sensor_state_dict.py"
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `entity_id` | `"sensor.temperature"` | Sensor entity ID. |
| `state` | `"25.5"` | Sensor value as a string. |
| `unit_of_measurement` | `None` | Unit string, e.g. `"°C"`, `"%"`. Omitted from attributes if not set. |
| `device_class` | `None` | HA device class, e.g. `"temperature"`, `"humidity"`. Omitted from attributes if not set. |
| `**kwargs` | | Extra attributes or top-level state dict fields. |

### `make_switch_state_dict`

`make_switch_state_dict` builds a state dict for a switch entity.

```python
--8<-- "pages/testing/snippets/testing_make_switch_state_dict.py"
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `entity_id` | `"switch.outlet"` | Switch entity ID. |
| `state` | `"on"` | `"on"` or `"off"`. |
| `**kwargs` | | Extra attributes or top-level state dict fields. |

## Event Factories

Event factories build typed event objects for direct bus dispatch. Most tests call `harness.simulate_state_change()` or `harness.simulate_call_service()` instead. These factories cover tests that bypass `simulate_*` and exercise lower-level bus methods.

### `create_state_change_event`

`create_state_change_event` builds a [`RawStateChangeEvent`][hassette.events.hass.hass.RawStateChangeEvent] suitable for direct bus dispatch.

```python
--8<-- "pages/testing/snippets/testing_create_state_change_event.py"
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `entity_id` | required | Entity ID. |
| `old_value` | required | Old state value. `None` simulates entity creation. |
| `new_value` | required | New state value. `None` simulates entity removal. |
| `old_attrs` | `None` | Attributes for the old state dict. |
| `new_attrs` | `None` | Attributes for the new state dict. |

When `old_value` or `new_value` is `None`, the corresponding state dict is `None` in the event, not `{"state": None, ...}`. This matches HA's wire format for entity creation and removal.

### `create_call_service_event`

`create_call_service_event` builds a [`CallServiceEvent`][hassette.events.hass.hass.CallServiceEvent].

```python
--8<-- "pages/testing/snippets/testing_create_call_service_event.py"
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `domain` | required | Service domain, e.g. `"light"`. |
| `service` | required | Service name, e.g. `"turn_on"`. |
| `service_data` | `None` | Service data dict. Defaults to `{}`. |

## `make_mock_hassette`

`make_mock_hassette` returns a sealed `AsyncMock` with a real, Pydantic-validated [HassetteConfig][hassette.config.config.HassetteConfig]. It wires readiness events, scheduler service stubs, bus service stubs, and other standard attributes without running `Hassette.__init__`.

```python
--8<-- "pages/testing/snippets/factories_mock_hassette.py"
```

`HassetteConfig` validates config overrides at construction time. An unrecognized field name or out-of-range value raises `pydantic.ValidationError` immediately. Nested group fields accept dicts or model instances.

The mock is sealed by default. Accessing any attribute not wired by the factory raises `AttributeError`. `sealed=False` allows adding extra attributes after construction.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `data_dir` | `tempfile.mkdtemp()` | Directory for Hassette data files. Tests needing DB isolation typically pass `tmp_path`. |
| `set_ready` | `True` | Pre-sets `ready_event` so `wait_for_ready()` resolves immediately. |
| `set_loop` | `True` | Sets `loop` to `asyncio.get_running_loop()`. `False` suits session-scoped fixtures running outside an event loop. |
| `sealed` | `True` | Calls `seal()` after wiring. Unlisted attribute access raises `AttributeError`. |
| `**config_overrides` | | Any `HassetteConfig` field, merged on top of test defaults. |

## `make_test_config`

`make_test_config` builds a `HassetteConfig` without a TOML file, env file, or CLI args. Only the values passed are read. Pydantic validation still runs.

```python
--8<-- "pages/testing/snippets/testing_make_test_config.py"
```

`AppTestHarness` creates a config internally. `make_test_config` covers tests that need a `HassetteConfig` directly without the full harness, such as config parsing or validation logic.

`data_dir` is required. All other fields have test-appropriate defaults:

| Field | Default |
|-------|---------|
| `data_dir` | required (no default) |
| `token` | `"test-token"` |
| `base_url` | `"http://test.invalid:8123"` |
| `disable_state_proxy_polling` | `True` |
| `apps` | `{"autodetect": False}` |
| `web_api` | `{"run": False}` |
| `run_app_precheck` | `False` |

`**overrides` replace any of the defaults.

## RecordingApi Coverage Boundary

`RecordingApi` records write-method calls and delegates read methods to the seeded [`StateProxy`][hassette.core.state_proxy.StateProxy]. Methods requiring a live HA connection raise `NotImplementedError`.

**Explicit stubs** that raise `NotImplementedError` directly:

- `get_state_raw()`
- `get_states_raw()`
- `get_history()`
- `render_template()`
- `ws_send_and_wait()`
- `ws_send_json()`
- `rest_request()`
- `delete_entity()`

**Redirected via `__getattr__`** with a message pointing to `get_state()`:

- `get_state_value()`
- `get_state_value_typed()`
- `get_attribute()`

Any other public name not defined on `RecordingApi` also falls through to `__getattr__` and raises `NotImplementedError`.

`harness.set_state()` seeds data for read methods. Read methods that delegate to `StateProxy` (`get_state()`, `get_states()`, `get_entity()`, `get_entity_or_none()`, `entity_exists()`, `get_state_or_none()`) return seeded values directly.

`harness.api_recorder.sync` is a `RecordingSyncFacade`. Write calls made via `self.api.sync.*` appear in the same `api_recorder.calls` list as their async counterparts. The same assertion API works for both:

```python
--8<-- "pages/testing/snippets/testing_sync_facade.py"
```

Methods not covered by the sync facade raise `NotImplementedError` rather than silently succeeding.

## Internal Helpers

`hassette.test_utils.helpers` contains several helpers used internally by the test infrastructure but not exported in `__all__`:

- `make_full_state_change_event` builds a `RawStateChangeEvent` from pre-built state dicts rather than raw values. Also available via the Tier 2 re-export at `hassette.test_utils.make_full_state_change_event`.
- `create_component_loaded_event` builds a [`ComponentLoadedEvent`][hassette.events.hass.hass.ComponentLoadedEvent] for a given component name.
- `create_service_registered_event` builds a [`ServiceRegisteredEvent`][hassette.events.hass.hass.ServiceRegisteredEvent] for a given domain and service.

`create_hassette_stub` is available from `hassette.test_utils._internal` and builds a `MagicMock` stub for web and API tests.

These are stable in practice but are not part of the documented public API. They may change without notice.

## Next Steps

- [Testing overview](index.md): harness basics and test patterns
- [Time Control](time-control.md): freeze and advance time for scheduler tests
- [Concurrency & pytest-xdist](concurrency.md): concurrency locks and xdist isolation
