# Testing Your Apps

Hassette ships with `hassette.test_utils` — a set of utilities for testing your automations in isolation, without a running Home Assistant instance. You can simulate state changes, inspect API calls your app makes, and control time for scheduler tests.

The core idea: `AppTestHarness` runs your app against a test-grade Hassette environment with a `RecordingApi` in place of a live HA connection. When your app calls `self.api.turn_on()`, `self.api.call_service()`, or any other API method, `RecordingApi` records those calls instead of contacting Home Assistant — you then assert on the recorder via `harness.api_recorder`.

## Installation

`hassette.test_utils` is part of the main `hassette` package — no extra install required. You only need to add your test runner:

```bash
--8<-- "pages/testing/snippets/testing_install_pip.sh"
```

Or with uv:

```bash
--8<-- "pages/testing/snippets/testing_install_uv.sh"
```

Add this to your `pyproject.toml` to configure pytest-asyncio:

```toml
--8<-- "pages/testing/snippets/testing_asyncio_mode.toml"
```

With `asyncio_mode = "auto"`, any `async def test_*` function is automatically treated as an async test — no `@pytest.mark.asyncio` decorator required. If you skip this config, your async tests will silently succeed **without actually running** — a silent false-green failure mode. The examples on this page assume `asyncio_mode = "auto"` is set.

## Quick Start

Here's a complete test for an app that turns on a light when motion is detected:

!!! note "Replace the placeholders with your own app"
    Replace `MotionLights` with your app class and `motion_lights` with your module path. The config keys (`motion_entity`, `light_entity`) should match the fields on your app's `AppConfig` subclass.

```python
--8<-- "pages/testing/snippets/testing_quick_start.py"
```

After `async with`, the app is fully initialized and ready to receive events. The harness tears everything down cleanly when the `async with` block exits.

## The Test Harness

`AppTestHarness` wires your app class into a test-grade Hassette environment with a `RecordingApi` instead of a live HA connection.

### Constructor

```python
--8<-- "pages/testing/snippets/testing_constructor.py"
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
--8<-- "pages/testing/snippets/testing_state_seeding.py"
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
--8<-- "pages/testing/snippets/testing_simulate_state_change.py"
```

### Attribute changes

`simulate_attribute_change()` simulates a change to a single attribute while keeping the state value the same.

```python
--8<-- "pages/testing/snippets/testing_simulate_attribute_change.py"
```

The generated event carries the entity's current cached state for the `state` field. If you haven't seeded the entity with `set_state()` first, that field defaults to `"unknown"` — which silently breaks any state-conditional predicates on the same entity. You can pass an explicit `state=` to avoid this, as shown above.

!!! warning "`simulate_attribute_change` can also fire state-change handlers"
    This method delegates to `simulate_state_change` under the hood. With the default `changed=True`, state-change handlers do **not** fire (the state value is unchanged). But if your app registers `on_state_change` with `changed=False`, that handler **will** fire — matching HA's real behavior where `state_changed` events fire even when only attributes change:

    ```python
    --8<-- "pages/testing/snippets/testing_attribute_change_both_handlers.py"
    ```

    Use `harness.api_recorder.reset()` between simulate calls, or `get_calls()` for targeted inspection, to isolate which handler made which API call.

### Service call events

`simulate_call_service()` publishes a `call_service` event, useful for apps that listen for HA service calls.

```python
--8<-- "pages/testing/snippets/testing_simulate_call_service.py"
```

### Timeouts and slow handlers

All three simulate methods wait for dispatched handlers to finish before returning. The default timeout is **2 seconds**. Override it with the `timeout=` parameter:

```python
--8<-- "pages/testing/snippets/testing_simulate_timeout.py"
```

!!! note "Task chains drain to completion"
    The drain is iterative: after the bus dispatch queue clears, any tasks spawned by `self.task_bucket.spawn(...)` inside a handler are awaited in turn, to arbitrary depth. `simulate_*` does not return until the full chain is settled. If a task raises or the drain times out, a `DrainFailure` subclass is raised — see [DrainFailure Exception Hierarchy](concurrency.md#drainfailure-exception-hierarchy) for the full exception hierarchy and catch patterns.

### Typed dependency injection in handlers

Hassette handlers support typed dependency injection via `D.*` annotations. These work seamlessly with `simulate_*` — the harness dispatches the same event objects that production code receives, so DI resolution runs identically.

**State change with `D.StateNew`** — extract a typed state model from the event:

```python
--8<-- "pages/testing/snippets/testing_di_state_change.py"
```

**Service call with `D.Domain`** — extract the service domain from the event:

```python
--8<-- "pages/testing/snippets/testing_di_call_service.py"
```

### Hassette service events

`simulate_hassette_service_status()` and its convenience wrappers (`simulate_hassette_service_failed`, `simulate_hassette_service_crashed`, `simulate_hassette_service_started`) let you test how your app responds to internal service lifecycle changes.

```python
--8<-- "pages/testing/snippets/testing_simulate_service_failure.py"
```

## Asserting API Calls

`harness.api_recorder` records every call your app makes to `self.api`. Use it to assert that your app called the right services.

### `assert_called`

Passes if the method was called at least once with kwargs that match **all** specified values (partial matching — additional kwargs in the recorded call are allowed).

```python
--8<-- "pages/testing/snippets/testing_assert_called.py"
```

!!! note "`turn_on`, `turn_off`, and `toggle_service` record under their own names"
    These convenience methods record calls using their own method name — not `call_service`. Assert them directly:

    ```python
    --8<-- "pages/testing/snippets/testing_assert_turn_on_off.py"
    ```

    Use `assert_called("call_service", ...)` only for direct `self.api.call_service(...)` calls.

### `assert_not_called`

```python
--8<-- "pages/testing/snippets/testing_assert_not_called.py"
```

### `assert_call_count`

```python
--8<-- "pages/testing/snippets/testing_assert_call_count.py"
```

### `get_calls`

Returns a list of `ApiCall` records, optionally filtered by method name. Each `ApiCall` has `method`, `args`, and `kwargs` attributes.

```python
--8<-- "pages/testing/snippets/testing_get_calls.py"
```

### `reset`

Clears all recorded calls. Useful when you want to assert on calls made after a specific point in your test.

```python
--8<-- "pages/testing/snippets/testing_recorder_reset.py"
```

## Configuration Errors

If the `config` dict you pass to `AppTestHarness` fails validation against your app's `AppConfig` class, the harness raises `AppConfigurationError` during setup — the `async with` body is never entered, so your test code inside the block does not run.

```python
--8<-- "pages/testing/snippets/testing_app_configuration_error.py"
```

`AppConfigurationError` has two attributes:
- `app_cls` — the `App` class whose config failed.
- `original_error` — the underlying `pydantic.ValidationError` with full field-level detail.

Read the error message to find which field is missing or invalid, then fix the `config` dict in your test.

## Harness Startup Failures

If the harness raises `TimeoutError: Timed out waiting for <YourApp> RUNNING`, the app's `on_initialize()` either raised an exception or took longer than 5 seconds to complete.

!!! info "This is a bare `TimeoutError`, not `DrainTimeout`"
    Harness startup timeouts are distinct from drain timeouts. The startup wait still raises a plain `TimeoutError` — catch `TimeoutError` here, not `DrainTimeout` or `DrainFailure`. Drain-related failures only happen once the harness is running and you call `simulate_*`.

Check test output for log lines near the `TimeoutError` — exceptions raised during `on_initialize()` are caught and logged at `WARNING` level during harness cleanup, so the `TimeoutError` is the surface symptom, not the root cause.

Common triggers:
- A required config field is present but its value causes a runtime error during initialization (distinct from a missing-field `AppConfigurationError` which fires before entry).
- `on_initialize()` awaits something that never resolves, such as an external call that isn't mocked.
- An `await` inside `on_initialize()` raises an exception that propagates out.

## Next Steps

- **[Time Control](time-control.md)**: Freeze and advance time to test scheduler-driven behavior
- **[Concurrency & pytest-xdist](concurrency.md)**: Understand the same-class lock and parallel test runners
- **[Factories & Internals](factories.md)**: Event factories, state factories, `make_test_config`, and `RecordingApi` coverage boundary
- **[Bus](../core-concepts/bus/index.md)**: Learn how to register handlers in your app
- **[Scheduler](../core-concepts/scheduler/index.md)**: Learn how to register scheduled jobs
- **[API](../core-concepts/api/index.md)**: The `self.api` methods your app calls
