# Bus & Events

This page covers how to migrate AppDaemon event listeners and state change listeners to Hassette's event bus (`self.bus`).

## Overview

AppDaemon exposes event subscriptions as methods directly on `self`: `self.listen_state(...)`, `self.listen_event(...)`. You cancel subscriptions using a handle returned by the listen call.

Hassette centralizes event subscriptions on `self.bus`. Each subscription method returns a `Subscription` object. You cancel it by calling `.cancel()` on that object.

## State Change Listeners

### AppDaemon

In AppDaemon, `self.listen_state()` listens for state changes on an entity. Callback signatures must follow a fixed pattern:

```python
--8<-- "pages/migration/snippets/bus_appdaemon_state_change.py"
```

### Hassette: with Dependency Injection (recommended)

In Hassette, `self.bus.on_state_change()` is the equivalent. Handler signatures are flexible — use type annotations and Hassette extracts the data for you:

```python
--8<-- "pages/migration/snippets/bus_hassette_state_change_di.py"
```

### Hassette: with the full event object

If you prefer to receive the raw event and inspect it yourself:

```python
--8<-- "pages/migration/snippets/bus_hassette_state_change_event.py"
```

### Filter options

`on_state_change()` supports built-in filter arguments:

| AppDaemon argument | Hassette equivalent |
|-------------------|---------------------|
| `new="on"` | `changed_to="on"` |
| `old="off"` | `changed_from="off"` |
| `attribute="battery"` | Use `on_attribute_change()` instead |

For more complex filtering, pass a predicate via the `where` parameter (`where=P.StateTo('on')` for example). See the [Bus filtering docs](../core-concepts/bus/filtering.md) for the full reference.

## Service Call Listeners

### AppDaemon

In AppDaemon, you use `self.listen_event("call_service", ...)` to monitor service calls:

```python
--8<-- "pages/migration/snippets/bus_appdaemon_event.py"
```

The callback signature must follow `(self, event_name, event_data, **kwargs)`. Extra keyword arguments you passed when subscribing arrive in `**kwargs`.

### Hassette: with Dependency Injection (recommended)

Use `self.bus.on_call_service()` and annotate your handler to extract exactly the fields you need:

```python
--8<-- "pages/migration/snippets/bus_hassette_on_call_service_di.py"
```

Available dependency markers for service call handlers include:

- `D.Domain` — the service domain (e.g., `"light"`)
- `D.EntityId` / `D.MaybeEntityId` — entity ID from the service data
- `D.EventContext` — the HA event context object
- `Annotated[str, A.get_service]` — the service name
- `Annotated[Any, A.get_service_data]` — the full service data dict

### Hassette: with the full event object

```python
--8<-- "pages/migration/snippets/bus_hassette_on_call_service_event.py"
```

!!! warning "Handler constraints"
    Handlers **cannot** use positional-only parameters (parameters before `/`) or variadic positional arguments (`*args`).

!!! note "Untyped event payload at runtime"
    The event bus works with typed events, but the data in the event payload is untyped at runtime. Use dependency injection or convert data manually to work with typed objects.

## Canceling Subscriptions

=== "AppDaemon"

    ```python
    handle = self.listen_state(...)
    self.cancel_listen_state(handle)
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/bus_cancel_subscription.py"
    ```

The subscription object returned by `on_state_change()`, `on_call_service()`, and `on()` all support `.cancel()`.

## Common Migration Patterns

### State changes with a filter

=== "AppDaemon"

    ```python
    def initialize(self):
        self.listen_state(self.on_motion, "binary_sensor.motion", new="on")

    def on_motion(self, entity, attribute, old, new, **kwargs):
        self.log(f"Motion detected on {entity}")
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/bus_migration_state_changes.py"
    ```

### Service call subscriptions

=== "AppDaemon"

    ```python
    def initialize(self):
        self.listen_event(
            self.on_service,
            "call_service",
            domain="light",
            service="turn_on",
        )
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/bus_migration_service_calls.py"
    ```

## See Also

- [Bus Overview](../core-concepts/bus/index.md) — the full bus API
- [Writing Handlers](../core-concepts/bus/handlers.md) — handler patterns and DI
- [Filtering & Predicates](../core-concepts/bus/filtering.md) — composable predicate system
- [Dependency Injection](../core-concepts/bus/dependency-injection.md) — full DI reference
