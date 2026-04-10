# Testing Your Apps

Hassette ships with `hassette.test_utils` — a set of utilities for testing your automations in isolation, without a running Home Assistant instance. You can simulate state changes, inspect API calls your app makes, and control time for scheduler tests.

The core idea: `AppTestHarness` runs your app against a test-grade Hassette environment with a `RecordingApi` in place of a live HA connection. When your app calls `self.api.turn_on()`, `self.api.call_service()`, or any other API method, `RecordingApi` records those calls instead of contacting Home Assistant — you then assert on the recorder via `harness.api_recorder`.

## Installation

`hassette.test_utils` is part of the main `hassette` package — no extra install required. You only need to add your test runner:

```bash
pip install pytest pytest-asyncio
```

Or with uv:

```bash
uv add --dev pytest pytest-asyncio
```

Add this to your `pyproject.toml` to configure pytest-asyncio:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

With `asyncio_mode = "auto"`, any `async def test_*` function is automatically treated as an async test — no `@pytest.mark.asyncio` decorator required. If you skip this config, your async tests will silently succeed **without actually running** — a silent false-green failure mode. The examples on this page assume `asyncio_mode = "auto"` is set.

!!! note "`whenever` is installed automatically"
    Time control examples on this page import from [`whenever`](https://whenever.readthedocs.io/) — Hassette's date/time library. It's a direct dependency of `hassette`, so it's installed automatically. No separate install needed.

## Quick Start

Here's a complete test for an app that turns on a light when motion is detected:

```python
from hassette.test_utils import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_light_turns_on_when_motion_detected():
    async with AppTestHarness(
        MotionLights,
        config={"motion_entity": "binary_sensor.hallway", "light_entity": "light.hallway"},
    ) as harness:
        await harness.simulate_state_change(
            "binary_sensor.hallway", old_value="off", new_value="on"
        )
        harness.api_recorder.assert_called(
            "turn_on",
            entity_id="light.hallway",
            domain="light",
        )
```

After `async with`, the app is fully initialized and ready to receive events. The harness tears everything down cleanly when the `async with` block exits.

## The Test Harness

`AppTestHarness` wires your app class into a test-grade Hassette environment with a `RecordingApi` instead of a live HA connection.

### Constructor

```python
AppTestHarness(
    app_cls: type[App],
    config: dict[str, Any],
    *,
    tmp_path: Path | None = None,
)
```

| Parameter | Description |
|-----------|-------------|
| `app_cls` | Your `App` subclass to test. |
| `config` | Dict of config values. Keys must match the fields defined on your app's `AppConfig` subclass (see [App Configuration](../core-concepts/apps/configuration.md)). Invalid or missing fields raise `AppConfigurationError` during harness setup. |
| `tmp_path` | Optional directory for Hassette data files. Created and cleaned up automatically if omitted. In pytest, pass the built-in `tmp_path` fixture to share a directory across multiple harnesses in one test. |

### Properties

Once inside the `async with` block, the harness exposes:

| Property | Type | Description |
|----------|------|-------------|
| `harness.app` | `App` | The fully initialized app instance. |
| `harness.bus` | `Bus` | The test bus your app registered handlers on. |
| `harness.scheduler` | `Scheduler` | The test scheduler your app registered jobs on. |
| `harness.api_recorder` | `RecordingApi` | Records every API call your app makes. Use this for assertions. |
| `harness.states` | `StateManager` | The state manager your app reads from. |

## State Seeding

Before simulating events, seed the state of any entities your app reads. Use `set_state()` for a single entity or `set_states()` for multiple at once.

```python
async with AppTestHarness(ThermostatApp, config={...}) as harness:
    # Seed a single entity
    await harness.set_state("sensor.temperature", "20.5", unit_of_measurement="°C")

    # Seed multiple entities at once
    await harness.set_states({
        "sensor.temperature": ("20.5", {"unit_of_measurement": "°C"}),
        "sensor.humidity": "55",
        "climate.living_room": "heat",
    })
```

`set_states()` accepts either a plain state string or a `(state, attributes)` tuple.

!!! warning "`set_state()` does not fire bus events"
    `set_state()` is for pre-test setup only. It writes directly to the state proxy without publishing a `state_changed` event, so **no handlers will fire**. Do not use `set_state()` mid-test to simulate a state transition — use [`simulate_state_change()`](#simulating-events) instead.

    A second hazard: calling `set_state()` *after* a `simulate_state_change()` for the same entity will silently overwrite the simulated state with the seeded value, which can make subsequent reads return wrong values. Seed first, simulate second.

## Simulating Events

If your handler reads entity state during handling (e.g., `self.states.light.get("light.kitchen")`), seed it first with [`harness.set_state()`](#state-seeding). Simulating an event does not update the state proxy automatically unless your handler writes back via the API.

### State changes

`simulate_state_change()` publishes a `state_changed` event through the bus and waits for all triggered handlers to finish before returning.

```python
await harness.simulate_state_change(
    "binary_sensor.motion",
    old_value="off",
    new_value="on",
)

# With attributes
await harness.simulate_state_change(
    "sensor.temperature",
    old_value="20.0",
    new_value="21.5",
    old_attrs={"unit_of_measurement": "°C"},
    new_attrs={"unit_of_measurement": "°C"},
)
```

### Attribute changes

`simulate_attribute_change()` simulates a change to a single attribute while keeping the state value the same.

```python
await harness.simulate_attribute_change(
    "light.kitchen",
    "brightness",
    old_value=128,
    new_value=255,
)
```

The generated event carries the entity's current cached state for the `state` field. If you haven't seeded the entity with `set_state()` first, that field defaults to `"unknown"` — which silently breaks any state-conditional predicates on the same entity. You can pass an explicit `state=` to avoid this:

```python
await harness.set_state("light.kitchen", "on", brightness=128)
# ...or pass state= explicitly for a one-off:
await harness.simulate_attribute_change(
    "light.kitchen",
    "brightness",
    old_value=128,
    new_value=255,
    state="on",  # avoids the "unknown" fallback
)
```

!!! warning "`simulate_attribute_change` also fires state-change handlers"
    This method delegates to `simulate_state_change` under the hood, which matches Home Assistant's real behavior — `state_changed` events fire even when only attributes change. If your app registers both `on_state_change` and `on_attribute_change` for the same entity, both handlers will fire:

    ```python
    # App registers two handlers for the same entity
    self.bus.on_state_change("sensor.temp", handler=self.on_temp_state)
    self.bus.on_attribute_change("sensor.temp", "temperature", handler=self.on_temp_attr)

    # simulate_attribute_change fires BOTH handlers.
    await harness.simulate_attribute_change("sensor.temp", "temperature", old_value=20, new_value=21)

    # Account for this in count assertions
    harness.api_recorder.assert_call_count("call_service", 2)  # not 1
    ```

    Use `harness.api_recorder.reset()` between simulate calls, or `get_calls()` for targeted inspection, to isolate which handler made which API call.

### Service call events

`simulate_call_service()` publishes a `call_service` event, useful for apps that listen for HA service calls.

```python
await harness.simulate_call_service(
    "light",
    "turn_on",
    entity_id="light.kitchen",
    brightness=200,
)
```

### Timeouts and slow handlers

All three simulate methods wait for dispatched handlers to finish before returning. The default timeout is **2 seconds**. Override it with the `timeout=` parameter:

```python
await harness.simulate_state_change(
    "sensor.slow_device",
    old_value="off",
    new_value="on",
    timeout=5.0,
)
```

!!! note "Task chains drain to completion — and surface failures via `DrainFailure`"
    The drain is iterative: after the bus dispatch queue clears, any tasks spawned by `self.task_bucket.spawn(...)` inside a handler are awaited in turn, and tasks those tasks spawn are awaited too — to arbitrary depth. `simulate_*` does not return until the full chain is settled.

    Drain failures are rooted at a single base class — `DrainFailure` — with two concrete subclasses:

    * `DrainError` — one or more spawned handler tasks raised a non-cancellation exception.
    * `DrainTimeout` — the drain did not reach quiescence within the configured timeout.

    Catch either outcome uniformly with a single `except DrainFailure:` clause, or branch on the concrete type when you need to react differently:

    ```python
    from hassette.test_utils import AppTestHarness, DrainError, DrainFailure, DrainTimeout

    try:
        await harness.simulate_state_change(
            "binary_sensor.motion", old_value="off", new_value="on"
        )
    except DrainError as e:
        # e.task_exceptions is a list of (task_name, exception) pairs
        raise
    except DrainTimeout:
        # diagnostic message includes pending task names and a debounce hint
        raise
    ```

    `DrainTimeout` does **not** inherit from `TimeoutError` — catch `DrainTimeout` (or `DrainFailure`) instead. The diagnostic message includes the names of the pending tasks and a hint to check for debounced handlers.

## Asserting API Calls

`harness.api_recorder` records every call your app makes to `self.api`. Use it to assert that your app called the right services.

### `assert_called`

Passes if the method was called at least once with kwargs that match **all** specified values (partial matching — additional kwargs in the recorded call are allowed).

```python
# Assert turn_on was called for a specific entity
harness.api_recorder.assert_called(
    "turn_on",
    entity_id="light.kitchen",
    domain="light",
)

# Assert fire_event was called with a specific event type
harness.api_recorder.assert_called("fire_event", event_type="my_custom_event")

# Assert call_service was called directly (for services without a named wrapper)
harness.api_recorder.assert_called(
    "call_service",
    domain="light",
    service="set_color_temp",
    target={"entity_id": "light.kitchen"},
)
```

!!! note "`turn_on`, `turn_off`, and `toggle_service` record under their own names"
    These convenience methods record calls using their own method name — not `call_service`. Assert them directly:

    ```python
    # Your app calls: await self.api.turn_on("light.kitchen", domain="light")
    harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen", domain="light")

    # Your app calls: await self.api.turn_off("light.kitchen", domain="light")
    harness.api_recorder.assert_called("turn_off", entity_id="light.kitchen", domain="light")
    ```

    Use `assert_called("call_service", ...)` only for direct `self.api.call_service(...)` calls.

### `assert_not_called`

```python
harness.api_recorder.assert_not_called("call_service")
```

### `assert_call_count`

```python
harness.api_recorder.assert_call_count("call_service", 2)
```

### `get_calls`

Returns a list of `ApiCall` records, optionally filtered by method name. Each `ApiCall` has `method`, `args`, and `kwargs` attributes.

```python
calls = harness.api_recorder.get_calls("call_service")
for call in calls:
    print(call.kwargs)  # e.g. {"domain": "light", "service": "turn_on", ...}
```

### `reset`

Clears all recorded calls. Useful when you want to assert on calls made after a specific point in your test.

```python
await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")
harness.api_recorder.reset()  # ignore calls from the above simulate

await harness.simulate_state_change("binary_sensor.motion", old_value="on", new_value="off")
harness.api_recorder.assert_called("turn_off", entity_id="light.hallway", domain="light")
```

## Time Control

Test scheduler-driven behavior by freezing time and advancing it manually.

The canonical sequence for any time-control test is:

```python
from whenever import Instant

from hassette.test_utils import AppTestHarness

from my_apps.reminder import ReminderApp


async def test_reminder_fires_after_one_hour():
    async with AppTestHarness(ReminderApp, config={}) as harness:
        # 1. Freeze time at a known point
        start = Instant.from_utc(2024, 1, 15, 9, 0, 0)  # 2024-01-15 09:00 UTC
        harness.freeze_time(start)

        # 2. Schedule the job (app registers it in on_initialize, but you
        #    can also trigger registration logic via simulate_* here)

        # 3. Advance the frozen clock
        harness.advance_time(hours=1)

        # 4. Fire any jobs whose due time is now <= frozen clock
        count = await harness.trigger_due_jobs()
        assert count == 1

        # 5. Assert your app made the expected API call
        harness.api_recorder.assert_called("fire_event", event_type="reminder_fired")
```

### `freeze_time(instant)`

Freezes `hassette.utils.date_utils.now` at the given time. Accepts an `Instant` or `ZonedDateTime` from the [`whenever`](https://whenever.readthedocs.io/) library. No stdlib `datetime` — the scheduler uses `whenever` types throughout.

```python
from whenever import Instant, ZonedDateTime

# From a UTC instant (most portable)
harness.freeze_time(Instant.from_utc(2024, 6, 1, 8, 0, 0))

# From a ZonedDateTime (when local time matters)
harness.freeze_time(ZonedDateTime(2024, 6, 1, 8, 0, 0, tz="America/Chicago"))
```

`freeze_time` is idempotent — calling it again replaces the frozen time. The clock is automatically unfrozen when the `async with` block exits.

### `advance_time`

Advances the frozen clock by the given delta.

```python
harness.advance_time(seconds=30)
harness.advance_time(minutes=5)
harness.advance_time(hours=1)
harness.advance_time(hours=1, minutes=30)  # combined
```

!!! warning "`advance_time` alone has no effect on scheduled jobs"
    Moving the clock forward does not trigger any jobs. You must call `trigger_due_jobs()` explicitly after advancing time — otherwise jobs accumulate silently and your assertions will fail.

### `trigger_due_jobs`

Fires all jobs whose scheduled time is at or before the current frozen time. Returns the number of jobs dispatched.

```python
count = await harness.trigger_due_jobs()
assert count == 1
```

Jobs re-enqueued during dispatch (repeating jobs) are not re-triggered in the same call — only the snapshot of due jobs at the moment of the call is processed. This prevents infinite loops when the clock is frozen.

## Event Factories

`hassette.test_utils` exports six factory functions for building raw event and state dictionaries. These are useful when you need to construct events manually — for example, to pre-populate state before a test or to pass custom event data to lower-level bus methods.

```python
from hassette.test_utils import (
    create_call_service_event,
    create_state_change_event,
    make_light_state_dict,
    make_sensor_state_dict,
    make_state_dict,
    make_switch_state_dict,
)
```

### `create_state_change_event`

Creates a `state_changed` event object suitable for sending through the bus directly.

```python
event = create_state_change_event(
    entity_id="binary_sensor.motion",
    old_value="off",
    new_value="on",
    old_attrs={"device_class": "motion"},
    new_attrs={"device_class": "motion"},
)
```

All parameters except `entity_id`, `old_value`, and `new_value` are optional.

### `create_call_service_event`

Creates a `call_service` event object.

```python
event = create_call_service_event(
    domain="light",
    service="turn_on",
    service_data={"entity_id": "light.kitchen", "brightness": 200},
)
```

### `make_state_dict`

Creates a raw state dictionary in Home Assistant format. The harness uses this internally; you'll use it when constructing test data directly.

```python
state = make_state_dict(
    "sensor.temperature",
    "21.5",
    attributes={"unit_of_measurement": "°C", "device_class": "temperature"},
)
```

All parameters except `entity_id` and `state` are optional. Timestamps default to now.

### `make_light_state_dict`

Shorthand for light entity state dicts with common attributes.

```python
state = make_light_state_dict(
    entity_id="light.kitchen",
    state="on",
    brightness=200,
    color_temp=370,
)
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
state = make_sensor_state_dict(
    entity_id="sensor.temperature",
    state="21.5",
    unit_of_measurement="°C",
    device_class="temperature",
)
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
state = make_switch_state_dict(entity_id="switch.outlet", state="off")
```

## Configuration Errors

If the `config` dict you pass to `AppTestHarness` fails validation against your app's `AppConfig` class, the harness raises `AppConfigurationError` during setup — the `async with` body is never entered, so your test code inside the block does not run.

```python
from hassette.test_utils import AppConfigurationError

with pytest.raises(AppConfigurationError) as exc_info:
    async with AppTestHarness(MotionLights, config={}) as harness:
        pass

# The error message includes the field name and validation failure reason
print(exc_info.value)
# AppConfigurationError for MotionLights: 1 validation error — field 'motion_entity': Field required
```

`AppConfigurationError` has two attributes:
- `app_cls` — the `App` class whose config failed.
- `original_error` — the underlying `pydantic.ValidationError` with full field-level detail.

Read the error message to find which field is missing or invalid, then fix the `config` dict in your test.

## Advanced: `make_test_config`

`AppTestHarness` creates a minimal `HassetteConfig` internally. If you need a `HassetteConfig` without the full harness — for example, to test configuration parsing logic directly — use `make_test_config`:

```python
from hassette.test_utils import make_test_config


def test_config_defaults(tmp_path):
    config = make_test_config(data_dir=tmp_path)
    assert config.run_web_api is False

    # Override specific fields
    config = make_test_config(data_dir=tmp_path, base_url="http://192.168.1.100:8123")
    assert config.base_url == "http://192.168.1.100:8123"
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

Pass `**overrides` to replace any of the defaults:

```python
config = make_test_config(data_dir=tmp_path, token="my-real-token", run_web_api=True)
```

## Limitations and Troubleshooting

### RecordingApi coverage boundary

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
    # Your app calls: self.api.sync.turn_on("light.kitchen", domain="light")
    harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen", domain="light")
    ```

    Methods not covered by the facade raise `NotImplementedError` rather than silently succeeding.

### Concurrency

The harness has two independent isolation mechanisms. Understanding which applies when prevents confusing deadlocks.

#### Same-class concurrency (always applies)

`AppTestHarness` holds a **per-App-class `asyncio.Lock`** for the entire `async with` block. This applies to every harness, whether or not you call `freeze_time`.

- Two harnesses for the **same App class** cannot run concurrently in the same event loop. Do not use `asyncio.gather()` with multiple harnesses that share a class — the second one will deadlock waiting for the first's lock.
- Two harnesses for **different App classes** can run concurrently in the same event loop without conflict.

#### Time-control concurrency (`freeze_time` only)

`freeze_time` additionally uses a **process-global non-reentrant lock**. Only one harness at a time may hold the time lock in a process, regardless of which App class it tests.

- Sequential tests in the same worker are safe — the lock is released when the `async with` block exits cleanly.
- If two harnesses compete for the time lock, the second one raises `RuntimeError: freeze_time is already held by another harness`.

#### Parallel test suites (pytest-xdist)

If you run tests with `pytest-xdist` (`pytest -n auto` or `pytest -n <N>`), two parallel workers can each try to acquire the time lock in their own processes — but because the lock is process-global, each worker's lock is independent. The problem is that two time-control tests scheduled to *different* workers can race on which one actually sees frozen time for your assertions.

Mark all tests that call `freeze_time` with the same `xdist_group` so they run on the same worker sequentially:

```python
@pytest.mark.xdist_group("time_control")
async def test_reminder_fires_after_one_hour():
    async with AppTestHarness(ReminderApp, config={}) as harness:
        harness.freeze_time(Instant.from_utc(2024, 1, 15, 9, 0, 0))
        ...
```

If you run pytest sequentially (no `-n` flag), you do not need this marker.

### Harness startup failures

If the harness raises `TimeoutError: Timed out waiting for <YourApp> RUNNING`, the app's `on_initialize()` either raised an exception or took longer than 5 seconds to complete.

!!! info "This is a bare `TimeoutError`, not `DrainTimeout`"
    Harness startup timeouts are distinct from drain timeouts. The startup wait still raises a plain `TimeoutError` — catch `TimeoutError` here, not `DrainTimeout` or `DrainFailure`. Drain-related failures only happen once the harness is running and you call `simulate_*`.

Check test output for earlier log lines — exceptions raised during `on_initialize()` are caught and logged at `WARNING` level during teardown, so the `TimeoutError` is the surface symptom, not the root cause.

Common triggers:
- A required config field is present but its value causes a runtime error during initialization (distinct from a missing-field `AppConfigurationError` which fires before entry).
- `on_initialize()` awaits something that never resolves, such as an external call that isn't mocked.
- An `await` inside `on_initialize()` raises an exception that propagates out.

## Next Steps

- [Bus](../core-concepts/bus/index.md) — Learn how to register handlers in your app
- [Scheduler](../core-concepts/scheduler/index.md) — Learn how to register scheduled jobs
- [API](../core-concepts/api/index.md) — The `self.api` methods your app calls
