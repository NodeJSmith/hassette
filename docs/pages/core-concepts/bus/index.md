# Bus

The event bus delivers Home Assistant events (state changes, service calls, component loads) to any app handler that subscribes. It also delivers Hassette-internal events.

`self.bus` is available on every [App](../apps/index.md) instance. Hassette creates it at startup.

## Subscribing to Events

[`Bus`][hassette.bus.Bus] provides typed subscription methods for common event types. Each returns a [`Subscription`][hassette.bus.listeners.Subscription] handle — call `sub.cancel()` to unregister the handler.

!!! warning "All registration methods must be awaited"
    Every `on_*` and `add_listener` call returns a coroutine. Without `await`, the listener is never registered and no error is raised at the call site. A forgotten `await` produces a [`HassetteForgottenAwaitWarning`][hassette.exceptions.HassetteForgottenAwaitWarning] naming the offending app when the coroutine is GC'd (subject to [configuration](../../troubleshooting.md#forgotten-await)). Pyright's `reportUnusedCoroutine` catches this at edit time — see [Enabling Pyright](../../troubleshooting.md#enabling-pyright).

```python
--8<-- "pages/core-concepts/bus/snippets/bus_basic_subscribe.py"
```

[`D`](dependency-injection.md) is `hassette.event_handling.dependencies`, a module of type annotations that tell Hassette what to extract from each event. [`states`][hassette.models.states] is `hassette.models.states`, typed state classes for each Home Assistant domain. `D.StateNew[states.BinarySensorState]` extracts the new state and passes it as a typed [`BinarySensorState`][hassette.models.states.binary_sensor.BinarySensorState]. The handler receives clean, typed data instead of a raw event dictionary. [Dependency Injection](dependency-injection.md) covers the full annotation reference.

`name=` is required on every subscription — it identifies the listener in logs and the monitoring UI. Omitting it raises `ListenerNameRequiredError` at call time.

[Subscription Methods](methods.md) covers each method, its parameters, and compatible DI annotations.

## Matching Multiple Entities

`Subscription` methods accept glob patterns for entity matching.

```python
--8<-- "pages/core-concepts/bus/snippets/bus_glob_patterns.py:glob_patterns"
```

`"light.*"` matches any entity in the `light` domain. `"sensor.bedroom_*"` matches sensors with a `bedroom_` prefix. The same patterns work for `domain` and `service` parameters on `on_call_service`.

!!! warning "Glob patterns match identifiers only"
    Glob patterns do not match attribute names or data values. Predicates (functions that decide whether to run the handler — see [Filtering](filtering.md)) handle those cases.

??? note "Synchronous usage (AppSync only)"
    `self.bus.sync` exposes a [`BusSyncFacade`][hassette.bus.sync.BusSyncFacade] that mirrors all subscription methods as blocking calls. It exists for [`AppSync`][hassette.app.app.AppSync] lifecycle hooks, which run in a worker thread outside the async event loop. The [Apps](../apps/index.md) page covers the `AppSync` pattern.

## Verify It's Working

Run `hassette listener --app <key>` to see registered listeners and invocation counts, where `<key>` is the app identifier from `hassette.toml` (e.g., `motion_lights`). Run `hassette log --app <key> --since 5m` to see handler log output. The [monitoring UI's](../../web-ui/index.md) Handlers tab shows invocation history and last-seen timestamps.

## Next Steps

- [Writing Handlers](handlers.md): start here — handler signature patterns and choosing the right one
- [Subscription Methods](methods.md): full method reference, parameters, error handling, timeouts, and registration
- [Filtering & Predicates](filtering.md): predicates, conditions, and accessors for complex event matching
- [Dependency Injection](dependency-injection.md): the full `D.*` annotation reference and how Hassette resolves handler parameters
