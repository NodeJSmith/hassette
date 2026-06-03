# Bus

The event bus delivers Home Assistant events (state changes, service calls, component loads) to any app handler that subscribes. It also delivers Hassette-internal events.

`self.bus` is available on every [App](../apps/index.md) instance. Hassette creates it at startup.

## Subscribing to Events

[`Bus`][hassette.bus.Bus] provides typed subscription methods for common event types. Each returns a [`Subscription`][hassette.bus.listeners.Subscription] handle.

```python
--8<-- "pages/core-concepts/bus/snippets/bus_basic_subscribe.py"
```

[`D.StateNew`][hassette.event_handling.dependencies] tells Hassette to extract the new state from the event and pass it as a typed [`BinarySensorState`][hassette.models.states.binary_sensor.BinarySensorState]. The handler receives clean, typed data instead of a raw event dictionary. [Dependency Injection](dependency-injection.md) covers the full annotation reference.

Four subscription methods cover the common event types:

| Method | Fires when |
|---|---|
| `on_state_change` | An entity's state value changes |
| `on_attribute_change` | A named attribute on an entity changes |
| `on_call_service` | A Home Assistant service is called |
| `on` | Any event on a given topic string |

All registration methods are async. Each requires a `name=` parameter, a stable string identifier for the listener. Additional specialized methods like `on_component_loaded` are covered in [Writing Handlers](handlers.md).

## Matching Multiple Entities

`Subscription` methods accept glob patterns for entity matching.

```python
--8<-- "pages/core-concepts/bus/snippets/bus_glob_patterns.py:glob_patterns"
```

`"light.*"` matches any entity in the `light` domain. `"sensor.bedroom_*"` matches sensors with a `bedroom_` prefix. The same patterns work for `domain` and `service` parameters on `on_call_service`.

!!! warning "Glob patterns match identifiers only"
    Glob patterns do not match attribute names or data values. [Predicates](filtering.md) handle those cases.

## Rate Control

Three subscription parameters manage handler invocation frequency.

`debounce` delays the handler until the event source has been quiet for N seconds. Each new event resets the timer.

```python
--8<-- "pages/core-concepts/bus/snippets/bus_rate_control.py:debounce"
```

`throttle` limits the handler to one invocation per N seconds. Events during the cooldown are dropped.

```python
--8<-- "pages/core-concepts/bus/snippets/bus_rate_control.py:throttle"
```

`once=True` fires the handler exactly once, then cancels the subscription.

```python
--8<-- "pages/core-concepts/bus/snippets/bus_rate_control.py:once"
```

!!! warning "One strategy per subscription"
    `debounce`, `throttle`, and `once` are mutually exclusive. Combining any two raises `ValueError` at registration.

## Synchronous Usage

`self.bus.sync` exposes a [`BusSyncFacade`][hassette.bus.sync.BusSyncFacade] that mirrors all subscription methods as blocking calls. It exists for [`AppSync`][hassette.app.app.AppSync] lifecycle hooks, which run outside the async event loop. The [Apps](../apps/index.md) page covers the `AppSync` pattern.

## Next Steps

- [Writing Handlers](handlers.md): handler signature patterns and choosing the right one
- [Subscription Methods](methods.md): full method reference, parameters, error handling, timeouts, and registration
- [Filtering & Predicates](filtering.md): predicates, conditions, and accessors for complex event matching
- [Dependency Injection](dependency-injection.md): the full `D.*` annotation reference and how Hassette resolves handler parameters
