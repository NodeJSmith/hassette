# Factories & Internals

## Event Factories

`hassette.test_utils` exports six factory functions for building raw event and state dictionaries. These are useful when you need to construct events manually — for example, to pre-populate state before a test or to pass custom event data to lower-level bus methods.

```python
--8<-- "pages/testing/snippets/testing_factory_imports.py"
```

### `create_state_change_event`

Creates a `state_changed` event object suitable for sending through the bus directly.

```python
--8<-- "pages/testing/snippets/testing_create_state_change_event.py"
```

All parameters except `entity_id`, `old_value`, and `new_value` are optional.

### `create_call_service_event`

Creates a `call_service` event object.

```python
--8<-- "pages/testing/snippets/testing_create_call_service_event.py"
```

## State Factories

### `make_state_dict`

Creates a raw state dictionary in Home Assistant format. The harness uses this internally; you'll use it when constructing test data directly.

```python
--8<-- "pages/testing/snippets/testing_make_state_dict.py"
```

All parameters except `entity_id` and `state` are optional. Timestamps default to now.

### `make_light_state_dict`

Shorthand for light entity state dicts with common attributes.

```python
--8<-- "pages/testing/snippets/testing_make_light_state_dict.py"
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `entity_id` | `"light.kitchen"` | Light entity ID. |
| `state` | `"on"` | `"on"` or `"off"`. |
| `brightness` | `None` | Brightness 0–255. Omitted if not set. |
| `color_temp` | `None` | Color temperature in mireds. Omitted if not set. |
| `**kwargs` | — | Extra attributes or state dict fields (`last_changed`, `last_updated`, `context`). |

### `make_sensor_state_dict`

Shorthand for sensor entity state dicts.

```python
--8<-- "pages/testing/snippets/testing_make_sensor_state_dict.py"
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `entity_id` | `"sensor.temperature"` | Sensor entity ID. |
| `state` | `"25.5"` | Sensor value as a string. |
| `unit_of_measurement` | `None` | Unit string, e.g. `"°C"`, `"%"`. |
| `device_class` | `None` | HA device class, e.g. `"temperature"`. |

### `make_switch_state_dict`

Shorthand for switch entity state dicts.

```python
--8<-- "pages/testing/snippets/testing_make_switch_state_dict.py"
```

## `make_test_config`

`AppTestHarness` creates a minimal `HassetteConfig` internally. If you need a `HassetteConfig` without the full harness — for example, to test configuration parsing logic directly — use `make_test_config`:

```python
--8<-- "pages/testing/snippets/testing_make_test_config.py"
```

`make_test_config` reads nothing from TOML files, env vars, or the CLI — only the values you pass are used. Pydantic validation still runs.

`data_dir` is **required** — pass a `tmp_path` fixture value in pytest. All other fields have test-appropriate defaults:

| Field | Default |
|-------|---------|
| `data_dir` | **required — no default** |
| `token` | `"test-token"` |
| `base_url` | `"http://test.invalid:8123"` |
| `disable_state_proxy_polling` | `True` |
| `autodetect_apps` | `False` |
| `run_web_api` | `False` |
| `run_app_precheck` | `False` |

Pass `**overrides` to replace any of the defaults.

## RecordingApi Coverage Boundary

`RecordingApi` stubs write methods and delegates state reads to the seeded `StateProxy`. Anything that requires a live HA connection raises `NotImplementedError`:

- `get_state_raw()`
- `get_states_raw()`
- `get_state_value()`
- `get_state_value_typed()`
- `get_attribute()`
- `get_history()`
- `render_template()`
- `ws_send_and_wait()`
- `ws_send_json()`
- `rest_request()`
- `delete_entity()`

For these methods, seed the data you need via `harness.set_state()` and use the read methods that delegate to `StateProxy`: `get_state()`, `get_states()`, `get_entity()`, `get_entity_or_none()`, `entity_exists()`, `get_state_or_none()`.

!!! note "`api.sync` is a recording facade"
    `harness.api_recorder.sync` is a `_RecordingSyncFacade` — a recording proxy, not a `Mock`. Write calls made via `self.api.sync.*` appear in the same `api_recorder.calls` list as their async counterparts and can be asserted with the same API:

    ```python
    --8<-- "pages/testing/snippets/testing_sync_facade.py"
    ```

    Methods not covered by the facade raise `NotImplementedError` rather than silently succeeding.

!!! warning "Needs human review"
    The list of `NotImplementedError` methods above was accurate at the time of writing but may not reflect future changes to `RecordingApi`. If you find a method missing from this list, check `src/hassette/test_utils/recording_api.py` directly and update this page.

## Tier 2 Re-exports

`hassette.test_utils` also re-exports a set of Tier 2 symbols — internal utilities used by Hassette's own test suite — for backward compatibility. These are **not in `__all__`** and may change without notice. They are not documented here. Use Tier 1 APIs (`AppTestHarness`, `RecordingApi`, the factory functions, `make_test_config`, and the drain exception types) for all end-user testing.

## What's Next

- [Quick Start](index.md) — Back to the harness basics
- [Time Control](time-control.md) — Freeze and advance time for scheduler tests
- [Concurrency & pytest-xdist](concurrency.md) — Understand the concurrency locks
