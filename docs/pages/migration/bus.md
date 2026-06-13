# Bus & Events

This page covers migrating AppDaemon event listeners and state change listeners to Hassette's event bus (`self.bus`).

!!! note "Coming from synchronous AppDaemon?"
    All registration methods (`on_state_change`, `on_attribute_change`, `on_call_service`, `on`) are `async` and must be awaited — see [Async Basics](async-basics.md) if that shift is new to you.

## Breaking Change: Once-listener name collision now raises

Previously, two `once=True` listeners registered with the same `name` and topic coexisted silently — no error was raised and both listeners remained active. `once=True` listeners now participate in name+topic collision tracking like durable listeners. A second registration under the same name and topic raises `DuplicateListenerError`.

This change affects any app that registers duplicate once-listeners intentionally or accidentally under matching names and topics.

**What to do:**

- **Distinct names** — give each once-listener a unique `name=`. This is the simplest fix and works when each registration is logically distinct.
- **`if_exists="skip"`** — pass `if_exists="skip"` when the intent is idempotent registration (register once, ignore duplicates with matching config).
- **`if_exists="replace"`** — pass `if_exists="replace"` when the new registration should supersede the previous one.

```python
# Before: silently registered two listeners — unpredictable behavior
await self.bus.on_state_change(
    "binary_sensor.motion",
    handler=self.on_motion,
    name="motion_once",
    once=True,
)
await self.bus.on_state_change(
    "binary_sensor.motion",
    handler=self.on_motion,
    name="motion_once",
    once=True,
)

# After option 1: distinct names
await self.bus.on_state_change(
    "binary_sensor.motion",
    handler=self.on_motion,
    name="motion_once_a",
    once=True,
)
await self.bus.on_state_change(
    "binary_sensor.motion",
    handler=self.on_motion,
    name="motion_once_b",
    once=True,
)

# After option 2: idempotent skip
await self.bus.on_state_change(
    "binary_sensor.motion",
    handler=self.on_motion,
    name="motion_once",
    once=True,
    if_exists="skip",
)
```

After a once-listener fires, its name+topic key is released. A subsequent registration under the same name and topic is a fresh registration and does not raise.

## The `name=` Requirement

Every `self.bus.on_*()` call requires a `name=` argument. Omitting it raises [`ListenerNameRequiredError`][hassette.exceptions.ListenerNameRequiredError] at call time. Hassette uses this name in log output and the monitoring UI, and to avoid registering the same listener twice after a reload.

=== "Missing name (breaks)"

    ```python
    --8<-- "pages/migration/snippets/bus_name_missing.py"
    ```

=== "With name (correct)"

    ```python
    --8<-- "pages/migration/snippets/bus_name_correct.py"
    ```

This is the most common cause of breakage when porting AppDaemon apps. Add `name=` to every subscription call before running the app.

## State Change Listeners

AppDaemon uses `self.listen_state()` with a fixed four-argument callback signature. Hassette uses `self.bus.on_state_change()`, which is `async` and must be awaited. Handler signatures are flexible: instead of AppDaemon's fixed `(entity, attribute, old, new, kwargs)`, declare only the parameters the handler needs and give them type hints — Hassette reads the hints and passes the matching values in. This pattern is called dependency injection.

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

The dependency injection form is preferred. `D.StateNew[states.InputButtonState]` tells Hassette to extract the new state and convert it to a typed model — `D` is `hassette.event_handling.dependencies`, `states` is the module of typed state classes. `AppConfig` in the example replaces AppDaemon's `self.args`; fields declared on it are set in `hassette.toml` (see [Configuration](configuration.md)). If your editor runs a type checker, it knows the state's type and catches typos.

### Filter argument mapping

`on_state_change()` supports built-in filter arguments that replace AppDaemon's `new=` and `old=` kwargs:

| AppDaemon | Hassette |
|---|---|
| `new="on"` | `changed_to="on"` |
| `old="off"` | `changed_from="off"` |
| `attribute="battery"` | Use `on_attribute_change()` instead |

For more complex filtering, pass a predicate via `where=` — a function that receives the event and returns `True` or `False`. See [`Bus` filtering](../core-concepts/bus/filtering.md) for the full reference.

## Attribute Change Listeners

AppDaemon uses `self.listen_state(..., attribute="battery")` to watch a specific attribute. Hassette has a dedicated method for this: `on_attribute_change()`.

```python
--8<-- "pages/migration/snippets/bus_attribute_change.py:attribute_change"
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

These are the values Hassette can inject into service-call handler parameters — declare the ones the handler needs. `A` is `hassette.event_handling.accessors`, field extractors; `Annotated[str, A.get_service]` means "a `str`, extracted by `A.get_service`":

- `D.Domain`, the service domain (e.g., `"light"`)
- `D.EntityId` / `D.MaybeEntityId`, entity ID from the service data (`Maybe` allows calls where it's absent)
- `D.EventContext`, the HA event context object
- `Annotated[str, A.get_service]`, the service name
- `Annotated[Any, A.get_service_data]`, the full service data dict

AppDaemon passes extra kwargs from `listen_event()` into the callback via `**kwargs`. Hassette uses `where=` for filtering instead. Pass a dict or predicate to match on domain, service, entity ID, or arbitrary fields.

## Canceling Subscriptions

AppDaemon returns an opaque handle from `listen_state()` and requires a separate cancel call. Hassette returns a [`Subscription`][hassette.bus.listeners.Subscription] object with a `.cancel()` method.

=== "AppDaemon"

    ```python
    --8<-- "pages/migration/snippets/bus_cancel_appdaemon.py"
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
    --8<-- "pages/migration/snippets/bus_migration_state_appdaemon.py"
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/bus_migration_state_changes.py"
    ```

### Service call subscription

=== "AppDaemon"

    ```python
    --8<-- "pages/migration/snippets/bus_migration_service_appdaemon.py"
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/bus_migration_service_calls.py"
    ```

## Verify the Migration

Run `hassette listener --app <key>` to confirm each subscription registered under its `name=`, then trigger the entity and watch `hassette log --app <key>` for the handler's log line.

## See Also

- [`Bus` Overview](../core-concepts/bus/index.md), the full bus API
- [Writing Handlers](../core-concepts/bus/handlers.md), handler patterns and DI
- [Filtering & Predicates](../core-concepts/bus/filtering.md), composable predicate system
- [Dependency Injection](../core-concepts/bus/dependency-injection.md), full DI reference
