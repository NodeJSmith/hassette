# Test Harness Reference

`AppTestHarness` wires an [App][hassette.app.app.App] subclass into Hassette's test infrastructure without a live Home Assistant connection. It exposes the app's bus, scheduler, seeded state, and a `RecordingApi` that records every API call.

## Basic Pattern

A typical test creates a harness, simulates an event, and asserts on the API calls the app made:

```python
--8<-- "pages/testing/snippets/testing_quick_start.py"
```

The `async with` block initializes the app (running `on_initialize`), then tears it down on exit. `simulate_state_change` publishes an event through the bus and waits for all handlers to finish. `api_recorder.assert_called` verifies the app called the expected service.

The sections below cover each piece of this pattern in detail.

## Prerequisites

The harness ships in the `hassette[test]` extra. [Write Your First
Test](index.md) covers installation and `pyproject.toml` setup.

## Seeding State

`set_state()` pre-populates a single entity's state into the state proxy (the in-process state store that app code reads via `self.states`).
`set_states()` pre-populates multiple entities at once.

```python
--8<-- "pages/testing/snippets/testing_state_seeding.py"
```

Both methods write directly to the state proxy. No bus events fire. Handlers
do not run.

`set_states()` accepts a plain state string or a `(state, attrs)` tuple per
entity.

!!! warning "Seed state before simulating events"
    `set_state()` does not fire bus events. It must precede
    `simulate_state_change()` for the same entity, not follow it. A later
    `set_state()` silently overwrites the state the simulation wrote.

## Simulating Events

Every `simulate_*` method sends an event through the bus and waits for all
triggered handlers to complete before returning.

!!! warning "Forgetting `await` fires nothing"
    Every `simulate_*` method is a coroutine. A call without `await` publishes
    no event — handlers never run, and a following `assert_called` fails even
    though the app code is correct. A `RuntimeWarning: coroutine ... was never
    awaited` in the pytest output is the tell.

### State Changes

`simulate_state_change()` publishes a `state_changed` event and drains all
handlers.

```python
--8<-- "pages/testing/snippets/testing_simulate_state_change.py"
```

Typed dependency injection via `D.StateNew[T]`
(`from hassette import D` — see
[Dependency Injection](../core-concepts/bus/dependency-injection.md)) delivers
the new state as a typed object:

```python
--8<-- "pages/testing/snippets/testing_di_state_change.py"
```

When `old_attrs` or `new_attrs` is omitted, `simulate_state_change()` merges
attributes from the state proxy automatically. Attributes seeded via
`set_state()` appear in the event without being passed again.

### Attribute Changes

`simulate_attribute_change()` changes one attribute while keeping the entity's
state value. It delegates to `simulate_state_change()` internally.

```python
--8<-- "pages/testing/snippets/testing_simulate_attribute_change.py"
```

State value resolution order: the explicit `state=` argument, the value cached
in the state proxy, then `"unknown"` as a fallback. Seeding state first avoids
the fallback.

!!! warning "Attribute changes can fire state-change handlers"
    `on_state_change` handlers registered with `changed=False` fire on any
    `state_changed` event, including attribute-only changes. When an app
    registers such a handler, `simulate_attribute_change()` fires both it and
    any `on_attribute_change` handler for the same entity.

```python
--8<-- "pages/testing/snippets/testing_attribute_change_both_handlers.py"
```

### Service Calls

`simulate_call_service()` publishes a `call_service` event and drains all
handlers.

```python
--8<-- "pages/testing/snippets/testing_simulate_call_service.py"
```

`D.Domain` ([`hassette.event_handling.dependencies`](../core-concepts/bus/dependency-injection.md))
injects the service domain into handlers the same way `D.StateNew` works for
state changes:

```python
--8<-- "pages/testing/snippets/testing_di_call_service.py"
```

### Hassette Service Events

`simulate_hassette_service_status()` fires a Hassette-internal service
lifecycle event. Convenience wrappers cover the common cases:

| Method | Status | `ready` |
|---|---|---|
| `simulate_hassette_service_ready(resource_name)` | `RUNNING` | `True` |
| `simulate_hassette_service_started(resource_name)` | `RUNNING` | `False` |
| `simulate_hassette_service_failed(resource_name)` | `FAILED` | `False` |
| `simulate_hassette_service_crashed(resource_name)` | `CRASHED` | `False` |

```python
--8<-- "pages/testing/snippets/testing_simulate_service_failure.py"
```

`simulate_hassette_service_status()` accepts `previous_status`, `exception`,
and `role` for cases the convenience wrappers do not cover.

### Other Framework Events

The harness simulates every event type the bus can deliver, so handlers
registered for connection, app-lifecycle, and HA-lifecycle events are testable
without a live instance:

| Method | Fires the event for |
|---|---|
| `simulate_websocket_connected()` / `simulate_websocket_disconnected()` | `on_websocket_connected` / `on_websocket_disconnected` — reconnection logic |
| `simulate_app_state_changed(app_key, status, ...)` | `on_app_state_changed` — inter-app coordination |
| `simulate_app_running(app_key)` / `simulate_app_stopping(app_key)` | the matching shorthands |
| `simulate_homeassistant_restart()` / `_start()` / `_stop()` | `on_homeassistant_restart` / `_start` / `_stop` |
| `simulate_component_loaded(component)` | `on_component_loaded` |
| `simulate_service_registered(domain, service)` | `on_service_registered` |

All drain triggered handlers before returning, like the other `simulate_*`
methods.

### Draining Manually

`drain_task_bucket(timeout=2.0)` waits for the bus dispatch queue and the
app's task bucket to go quiescent without firing an event. Call it after
[`trigger_due_jobs()`](time-control.md) when dispatched jobs emit bus events —
the job trigger does not drain the downstream handler tasks itself. Raises the
same `DrainTimeout`/`DrainError` exceptions as the `simulate_*` methods; when
debounced handlers are involved, pass a `timeout=` larger than the debounce
window.

### Timeouts

All `simulate_*` methods default to a 2-second drain timeout. The `timeout=`
parameter overrides this per call.

```python
--8<-- "pages/testing/snippets/testing_simulate_timeout.py"
```

The drain mechanism waits until both the bus dispatch queue and the app's task
bucket are quiescent.

| Exception | Meaning |
|---|---|
| `DrainTimeout` | Handlers did not finish within the deadline |
| `DrainError` | One or more handlers raised an exception |
| `DrainFailure` | Base class; catches both of the above |

When tasks include debounce handlers, the `timeout=` value should exceed the
debounce window. [Concurrency](concurrency.md) covers task chain draining in
detail.

## Asserting API Calls

`harness.api_recorder` exposes a `RecordingApi` that records every call the
app makes through `self.api`: `turn_on`, `turn_off`, `call_service`,
`set_state`, `fire_event`, and all helper CRUD methods.

### assert_called

`assert_called(method, **kwargs)` passes when at least one recorded call
matches every specified key-value pair. Extra kwargs in the recorded call are
allowed (partial match).

```python
--8<-- "pages/testing/snippets/testing_assert_called.py"
```

`turn_on`, `turn_off`, and `toggle_service` record under their own names, not
under `call_service`:

```python
--8<-- "pages/testing/snippets/testing_assert_turn_on_off.py"
```

For strict assertions, `assert_called_exact(method, **kwargs)` requires the
recorded kwargs to match exactly — extra recorded kwargs fail the assertion.
Use it to prove no unexpected arguments were forwarded.
`assert_called_partial` is an explicit-name alias for `assert_called` when the
partial-match intent should be visible in the test.

### assert_not_called

`assert_not_called(method, **kwargs)` raises `AssertionError` when a matching
call exists. With `kwargs`, only calls whose recorded kwargs include all given
pairs count as a violation.

```python
--8<-- "pages/testing/snippets/testing_assert_not_called.py"
```

### assert_call_count

`assert_call_count(method, count, **kwargs)` raises `AssertionError` when the
method was not called exactly `count` times. With `kwargs`, only matching
calls are counted.

```python
--8<-- "pages/testing/snippets/testing_assert_call_count.py"
```

### get_calls

`get_calls(method)` returns a list of `ApiCall` records for the named method.
Each `ApiCall` has `method`, `args`, and `kwargs` fields. Omitting `method`
returns all recorded calls.

```python
--8<-- "pages/testing/snippets/testing_get_calls.py"
```

### reset

`reset()` clears all recorded calls and resets helper definitions. Mid-test
isolation is the primary use case: asserting separately on two distinct phases
within one test.

```python
--8<-- "pages/testing/snippets/testing_recorder_reset.py"
```

`reset()` replaces the `calls` list with a new empty list. Any snapshot taken
before the reset (e.g., `saved = harness.api_recorder.calls`) retains the
original calls.

## Testing Configuration Errors

`AppConfigurationError` raises during `async with AppTestHarness(...)` entry
when the `config` dict fails validation. The `async with` body never runs.

```python
--8<-- "pages/testing/snippets/testing_app_configuration_error.py"
```

| Attribute | Type | Description |
|---|---|---|
| `app_cls` | `type[App]` | The `App` class whose config failed |
| `original_error` | `pydantic.ValidationError` | The underlying Pydantic error |

## Testing Startup Failures

When `on_initialize()` raises, the harness startup times out with a plain
`TimeoutError`. This is distinct from `DrainTimeout`, which only surfaces from
`simulate_*` methods. The exception from `on_initialize()` appears in the log
output.

## Harness Constructor and Properties

### Constructor

```python
--8<-- "pages/testing/snippets/testing_constructor.py"
```

| Parameter | Type | Description |
|---|---|---|
| `app_cls` | `type[App]` | The `App` subclass to test |
| `config` | `dict[str, Any]` | Config values validated against the app's [AppConfig][hassette.app.app_config.AppConfig] |
| `tmp_path` | `Path \| None` | Directory for Hassette data. Auto-created and cleaned up if omitted. |

### Properties

| Property | Type | Description |
|---|---|---|
| `harness.app` | `App` | Fully initialized app instance |
| `harness.bus` | [Bus][hassette.bus.bus.Bus] | Test bus owned by the app |
| `harness.scheduler` | [Scheduler][hassette.scheduler.scheduler.Scheduler] | Test scheduler owned by the app |
| `harness.api_recorder` | `RecordingApi` | Records every API call the app makes |
| `harness.states` | [StateManager][hassette.state_manager.state_manager.StateManager] | State manager owned by the app |

## Next Steps

- [Time Control](time-control.md): freeze time and trigger scheduled jobs
- [Concurrency & pytest-xdist](concurrency.md): parallel test execution and
  drain failure details
- [Factories](factories.md): build custom state dicts and event objects
