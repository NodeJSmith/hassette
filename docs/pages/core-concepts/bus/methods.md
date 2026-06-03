# Subscription Methods

[`Bus`][hassette.bus.Bus] provides typed subscription methods for each event category Home Assistant and Hassette emit. Each method returns a [`Subscription`][hassette.bus.listeners.Subscription] handle. Calling `sub.cancel()` removes the listener.

All registration methods are `async` and must be awaited. See [Registration](#registration) for what that guarantees.

## Shared Parameters

Every subscription method accepts these parameters. Individual method tables below list only method-specific parameters.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `handler` | `HandlerType` | — | The function called when the event matches. See [Writing Handlers](handlers.md). |
| `name` | `str \| None` | `None` | Required. Stable string identifier. Forms the natural key `(app_key, instance_index, name, topic)`. Omitting raises `ListenerNameRequiredError`. |
| `on_error` | `BusErrorHandlerType \| None` | `None` | Per-listener error handler. Overrides the app-level handler set via `bus.on_error()`. Available on `on_state_change`, `on_attribute_change`, `on_call_service`, `on_service_registered`, `on_component_loaded`, `on_app_state_changed`, and `on()`. |
| `timeout` | `float \| None` | `None` | Per-listener timeout in seconds. `None` inherits `event_handler_timeout_seconds` from config. |
| `timeout_disabled` | `bool` | `False` | Disables timeout enforcement for this listener regardless of config. |
| `debounce` | `float \| None` | `None` | Delays the handler until events have been quiet for N seconds. Each new event resets the timer. |
| `throttle` | `float \| None` | `None` | Limits the handler to one invocation per N seconds. Events during the cooldown are dropped. |
| `once` | `bool` | `False` | Fires the handler exactly once, then cancels the subscription. |
| `kwargs` | `Mapping \| None` | `None` | Keyword arguments passed to the handler at invocation time. |

`debounce`, `throttle`, and `once` are mutually exclusive. Combining any two raises `ValueError`.

## `on_state_change(entity_id)`

Fires when a Home Assistant entity's state changes. `entity_id` accepts glob patterns (`"light.*kitchen*"`).

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_state_change.py:basic"
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `entity_id` | `str` | — | Entity ID or glob pattern to match. |
| `changed` | `bool \| ComparisonCondition` | `True` | `True` fires only when the state value changes. `False` fires on attribute-only updates too. A [`ComparisonCondition`](filtering.md) (e.g., `C.Increased()`) compares old and new values. |
| `changed_from` | `ChangeType` | not set | Filters on the previous state value. Accepts a raw value, callable, or condition. Compares raw HA state strings. |
| `changed_to` | `ChangeType` | not set | Filters on the new state value. Accepts a raw value, callable, or condition. Compares raw HA state strings. |
| `where` | `Predicate \| Sequence[Predicate] \| None` | `None` | Additional predicates applied after value filters. See [Filtering & Predicates](filtering.md). |
| `immediate` | `bool` | `False` | Fires with the current state on registration, then on every subsequent change. Not supported with glob patterns. |
| `duration` | `float \| None` | `None` | Fires only after the state has held for N seconds continuously. Not supported with glob patterns. |

`changed_from` and `changed_to` compare **raw HA state strings** (`"on"`, `"off"`, `"72.5"`), not typed values from the state registry.

`immediate=True` and `duration` both raise `ValueError` when `entity_id` contains glob characters.

**Compatible [DI annotations](dependency-injection.md)**

| Annotation | Provides |
|---|---|
| `D.StateNew[T]` | New state object, converted to type `T`. Raises if absent. |
| `D.StateOld[T]` | Previous state object, converted to type `T`. Raises if absent. |
| `D.MaybeStateNew[T]` | New state object or `None` if not present. |
| `D.MaybeStateOld[T]` | Previous state object or `None` if not present. |
| `D.EntityId` | Entity ID string. Raises if absent. |
| `D.MaybeEntityId` | Entity ID string or missing-value sentinel. |
| `D.Domain` | Domain string (e.g., `"light"`). Raises if absent. |
| `D.MaybeDomain` | Domain string or missing-value sentinel. |
| `D.TypedStateChangeEvent[T]` | Full event with new/old states converted to type `T`. |
| `D.EventContext` | HA event context (user_id, parent_id, etc.). |

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_state_change.py:immediate"
```

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_state_change.py:duration"
```

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_state_change.py:changed_to"
```

## `on_attribute_change(entity_id, attr)`

Fires when a specific attribute of an entity changes. `entity_id` accepts glob patterns; `attr` does not.

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_attribute_change.py:basic"
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `entity_id` | `str` | — | Entity ID or glob pattern to match. |
| `attr` | `str` | — | Attribute name to monitor (e.g., `"volume_level"`). |
| `changed` | `bool \| ComparisonCondition` | `True` | `True` fires only when the attribute value changes. `False` fires on any state event for the entity. |
| `changed_from` | `ChangeType` | not set | Filters on the previous attribute value. |
| `changed_to` | `ChangeType` | not set | Filters on the new attribute value. |
| `where` | `Predicate \| Sequence[Predicate] \| None` | `None` | Additional predicates. |
| `immediate` | `bool` | `False` | Fires with the current attribute value on registration. Not supported with glob patterns. |
| `duration` | `float \| None` | `None` | Fires only after the attribute has held the value for N seconds. Not supported with glob patterns. |

`changed_from` and `changed_to` compare the **attribute value**, not the entity's main state string.

`changed=False` fires on every state event for the entity, even when the monitored attribute did not change. `on_state_change` with `changed=False` provides that broader behavior.

**Compatible [DI annotations](dependency-injection.md)**

Same as [`on_state_change`](#on_state_changeentity_id).

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_attribute_change.py:changed_from_to"
```

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_attribute_change.py:immediate"
```

## `on_call_service(domain, service)`

Fires when Home Assistant calls a service.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/non_state_call_service.py"
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `domain` | `str \| None` | `None` | Service domain to match (e.g., `"light"`). `None` matches all domains. |
| `service` | `str \| None` | `None` | Service name to match (e.g., `"turn_on"`). `None` matches all services in the domain. |
| `where` | `Predicate \| Sequence[Predicate] \| Mapping[str, ChangeType] \| None` | `None` | Additional predicates, or a dict for service data matching. |

`where=` accepts a plain `dict` mapping service data fields to expected values. `{"entity_id": "light.kitchen"}` matches only calls targeting `light.kitchen`. This dict form is unique to `on_call_service`. `on_service_registered` does not support it.

No `changed`, `changed_from`, `changed_to`, `immediate`, or `duration` parameters.

**Compatible [DI annotations](dependency-injection.md)**

| Annotation | Provides |
|---|---|
| `D.EntityId` | Entity ID from the service call. Raises if absent. |
| `D.MaybeEntityId` | Entity ID or missing-value sentinel. |
| `D.EventContext` | HA event context. |

## `on_service_registered(domain, service)`

Fires when Home Assistant registers a new service. Same parameter shape as `on_call_service`, with one difference. `where=` accepts only predicates, not a dict.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `domain` | `str \| None` | `None` | Domain to match. |
| `service` | `str \| None` | `None` | Service name to match. |
| `where` | `Predicate \| Sequence[Predicate] \| None` | `None` | Additional predicates. |

## `on_component_loaded(component)`

Fires when Home Assistant finishes loading a component.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `component` | `str \| None` | `None` | Component name to match (e.g., `"light"`). `None` matches all components. |
| `where` | `Predicate \| Sequence[Predicate] \| None` | `None` | Additional predicates. |

## Home Assistant Lifecycle Methods

Three shorthands delegate to `on_call_service("homeassistant", ...)`.

| Method | Equivalent |
|---|---|
| `on_homeassistant_start(handler, ...)` | `on_call_service("homeassistant", "start", ...)` |
| `on_homeassistant_stop(handler, ...)` | `on_call_service("homeassistant", "stop", ...)` |
| `on_homeassistant_restart(handler, ...)` | `on_call_service("homeassistant", "restart", ...)` |

All three accept `handler`, `where`, `kwargs`, `name`, and `**opts` (the shared timing parameters). They do not expose `on_error` directly. Per-registration error handling requires `on_call_service` directly.

## `on(topic)`

Subscribes to any raw event topic string.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/non_state_raw_topic.py"
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `topic` | `str` | — | The exact event topic string to subscribe to. |
| `where` | `Predicate \| Sequence[Predicate] \| None` | `None` | Additional predicates. |

`on()` does not support `immediate`, `duration`, `changed`, `changed_from`, or `changed_to`. All shared timing parameters (`debounce`, `throttle`, `once`, `timeout`, `timeout_disabled`) are accepted. Internal topics used by Hassette shorthands (WebSocket events, app state events) are also accessible via `on()` for raw topic access.

## App and Connection Events

### `on_app_state_changed` and shorthands

`on_app_state_changed` fires when any app instance transitions to a new [`ResourceStatus`][hassette.types.enums.ResourceStatus]. Two shorthands cover the most common cases.

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_app_events.py:app_state_changed"
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `app_key` | `str \| None` | `None` | Filters to a specific app. `None` matches all apps. |
| `status` | `ResourceStatus \| None` | `None` | Filters to a specific status. `None` matches all status transitions. |
| `where` | `Predicate \| Sequence[Predicate] \| None` | `None` | Additional predicates. |

`on_app_running(app_key=...)` delegates to `on_app_state_changed(status=ResourceStatus.RUNNING)`.
`on_app_stopping(app_key=...)` delegates to `on_app_state_changed(status=ResourceStatus.STOPPING)`.

The shorthands do not expose `on_error` directly. Per-listener error handling requires `on_app_state_changed` with `on_error=` directly.

### `on_websocket_connected` and `on_websocket_disconnected`

Fire when the Hassette WebSocket connection to Home Assistant opens or closes.

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_app_events.py:websocket"
```

Both methods accept `handler`, `where`, `kwargs`, `name`, and `**opts`. Neither exposes `on_error`. Both delegate to `on()` internally.

## Error Handling

### App-level handler

`bus.on_error(handler)` registers a fallback called when any listener on the bus raises. The handler receives a [`BusErrorContext`][hassette.bus.error_context.BusErrorContext].

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/bus_error_handler_app.py"
```

### Per-registration handler

`on_error=` on a registration overrides the app-level fallback for that listener only.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/bus_error_handler_per_reg.py"
```

**`BusErrorContext` fields**

| Field | Type | Description |
|---|---|---|
| `exception` | `BaseException` | The raised exception, with `__traceback__` chain intact. |
| `traceback` | `str` | Full formatted traceback string. Always non-empty. |
| `topic` | `str` | The event topic the listener was registered on. |
| `listener_name` | `str` | Human-readable listener identity string. |
| `event` | `Event[Any]` | The event being processed when the exception occurred. |
| `execution_id` | `str \| None` | UUIDv7 identifying the execution that failed, or `None`. |

Error handlers run as fire-and-forget tasks. Handlers that start near app shutdown may be cancelled before they complete. Error handlers are not a reliable delivery channel during system teardown.

`on_error` is not available on `on_homeassistant_start`, `on_homeassistant_stop`, `on_homeassistant_restart`, `on_app_running`, `on_app_stopping`, `on_websocket_connected`, or `on_websocket_disconnected`. Per-registration error handling on these events requires the underlying method (`on_call_service`, `on_app_state_changed`, or `on()`) directly.

## Timeout Configuration

`timeout=` overrides the global `event_handler_timeout_seconds` for a single listener. `timeout_disabled=True` removes timeout enforcement entirely for that listener.

```python
--8<-- "pages/core-concepts/bus/snippets/bus_timeouts.py"
```

The global default comes from `event_handler_timeout_seconds` in `hassette.toml`. A listener with `timeout=None` (the default) inherits that value. Setting `timeout=30.0` overrides the global only for that listener. Other listeners are unaffected.

`timeout_disabled=True` is appropriate for handlers that legitimately run longer than the global limit. A backup job triggered by a boolean is a typical case. `timeout=` is appropriate when a specific handler needs a tighter or looser bound than the global.

## Registration

### `name=` requirement

Every registration method requires `name=`. Omitting it raises `ListenerNameRequiredError` at call time.

```python
--8<-- "pages/core-concepts/bus/snippets/bus_registration_identity.py:registration_identity"
```

The `name` forms the natural key `(app_key, instance_index, name, topic)`. Two registrations with the same name on the same topic within a session raise `DuplicateListenerError`. Across sessions (app restart), the same name and topic performs an upsert. The existing listener record is updated, not duplicated.

### Synchronous completion

Registration completes before the awaited call returns. `sub.listener.db_id` is a valid integer immediately.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/bus_subscription_patterns.py:await_persistence"
```

### Cancel-then-resubscribe

Cancelling a subscription and registering a new one is deterministic. The old handler is removed before the new registration begins. No overlap, no gap.

```python
--8<-- "pages/core-concepts/bus/snippets/handlers/bus_subscription_patterns.py:resubscribe"
```

## Synchronous Usage

`self.bus.sync` exposes `BusSyncFacade`, which wraps every `Bus` registration method as a blocking synchronous call. `AppSync` lifecycle hooks, which run in a worker thread outside the event loop, register listeners through this facade. Calling methods on `self.bus.sync` from within the event loop raises `RuntimeError`. All `name=` requirements and collision rules apply identically.

## See Also

- [Writing Handlers](handlers.md) — handler signature patterns and DI annotation usage
- [Filtering & Predicates](filtering.md) — `where=`, `P.*` predicates, and `C.*` conditions
- [Dependency Injection](dependency-injection.md) — full `D.*` annotation reference
- [Bus Overview](index.md) — bus overview and getting started
