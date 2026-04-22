# Writing Event Handlers

Once you've subscribed to an event, you need a handler to process it. Hassette handlers are flexible, supporting dependency injection (DI), custom keyword arguments, and various event patterns.

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
from hassette.bus.error_context import BusErrorContext

class MyApp(App[AppConfig]):
    async def on_initialize(self):
        # Register first to avoid the reload gap
        self.bus.on_error(self.on_bus_error)

        self.bus.on_state_change("light.kitchen", handler=self.on_light_change)

    async def on_bus_error(self, ctx: BusErrorContext) -> None:
        self.logger.error(
            "Handler failed for topic=%s: %s\n%s",
            ctx.topic,
            ctx.exception,
            ctx.traceback,
        )

    async def on_light_change(self, event) -> None:
        raise ValueError("something went wrong")
```

### Per-registration error handler

```python
from hassette.bus.error_context import BusErrorContext

class MyApp(App[AppConfig]):
    async def on_initialize(self):
        self.bus.on_state_change(
            "sensor.temperature",
            handler=self.on_temp_change,
            on_error=self.on_temp_error,
        )

    async def on_temp_error(self, ctx: BusErrorContext) -> None:
        self.logger.warning("Temperature handler failed: %s", ctx.exception)

    async def on_temp_change(self, event) -> None:
        raise RuntimeError("temp sensor error")
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

## See Also

- [Filtering & Predicates](filtering.md) - Filter which events trigger your handlers
- [Dependency Injection](dependency-injection.md) - Full annotation table, custom extractors, and type conversion
- [API](../api/index.md) - Call services in response to events
