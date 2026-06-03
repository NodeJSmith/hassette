# Bus & Events

This page covers migrating AppDaemon event listeners and state change listeners to Hassette's event bus (`self.bus`).

## The `name=` Requirement

Every `self.bus.on_*()` call requires a `name=` argument. Omitting it raises [`ListenerNameRequiredError`][hassette.exceptions.ListenerNameRequiredError] at call time. Hassette uses this name for telemetry, log output, and listener deduplication across restarts.

=== "Missing name (breaks)"

    ```python
    # Raises ListenerNameRequiredError immediately
    await self.bus.on_state_change("light.kitchen", handler=self.on_change)
    ```

=== "With name (correct)"

    ```python
    await self.bus.on_state_change("light.kitchen", handler=self.on_change, name="kitchen_light")
    ```

This is the most common cause of breakage when porting AppDaemon apps. Add `name=` to every subscription call before running the app.

## State Change Listeners

AppDaemon uses `self.listen_state()` with a fixed four-argument callback signature. Hassette uses `self.bus.on_state_change()`, which is `async` and must be awaited. Handler signatures are flexible. Annotate parameters and Hassette fills them in.

=== "AppDaemon"

    ```python
    --8<-- "pages/migration/snippets/bus_appdaemon_state_change.py"
    ```

=== "Hassette (dependency injection, recommended)"

    ```python
    --8<-- "pages/migration/snippets/bus_hassette_state_change_di.py"
    ```

=== "Hassette (full event)"

    ```python
    --8<-- "pages/migration/snippets/bus_hassette_state_change_event.py"
    ```

The dependency injection form is preferred. `D.StateNew[states.InputButtonState]` tells Hassette to extract the new state and convert it to a typed model. Your IDE knows the type; Pyright catches typos.

### Filter argument mapping

`on_state_change()` supports built-in filter arguments that replace AppDaemon's `new=` and `old=` kwargs:

| AppDaemon | Hassette |
|---|---|
| `new="on"` | `changed_to="on"` |
| `old="off"` | `changed_from="off"` |
| `attribute="battery"` | Use `on_attribute_change()` instead |

For more complex filtering, pass a predicate via `where=`. See [Bus filtering](../core-concepts/bus/filtering.md) for the full reference.

## Attribute Change Listeners

AppDaemon uses `self.listen_state(..., attribute="battery")` to watch a specific attribute. Hassette has a dedicated method for this: `on_attribute_change()`.

```python
await self.bus.on_attribute_change(
    "sensor.phone",
    "battery_level",
    handler=self.on_battery,
    name="phone_battery",
)
```

The method signature is `on_attribute_change(entity_id, attr, *, handler, name, ...)`. The `attribute=` argument on `listen_state()` maps directly to the second positional argument here.

## Service Call Listeners

AppDaemon uses `self.listen_event("call_service", ...)` with a callback that receives raw dicts. Hassette uses `self.bus.on_call_service()`, which is `async` and must be awaited.

=== "AppDaemon"

    ```python
    --8<-- "pages/migration/snippets/bus_appdaemon_event.py"
    ```

=== "Hassette (dependency injection, recommended)"

    ```python
    --8<-- "pages/migration/snippets/bus_hassette_on_call_service_di.py"
    ```

=== "Hassette (full event)"

    ```python
    --8<-- "pages/migration/snippets/bus_hassette_on_call_service_event.py"
    ```

Dependency markers available in service call handlers:

- `D.Domain`, the service domain (e.g., `"light"`)
- `D.EntityId` / `D.MaybeEntityId`, entity ID from the service data
- `D.EventContext`, the HA event context object
- `Annotated[str, A.get_service]`, the service name
- `Annotated[Any, A.get_service_data]`, the full service data dict

AppDaemon passes extra kwargs from `listen_event()` into the callback via `**kwargs`. Hassette uses `where=` for filtering instead. Pass a dict or predicate to match on domain, service, entity ID, or arbitrary fields.

## Canceling Subscriptions

AppDaemon returns an opaque handle from `listen_state()` and requires a separate cancel call. Hassette returns a [Subscription][hassette.bus.listeners.Subscription] object with a `.cancel()` method.

=== "AppDaemon"

    ```python
    handle = self.listen_state(self.on_change, "light.kitchen")
    self.cancel_listen_state(handle)
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/bus_cancel_subscription.py"
    ```

All registration methods (`on_state_change`, `on_attribute_change`, `on_call_service`, `on`) are `async` and must be awaited. `.cancel()` on the returned `Subscription` is synchronous.

## Common Migration Patterns

### State change with filter

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

### Service call subscription

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

- [Bus Overview](../core-concepts/bus/index.md), the full bus API
- [Writing Handlers](../core-concepts/bus/handlers.md), handler patterns and DI
- [Filtering & Predicates](../core-concepts/bus/filtering.md), composable predicate system
- [Dependency Injection](../core-concepts/bus/dependency-injection.md), full DI reference
