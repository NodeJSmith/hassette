# Testing

This page covers how to test your Hassette apps during and after migration from AppDaemon.

## Overview

Testing AppDaemon apps is hard. There is no official test harness, and apps depend heavily on the `Hass` runtime — mocking it is fragile and often ends up testing the mock rather than your code.

Hassette ships with `hassette.test_utils`, a first-class test harness that lets you test automations in isolation, without a running Home Assistant instance. You can simulate state changes, inspect API calls your app makes, and control time for scheduler tests.

## Installation

`hassette.test_utils` is part of the main `hassette` package — no extra install required. You need a test runner:

```bash
pip install pytest pytest-asyncio
```

Add this to your `pyproject.toml` to configure pytest-asyncio:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

With `asyncio_mode = "auto"`, any `async def test_*` function is automatically treated as an async test — no `@pytest.mark.asyncio` decorator required.

## Basic Test Structure

Here is a complete test for an app that turns on a light when motion is detected:

```python
--8<-- "pages/migration/snippets/testing_hassette_example.py"
```

The pattern is:

1. Open an `AppTestHarness` as an async context manager — this initializes your app and tears it down when the block exits
2. Seed state for entities your app reads
3. Simulate the event that should trigger your app
4. Assert on `harness.api_recorder` to verify the expected API calls were made

## The AppTestHarness

`AppTestHarness` accepts three arguments:

| Parameter | Description |
|-----------|-------------|
| `app_cls` | Your `App` subclass to test |
| `config` | Dict of config values — keys must match your `AppConfig` subclass fields |
| `tmp_path` | Optional directory for Hassette data files; created and cleaned up automatically if omitted |

Inside the `async with` block:

| Property | Type | Description |
|----------|------|-------------|
| `harness.app` | `App` | The fully initialized app instance |
| `harness.bus` | `Bus` | The test bus your app registered handlers on |
| `harness.scheduler` | `Scheduler` | The test scheduler your app registered jobs on |
| `harness.api_recorder` | `RecordingApi` | Records every API call your app makes |
| `harness.states` | `StateManager` | The state manager your app reads from |

## Seeding State

Before simulating events, seed entity state using `set_state()`:

```python
await harness.set_state("binary_sensor.motion", "off")
await harness.set_state("light.kitchen", "off", brightness=0, friendly_name="Kitchen")
```

!!! warning "`set_state()` does not fire bus events"
    `set_state()` is for pre-test setup only. It writes directly to the state proxy without publishing a `state_changed` event. To simulate a state transition, use `simulate_state_change()`.

## Simulating Events

Use the simulate methods to trigger your app's handlers:

```python
# Simulate a state change
await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")

# Simulate a service call
await harness.simulate_call_service("input_button", "press", entity_id="input_button.test")
```

Each simulate method waits for all triggered handlers to finish before returning.

## Asserting on API Calls

`harness.api_recorder` records every API call your app makes. Use its assertion helpers:

```python
# Assert a specific call was made
harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen")

# Assert a call was NOT made
harness.api_recorder.assert_not_called("turn_off")

# Inspect all recorded calls
calls = harness.api_recorder.get_calls("call_service")
```

## Event Factories

Hassette provides factory functions for creating test events:

```python
from hassette.test_utils import (
    create_state_change_event,
    create_call_service_event,
    make_light_state_dict,
    make_sensor_state_dict,
    make_switch_state_dict,
)

# Create a state change event
event = create_state_change_event(
    "binary_sensor.motion",
    old="off",
    new="on",
)

# Create a service call event
event = create_call_service_event(
    domain="light",
    service="turn_on",
    service_data={"entity_id": "light.kitchen", "brightness": 200},
)

# Create a light state dict for seeding
state_dict = make_light_state_dict(brightness=200, friendly_name="Kitchen")
```

## Scheduler Testing

The test scheduler supports time control. Freeze time to a known point, then advance it to trigger scheduled jobs:

```python
from whenever import Instant

async with AppTestHarness(MyApp, config={}) as harness:
    # Freeze to a known instant (takes Instant or ZonedDateTime — not a string)
    harness.freeze_time(Instant.from_utc(2025, 1, 1, 7, 0, 0))
    # Advance time (synchronous — no await)
    harness.advance_time(seconds=1800)
    # Trigger any jobs that became due
    await harness.trigger_due_jobs()
    harness.api_recorder.assert_called("turn_on")
```

See [Time Control](../testing/time-control.md) for the full time-control API.

## See Also

- [Testing Your Apps](../testing/index.md) — full test harness reference
- [Time Control](../testing/time-control.md) — freezing and advancing time in tests
- [Concurrency & pytest-xdist](../testing/concurrency.md) — parallel test execution
- [Factories & Internals](../testing/factories.md) — event factories and advanced patterns
