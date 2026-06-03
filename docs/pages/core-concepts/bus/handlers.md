# Writing Event Handlers

A handler is an async method that runs when an event matches a subscription. Hassette
supports four handler patterns, from no parameters to fully typed dependency injection.
Each subscription also accepts operational controls for errors, timeouts, and registration.

## Handler Patterns

### No data needed

A handler with no parameters runs as a side effect. No event data is extracted or passed.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_no_data.py"
```

### Raw event

A handler annotated with [`RawStateChangeEvent`][hassette.events.hass.hass.`RawStateChangeEvent`] receives the untyped event object directly.
The state value lives at `event.payload.data.new_state.get("state")`.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_raw_event.py"
```

This pattern suits exploratory work or event types that [dependency injection](dependency-injection.md)
doesn't cover.

### Typed state event

`D.TypedStateChangeEvent[T]` wraps the same event with typed state objects. The new and
old state values are accessible as attributes instead of raw dicts.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_typed_event.py"
```

`D` is an alias for `hassette.dependencies`. `states` is `hassette.models.states`,
which contains typed state classes for each Home Assistant domain. See the
[Dependency Injection](dependency-injection.md) page for the full import reference.

### Extracted data (recommended)

[`D` annotations](dependency-injection.md) tell Hassette which fields to extract from the
event and pass as individual parameters. No event object is received; only the requested
data arrives.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_extract_data.py"
```

`D.StateNew[T]` delivers the new state converted to type `T`. `D.EntityId` delivers the
entity ID string. The [Dependency Injection](dependency-injection.md) page covers the
full annotation table, union types, and custom extractors.

## Non-State Event Types

The bus subscribes to more than state changes. Each method below returns a [`Subscription`][hassette.bus.listeners.`Subscription`],
a handle that cancels the listener when called. All accept the same `name=`, `on_error=`,
`timeout=`, `debounce=`, and `throttle=` options as `on_state_change`.

### Home Assistant events

| Method | Fires when |
|---|---|
| `on_state_change(entity)` | An entity's state string changes |
| `on_attribute_change(entity, attr)` | A specific entity attribute changes |
| `on_call_service(domain, service)` | A HA service is called |
| `on_component_loaded(component)` | A HA component finishes loading |
| `on_service_registered(domain, service)` | A new HA service is registered |
| `on_homeassistant_start()` | HA starts up |
| `on_homeassistant_stop()` | HA begins shutting down |
| `on_homeassistant_restart()` | HA restarts |
| `on(topic=...)` | Any raw HA event topic |

An `on_call_service` handler receives the service call's entity ID via `D.EntityId`:

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/non_state_call_service.py"
```

`on()` subscribes to any raw topic string. The handler receives the full event.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/non_state_raw_topic.py"
```

### Cross-app communication

`emit(topic, data)` broadcasts a payload to all subscribers of a custom topic. Other
apps subscribe to the same topic with `on()`. Handlers annotated with `D.EventData[T]`
receive `data` pre-extracted.

### Hassette-internal events

These fire for framework-level changes within the running instance.

| Method | Fires when |
|---|---|
| `on_websocket_connected()` | The HA WebSocket connection is established |
| `on_websocket_disconnected()` | The HA WebSocket connection is lost |
| `on_hassette_service_status(status)` | A Hassette service changes status |
| `on_hassette_service_started()` | A Hassette service reaches STARTED |
| `on_hassette_service_failed()` | A Hassette service reaches FAILED |
| `on_hassette_service_crashed()` | A Hassette service reaches CRASHED |
| `on_app_state_changed(app_key, status)` | An app instance changes status |
| `on_app_running(app_key)` | An app instance reaches RUNNING |
| `on_app_stopping(app_key)` | An app instance begins stopping |

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/non_state_internal.py"
```

## Error Handling

### App-level error handler

`bus.on_error(handler)` registers a fallback for all listeners without a per-registration
error handler. The handler receives a
[`BusErrorContext`][hassette.bus.error_context.BusErrorContext] with full exception details.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/bus_error_handler_app.py"
```

The handler is resolved at dispatch time, not at listener registration time. Registering
`on_error()` after listeners are already in place is valid; the handler fires for those
listeners too. Any listener that fires before `on_error()` is called has no fallback.
Registering it as the first statement in `on_initialize()` closes that gap.

### Per-registration error handler

`on_error=` on any subscription method registers a handler for that listener only.
It takes precedence over the app-level handler.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/bus_error_handler_per_reg.py"
```

Both sync and async functions are accepted. If the error handler itself raises or times
out, Hassette logs the failure. The executor's error handler failure counter increments,
but the original listener's telemetry record stays unaffected.

### What `BusErrorContext` contains

| Field | Type | Description |
|---|---|---|
| `exception` | `BaseException` | The raised exception |
| `traceback` | `str` | Full formatted traceback. Always present. |
| `topic` | `str` | The event topic the listener was registered on |
| `listener_name` | `str` | Human-readable listener identity |
| `event` | `Event[Any]` | The event being processed when the exception occurred |

## Timeout Configuration

`timeout=` overrides the global `event_handler_timeout_seconds` setting for one listener.
`timeout_disabled=True` removes enforcement entirely for that listener.

```python
--8<-- "pages/core-concepts/bus/snippets/bus_timeouts.py"
```

`timeout=` accepts a float in seconds. A handler that exceeds its timeout is cancelled
and the failure is recorded in telemetry.

## Registration Mechanics

### The `name=` parameter

All subscription methods require a `name=` parameter, a stable string identifier for the
listener. The name forms part of the natural key `(app_key, instance_index, name, topic)`
used for upsert deduplication across restarts.

```python
--8<-- "pages/core-concepts/bus/snippets/bus_registration_identity.py:registration_identity"
```

Two listeners on the same topic in the same app instance must carry distinct names. Two
listeners with the same name on different topics are distinct; topic is part of the key.

[`ListenerNameRequiredError`][hassette.exceptions.ListenerNameRequiredError] is raised at call time when `name=` is omitted. The message
includes the handler method and topic.

[`DuplicateListenerError`][hassette.exceptions.DuplicateListenerError] is raised when a second listener with the same `(name, topic)`
is registered within the same app session. Cross-session registrations with the same name
and topic update the existing record via upsert. This is not an error.

### Registration completes synchronously

Routing and database persistence both complete before the awaited call returns.
`sub.listener.db_id` is a valid integer immediately. No background task, no polling.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/bus_subscription_patterns.py:await_persistence"
```

### Sequential operations are deterministic

Cancel-then-resubscribe sequences have no race conditions. The old handler is guaranteed
gone before the new registration begins.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/bus_subscription_patterns.py:resubscribe"
```

## See Also

- [Dependency Injection](dependency-injection.md): full annotation table, custom extractors, and type conversion
- [Filtering & Predicates](filtering.md): filter which events reach a handler
- [Subscribing to State Changes](index.md): state-specific subscription patterns and options
