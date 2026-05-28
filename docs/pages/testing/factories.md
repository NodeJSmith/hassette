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

## `make_mock_hassette`

`make_mock_hassette()` builds a sealed `AsyncMock` hassette with real, Pydantic-validated configuration. It is the standard pattern for unit tests that need a hassette mock with validated config — it replaces the pattern of manually setting `.config.*` fields on a raw `AsyncMock`.

```python
--8<-- "pages/testing/snippets/factories_mock_hassette.py"
```

All `HassetteConfig` fields can be passed as keyword arguments; Pydantic validates them at construction time. Passing an unrecognised field name or an out-of-range value raises `pydantic.ValidationError` immediately.

Non-config attributes (`ready_event`, `shutdown_event`, `session_id`, `_scheduler_service`, `_bus_service`, `wait_for_ready`, `children`, etc.) are wired automatically. By default the mock is `seal()`-ed — accessing an attribute not set by the factory raises `AttributeError`. Pass `sealed=False` to add extra attributes after construction.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `data_dir` | `tempfile.mkdtemp()` | Directory for Hassette data files. Pass `tmp_path` in integration tests for isolation. |
| `set_ready` | `True` | Pre-set `ready_event` so `wait_for_ready()` resolves immediately. |
| `set_loop` | `True` | Wire `loop` to `asyncio.get_running_loop()`. Pass `False` for session-scoped fixtures that run outside an event loop. |
| `sealed` | `True` | Call `seal()` after wiring; accessing unlisted attributes raises `AttributeError`. |
| `**config_overrides` | — | Any `HassetteConfig` field. Merged on top of test-appropriate defaults. |

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
| `app` | `{"autodetect": False}` |
| `web_api` | `{"run": False}` |
| `run_app_precheck` | `False` |

Pass `**overrides` to replace any of the defaults.

## RecordingApi Coverage Boundary

`RecordingApi` stubs write methods and delegates state reads to the seeded `StateProxy`. Anything that requires a live HA connection raises `NotImplementedError`.

**Explicit stubs** (raise `NotImplementedError` directly):

- `get_state_raw()`
- `get_states_raw()`
- `get_history()`
- `render_template()`
- `ws_send_and_wait()`
- `ws_send_json()`
- `rest_request()`
- `delete_entity()`

**Redirected via `__getattr__`** (raise `NotImplementedError` with a message pointing to `get_state()`):

- `get_state_value()`
- `get_state_value_typed()`
- `get_attribute()`

Any other public method not explicitly defined on `RecordingApi` also falls through to `__getattr__` and raises `NotImplementedError`.

For all of the above, seed the data you need via `harness.set_state()` and use the read methods that delegate to `StateProxy`: `get_state()`, `get_states()`, `get_entity()`, `get_entity_or_none()`, `entity_exists()`, `get_state_or_none()`.

!!! note "`api.sync` is a recording facade"
    `harness.api_recorder.sync` is a `_RecordingSyncFacade` — a recording proxy, not a `Mock`. Write calls made via `self.api.sync.*` appear in the same `api_recorder.calls` list as their async counterparts and can be asserted with the same API:

    ```python
    --8<-- "pages/testing/snippets/testing_sync_facade.py"
    ```

    Methods not covered by the facade raise `NotImplementedError` rather than silently succeeding.

!!! note
    The list of `NotImplementedError` methods above reflects `RecordingApi` at the time this page was written. If you encounter an unexpected `NotImplementedError`, check `src/hassette/test_utils/recording_api.py` for the current state.

## Tier 2 Re-exports

`hassette.test_utils` also re-exports a set of Tier 2 symbols — internal utilities used by Hassette's own test suite — for backward compatibility. These are **not in `__all__`** and may change without notice. They are not documented here. Use Tier 1 APIs (`AppTestHarness`, `RecordingApi`, the factory functions, `make_test_config`, and the drain exception types) for all end-user testing.

## Next Steps

- **[Quick Start](index.md)**: Back to the harness basics
- **[Time Control](time-control.md)**: Freeze and advance time for scheduler tests
- **[Concurrency & pytest-xdist](concurrency.md)**: Understand the concurrency locks
