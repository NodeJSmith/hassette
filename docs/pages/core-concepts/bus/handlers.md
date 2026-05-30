# Writing Event Handlers

Once you've subscribed to an event, you need a handler to process it. Hassette supports dependency injection (DI), custom keyword arguments, and various event patterns — so your handlers can be as simple or detailed as you need.

## Event Model

Every event you receive from the bus is an [`Event`][hassette.events.base.Event] dataclass with two main fields:

- `topic` - a string identifier describing what happened, such as `hass.event.state_changed`.
- `payload` - an untyped object containing event-specific data.

!!! question "Why is the payload untyped?"

    You may be wondering why the event payload is untyped if Hassette is focused on strong typing. The reason for this is to avoid the overhead of converting every
    event payload to a typed object when the majority of payloads will never be used.

    Instead of converting *every* event payload, Hassette converts at the user boundary, such as when using Dependency Injection (DI) or
    accessing states through [DomainStates][hassette.state_manager.state_manager.DomainStates] (e.g. `self.states.light`).


## Dependency Injection

Hassette uses dependency injection (DI) to provide event data to your handlers. The type annotations on your handler parameters tell Hassette what data to extract from the event.

### Basic Patterns

**Option 1: Receive the full event in raw form** (simplest):
This gives you the raw event object, with the state data in untyped dicts. The raw state dict mirrors Home Assistant's `state_changed` event — the main state value is in `new_state["state"]`; attributes are in `new_state["attributes"]`.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_raw_event.py"
```

**Option 2: Receive full event with typed state objects** (better):
This gives you typed state objects for easier access to attributes.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_typed_event.py"
```

**Option 3: Extract specific data** (recommended for production code — if you're new to Hassette, start with Option 1 or 2):

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_extract_data.py"
```

**Option 4: No event data needed**:

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_no_data.py"
```

### Passing Custom Arguments

You can pass additional arguments to your handler using `kwargs` when subscribing. These are injected alongside event dependencies.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_custom_args.py"
```

### Available Dependencies

Dependencies are available via `from hassette import D`. The most common are `StateNew[T]`, `StateOld[T]`, `EntityId`, and `Domain`.

See the [Dependency Injection guide](dependency-injection.md#available-di-annotations) for the full annotation table, custom extractors, and automatic type conversion.

### Restrictions

!!! warning "Handler Signature Rules"
    Handlers **cannot** use:

    - Positional-only parameters (parameters before `/`)
    - Variadic positional arguments (`*args`)

    These restrictions ensure unambiguous parameter injection.

## Combining Multiple Dependencies

You can extract multiple pieces of data in a single handler:

```python
--8<-- "pages/core-concepts/bus/snippets/handlers_multiple_dependencies.py"
```

## Error Handling

When a listener raises an exception, Hassette logs the error and records it for telemetry. You can also register an error handler to receive a typed [`BusErrorContext`][hassette.bus.error_context.BusErrorContext] with full exception details.

There are two levels of error handlers:

- **App-level**: `bus.on_error(handler)` — applies to all listeners on this bus that don't have a per-registration handler.
- **Per-registration**: `on_error=` option on any `bus.on_state_change()`, `bus.on()`, etc. — takes precedence over the app-level handler.

Both levels can be sync or async.

!!! warning "Register early — the reload gap"
    The app-level handler is resolved at dispatch time, not at listener registration time. This means calling `bus.on_error()` after listeners are registered is valid and the handler will still fire. However, if a listener fires during app startup (before `on_error()` is called), the handler won't be invoked for that event. To avoid this gap, **register `on_error()` as the first statement in `on_initialize()`**.

### App-level error handler

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/bus_error_handler_app.py"
```

### Per-registration error handler

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/bus_error_handler_per_reg.py"
```

### What `BusErrorContext` contains

| Field | Type | Description |
|-------|------|-------------|
| `exception` | `BaseException` | The raised exception |
| `traceback` | `str` | Full formatted traceback — always present |
| `topic` | `str` | The event topic the listener was registered on |
| `listener_name` | `str` | Human-readable listener identity |
| `event` | `Event[Any]` | The event being processed when the exception occurred |

!!! note "Error handler failures"
    If the error handler itself raises or times out, the failure is logged at ERROR/WARNING and counted in the executor's error handler failure counter. The original listener's telemetry record is unaffected.

## Subscription and Registration

Every `bus.on_*()` method — `on_state_change()`, `on_attribute_change()`, `on_call_service()`, `on_component_loaded()`, and `on()` — is `async` and must be awaited. It returns a `Subscription` object once both routing and database registration are complete.

| Attribute | Description |
|-----------|-------------|
| `sub.cancel()` | Removes the listener immediately. |
| `sub.listener` | The underlying `Listener` object. |
| `sub.listener.db_id` | Integer database row ID — always set when the awaited call returns. |

### The `name=` parameter (required)

All database-registered listeners require a `name=` parameter — a stable string identifier for the listener. The name is part of the natural key `(app_key, instance_index, name, topic)` used for upsert deduplication across restarts.

```python
await self.bus.on_state_change(
    "light.kitchen",
    handler=self.on_light_change,
    name="kitchen_light",  # required
)
```

The name must be unique within a single app instance for a given topic. Two listeners with the same name on different topics are distinct — topic is part of the key.

**`ListenerNameRequiredError`** is raised at call time when `name=` is omitted. The error includes the handler method and topic:

```
ListenerNameRequiredError: Listener registration requires a name.

  handler: MyApp.on_light_change
  topic:   light.kitchen

Provide a stable name via the `name=` parameter:

  await self.bus.on_state_change("light.kitchen", handler=self.on_light_change, name="kitchen_light")
```

**`DuplicateListenerError`** is raised when a second listener with the same `(name, topic)` is registered within the same app session. Cross-session registrations with the same name and topic update the existing record via upsert — not an error.

```
DuplicateListenerError: A listener named 'kitchen_light' is already registered for topic 'light.kitchen'.

  existing handler: MyApp.on_light_change
  duplicate handler: MyApp.on_light_change_v2

Use a different name for the second listener, or remove the first registration before re-registering.
```

### Registration is complete when the awaited call returns

Routing and database persistence both complete before `on_state_change()` returns. `sub.listener.db_id` is a valid integer immediately — no further awaiting or checking is needed.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/bus_subscription_patterns.py:await_persistence"
```

### Sequential operations are deterministic

Cancel-then-resubscribe sequences have no race conditions — both routing removal and the new registration complete before the next statement runs:

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/bus_subscription_patterns.py:resubscribe"
```

## See Also

- [Filtering & Predicates](filtering.md) - Filter which events trigger your handlers
- [Dependency Injection](dependency-injection.md) - Full annotation table, custom extractors, and type conversion
- [API](../api/index.md) - Call services in response to events
