# Subscription Methods

[`Bus`][hassette.bus.Bus] provides typed subscription methods for each event category Home Assistant and Hassette emit. Each method returns a [`Subscription`][hassette.bus.listeners.Subscription] handle. Calling `sub.cancel()` removes the listener.

All registration methods are `async` and must be awaited. See [Registration](#registration) for what that guarantees.

!!! warning "Forgetting `await` registers nothing"
    A subscription call without `await` returns a coroutine object and registers no listener — the handler never fires, and no error is raised at the call site. Python logs `RuntimeWarning: coroutine 'Bus.on_state_change' was never awaited` when the coroutine is garbage-collected, but the message is easy to miss. When a handler never fires, check the registration is awaited, then confirm the listener exists with `hassette listener --app <key>`.

## Shared Parameters

Every subscription method accepts these parameters. Individual method tables below list only method-specific parameters.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `handler` | `HandlerType` | — | The function called when the event matches. See [Writing Handlers](handlers.md). |
| `name` | `str \| None` | `None` | Required. Identifies this listener in logs and the monitoring UI. Must be unique per app instance and topic. Omitting raises `ListenerNameRequiredError`. |
| `on_error` | `BusErrorHandlerType \| None` | `None` | Per-listener error handler. Overrides the app-level handler set via `bus.on_error()`. Available on `on_state_change`, `on_attribute_change`, `on_call_service`, `on_service_registered`, `on_component_loaded`, `on_app_state_changed`, and `on()`. |
| `timeout` | `float \| None` | `None` | Per-listener timeout in seconds. If the handler runs longer, it is cancelled. `None` inherits `event_handler_timeout_seconds` from [`hassette.toml`](../configuration/index.md). |
| `timeout_disabled` | `bool` | `False` | Disables timeout enforcement for this listener regardless of config. |
| `debounce` | `float \| None` | `None` | Delays the handler until events have been quiet for N seconds. Each new event resets the timer. |
| `throttle` | `float \| None` | `None` | Limits the handler to one invocation per N seconds. Events during the cooldown are dropped. |
| `once` | `bool` | `False` | Fires the handler exactly once, then cancels the subscription. |
| `kwargs` | `Mapping \| None` | `None` | Keyword arguments passed to the handler at invocation time. |
| `if_exists` | `"error"` \| `"skip"` \| `"replace"` | `"error"` | Behavior when a listener with the same name and topic already exists. See [Idempotent Registration](#idempotent-registration). |
| `mode` | `"single"` \| `"restart"` \| `"queued"` \| `"parallel"` \| `None` | tier-aware | Overlap behavior when a trigger fires while the handler is still running. See [Execution Modes](execution-modes.md). |

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

`D` is the dependency-injection module (`from hassette import D`). Annotating a handler parameter with one of these types makes Hassette extract and convert that piece of the event automatically. Each method section below lists the annotations its events support.

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

Fire with the current value on registration, then on each subsequent change:

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_state_change.py:immediate"
```

Fire only after the state has held for a set duration:

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_state_change.py:duration"
```

Fire only on a specific state transition:

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_state_change.py:changed_to"
```

## `on_attribute_change(entity_id, attr)`

Fires when a specific attribute of an entity changes. `entity_id` accepts glob patterns.

!!! warning "`attr` does not support glob patterns"
    The `attr` parameter matches a single attribute name exactly. Glob characters in `attr` are treated as literal characters, not patterns. [Predicates](filtering.md) handle multi-attribute matching.

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

All three accept `handler`, `where`, `kwargs`, `name`, and the [shared parameters](#shared-parameters) (`debounce`, `throttle`, `once`, `timeout`, `timeout_disabled`). They do not expose `on_error` directly. Per-registration error handling requires `on_call_service` directly.

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

## `wait_for(topic)`

Suspends the calling coroutine until an event matching `topic` and `where` is dispatched, then returns that event. Every other registration method returns a `Subscription` and requires a handler function; `wait_for` returns the matched `Event` directly and needs no handler — it's the primitive for sequential automation logic, not for a standing subscription.

```python
--8<-- "pages/core-concepts/bus/snippets/methods/wait_for.py:basic"
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `topic` | `str` | — | The exact event topic string to match. Glob patterns work the same as `on()`. |
| `where` | `Predicate \| Sequence[Predicate] \| None` | `None` | Additional predicates applied to each candidate event. |
| `timeout` | `float \| None` | — | Mandatory. Seconds to wait before raising `asyncio.TimeoutError`. Pass `None` for no timeout — the wait persists until a match or listener removal. |
| `name` | `str \| None` | `None` | Optional. When omitted, an auto-generated name (`_wait_for_<hex id>`) is used for the underlying listener registration. |

Returns the matching `Event[Any]`.

Raises `asyncio.TimeoutError` when no matching event arrives within `timeout` seconds. Raises `asyncio.CancelledError` when the underlying listener is removed before a match — Bus shutdown, or an explicit `Subscription.cancel()` reaching the same registration.

`wait_for` only matches events dispatched *after* the call is awaited. An entity that already reports the target value when `wait_for` starts does not resolve the wait — only a subsequent event does. `self.states.get()` covers the "already true" case; call it first when "already true or wait" is the desired behavior.

`wait_for` skips `guard_await`, the wrapper the other registration methods use to catch a forgotten `await`. It returns an `Event`, not a `Subscription`, so there's no listener handle to silently drop — Python's own `coroutine was never awaited` warning already covers this case.

!!! warning "`wait_for` holds resources for the entire wait — prefer a finite `timeout`"
    A pending `wait_for` ties up shared resources until it resolves, times out, or is cancelled. Three cases matter:

    - **Dispatch slots.** A handler that calls `wait_for` holds its dispatch slot (`max_concurrent_dispatches`, default 50) for the full duration of the wait. Enough concurrent handlers parked in `wait_for` exhaust all slots and block all new event delivery — including the events the waiters need. The default `mode="single"` helps here — it caps each listener to one in-flight invocation, so a single listener can only park one `wait_for` at a time. Avoid `mode="parallel"` on handlers that call `wait_for`, since every concurrent re-fire spawns another parked wait. Use a finite `timeout` and keep the total number of concurrent `wait_for` calls well below the dispatch limit.
    - **Sync worker threads.** `self.bus.sync.wait_for(topic, timeout=None)` pins one of the small, fixed `SyncExecutor` pool threads with no cancellation path. Always use a finite `timeout` from sync code.
    - **Shutdown race.** If `remove_all_listeners()` runs while a `wait_for` registration is still completing its DB write (~1ms), the listener misses the sweep. With a finite `timeout` the wait times out normally; with `timeout=None` it hangs until process exit. The window is extremely narrow in practice.

### Composition Recipes

`wait_for` composes with `self.api.call_service()` to write automations that wait for a physical effect before moving on. Two patterns cover most cases.

#### Arm before fire

The `wait_for` task starts *before* the service call, then the caller awaits it after:

```python
--8<-- "pages/core-concepts/bus/snippets/methods/wait_for.py:arm_before_fire"
```

The ordering matters. `asyncio.create_task` schedules `wait_for` and starts registering its listener immediately, but registration is not guaranteed to complete before `call_service`'s WebSocket round-trip triggers the event — the listener registration writes to the local SQLite telemetry database (~1ms), which in practice finishes well before the round-trip to Home Assistant (~10ms or more), but the two are not synchronized.

!!! warning "This race is narrowed, not closed"
    Arming the wait first shrinks the window between registration and the triggering call — it does not close it. Closing it fully requires a primitive that awaits registration before firing the action, tracked as #2286 and not yet available. Until that ships, arm-before-fire is the best available pattern; a stricter primitive is only worth waiting for when the residual race actually matters for a given automation.

#### Confirm started, then wait for idle

Media players and similar entities sit in an idle-like state most of the time, so the target state a caller wants to wait for is frequently the *current* state too. A single `wait_for(where=P.StateTo("idle"))` armed right after calling `media_play` can resolve against a state_changed event that still reports `"idle"` — a refresh or attribute-only update that carries the pre-play value — well before playback has actually finished. That event is real, dispatched after registration, and matches the predicate; it just isn't the one the automation is waiting for. The after-registration guarantee described above protects against the literal pre-existing state, not against a *different* idle event that arrives before the action completes.

The fix is two waits instead of one: confirm the entity left idle (proof the action actually started), then wait for it to return:

```python
--8<-- "pages/core-concepts/bus/snippets/methods/wait_for.py:two_stage"
```

The first `wait_for` uses `~P.StateTo("idle")` — anything other than idle — armed before the service call, same arm-before-fire ordering as above. Once that resolves, the entity is confirmed off idle, so the second `wait_for(where=P.StateTo("idle"))` is now waiting on a transition that can only mean the action actually finished, not a stray restatement of the pre-existing value.

!!! note "This is the bedtime-automation bug"
    Skipping the first stage was the original production failure this primitive was built to prevent: a media-player automation that called `media_play` and immediately waited for `"idle"` resolved instantly against the not-yet-changed state, and the rest of the automation ran before playback had even started.

## App and Connection Events

### `on_app_state_changed` and shorthands

`on_app_state_changed` fires when any app instance transitions to a new [`ResourceStatus`][hassette.types.enums.ResourceStatus] (e.g., `RUNNING`, `STOPPING`, `STOPPED`, `FAILED`). Two shorthands cover the most common cases.

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_app_events.py:app_state_changed"
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `app_key` | `str \| None` | `None` | Filters to a specific app (the identifier from [`hassette.toml`](../configuration/index.md)). `None` matches all apps. |
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

### `on_hassette_service_status` and shorthands

`on_hassette_service_status` fires when a Hassette background service (WebSocket, database, bus, scheduler) transitions to a new [`ResourceStatus`][hassette.types.enums.ResourceStatus]. Most apps never need this — Hassette restarts failed services on its own. It exists for apps that pause work or alert when a service goes down. Three shorthands cover the common cases: `on_hassette_service_failed` (status `FAILED`), `on_hassette_service_crashed` (status `CRASHED`), and `on_hassette_service_started` (status `RUNNING`).

```python
--8<-- "pages/core-concepts/bus/snippets/methods/on_service_events.py:service"
```

All four accept `handler`, `where`, `kwargs`, `name`, and `**opts`. [Service supervision](../internals/lifecycle.md) explains when each status fires.

## Error Handling

### App-level handler

`bus.on_error(handler)` registers a fallback called when any listener on the bus raises — either in the handler itself or in a `where=` predicate. This call is synchronous — no `await` needed. The handler receives a [`BusErrorContext`][hassette.bus.error_context.BusErrorContext].

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

The `name` forms a natural key together with the app identifier, instance index, and topic. Two registrations with the same name on the same topic within a session raise `DuplicateListenerError`. Across sessions (app restart), the same name and topic performs an upsert — Hassette persists listener metadata to a local SQLite [telemetry database](../database-telemetry.md), and the existing record is updated, not duplicated.

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

### Idempotent registration

Listener names must be unique per app instance and topic. Registering a second listener with the same name and topic raises `DuplicateListenerError` by default. The `if_exists` parameter controls this behavior.

| Value | Behavior |
|---|---|
| `"error"` (default) | Raises `DuplicateListenerError` when a listener with the same name and topic already exists. |
| `"skip"` | Returns the existing subscription when the new registration's configuration matches. Raises `ValueError` naming the changed fields when configurations differ. Two listeners match when they share the same handler, filter predicate, timing options (`once`, `debounce`, `throttle`, `timeout`, `timeout_disabled`, `priority`), handler kwargs, per-registration error handler, and duration configuration. The returned subscription is the same live handle as the original registrant's — cancelling it removes the listener for all holders. |
| `"replace"` | Cancels the existing listener and registers the new one. The new configuration does not need to match the old one. |

`if_exists` matters most in `on_initialize`, which re-runs on app reload.

```python
--8<-- "pages/core-concepts/bus/snippets/bus_idempotent_registration.py:idempotent_registration"
```

`"skip"` works when the listener configuration is stable across reloads. `"replace"` is the right choice when the handler, filter, or timing options may change between reloads.

```python
--8<-- "pages/core-concepts/bus/snippets/bus_idempotent_registration.py:replace_registration"
```

**Key shape: bus vs. scheduler.** The bus resolves `if_exists` per `(name, topic)` — the same name on a different topic is a different listener and does not collide. The scheduler resolves `if_exists` per `name` alone, because job names are unique across the scheduler regardless of trigger type. `if_exists="skip"` on the bus is safe to use when registering the same handler on multiple topics under different names; `if_exists="replace"` on the bus targets exactly the `(name, topic)` pair, not all listeners sharing that name.

!!! note "Lambda filters report drift under `skip`"
    Lambdas and closures compare by identity, not by value. Re-registering "the same" filter built from a fresh lambda reports drift and raises under `if_exists="skip"`. Use a named function or a built-in predicate (from `P.*`) for stable comparison. `if_exists="replace"` is not affected by this constraint.

!!! note "Once-listeners and `if_exists`"
    `once=True` listeners participate in name+topic collision tracking like durable listeners. Two `once=True` registrations with the same name and topic raise `DuplicateListenerError` by default. Pass `if_exists="skip"` or `if_exists="replace"` to control the behavior explicitly.

## See Also

- [Writing Handlers](handlers.md): handler signature patterns and DI annotation usage
- [Filtering & Predicates](filtering.md): `where=`, `P.*` predicates, and `C.*` conditions
- [Dependency Injection](dependency-injection.md): full `D.*` annotation reference
- [Bus Overview](index.md): bus overview and getting started
