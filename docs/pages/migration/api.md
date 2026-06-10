# API Calls

!!! note "Coming from synchronous AppDaemon?"
    Every Hassette lifecycle method and handler is `async def`, and calls to `self.api` need `await` in front — `await` pauses the handler until the network call finishes. Reads from `self.states` (the local cache) are plain synchronous calls. [Migration Concepts](concepts.md#async-vs-sync) covers the model.

## Getting Entity State

AppDaemon's `self.get_state()` reads from an internal cache and returns raw strings or dicts. Hassette provides two options. `self.states` is a local cache for most reads. `self.api.get_state()` forces a fresh read from Home Assistant when the cache is not enough.

### AppDaemon

```python
--8<-- "pages/migration/snippets/api_appdaemon_get_state.py"
```

Returns a raw dict. No type information. No autocomplete.

### Hassette: State Cache (recommended)

`self.states` holds a local copy of all entity states, kept current via WebSocket events. No `await` needed. The returned object is typed to the entity domain.

```python
--8<-- "pages/migration/snippets/api_hassette_states_cache.py"
```

Three access patterns:

| Pattern | Returns |
|---|---|
| `self.states.light.get("light.kitchen")` | `LightState \| None` |
| `self.states[states.LightState].get("light.kitchen")` | `LightState \| None`, for any domain |
| `for entity_id, state in self.states.light` | Iterates all cached lights |

Use `self.states` for any read inside a handler or scheduled task. The cache is always up-to-date.

### Hassette: Direct API Call

For a guaranteed fresh read from Home Assistant:

```python
--8<-- "pages/migration/snippets/api_hassette_get_state_api.py"
```

`self.api.get_state()` hits the HA REST API and requires `await`. Use it when the cache is not reliable, such as during initialization before the first state change event.

## Calling Services

AppDaemon uses a single `domain/service` string. Hassette splits them into two arguments.

=== "AppDaemon"

    ```python
    --8<-- "pages/migration/snippets/api_appdaemon_call_service.py"
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/api_hassette_call_service.py"
    ```

!!! warning "Don't forget `await`"
    Without `await`, the call appears to succeed but the service never runs — Python just hands back an unexecuted coroutine. If service calls have no effect, check that every call site has `await`.

Two signature differences from AppDaemon: the entity belongs in the `target` dict (`target={"entity_id": "light.kitchen"}`) rather than AppDaemon's bare `entity_id=` keyword, and Hassette handlers don't take `**kwargs` — event data arrives through typed parameters instead (see [Bus & Events](bus.md)).

## Setting States

=== "AppDaemon"

    ```python
    --8<-- "pages/migration/snippets/api_appdaemon_set_state.py"
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/api_hassette_set_state.py"
    ```

## Firing Events

=== "AppDaemon"

    ```python
    self.fire_event("custom_event", entity_id="sensor.test", value=42)
    ```

=== "Hassette"

    ```python
    await self.api.fire_event("custom_event", {"entity_id": "sensor.test", "value": 42})
    ```

`fire_event` sends an event to Home Assistant's event bus. The event data is a dict in Hassette (AppDaemon accepts kwargs). For broadcasting between apps in the same Hassette process without leaving the framework, use [`self.bus.emit()`](../core-concepts/bus/handlers.md#cross-app-communication) instead.

## Logging

AppDaemon provides `self.log()` and `self.error()`. Hassette uses Python's standard `logging` module via `self.logger`.

=== "AppDaemon"

    ```python
    --8<-- "pages/migration/snippets/api_appdaemon_logging.py"
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/api_logging.py"
    ```

`self.logger` automatically includes the app instance name, calling method, and line number in every log line. Use `%s`-style formatting rather than f-strings. The string is only constructed if the log level is active.

## See Also

- [States](../core-concepts/states/index.md), state cache and state models
- [API Methods](../core-concepts/api/methods.md), reading state and calling services
- [API Overview](../core-concepts/api/index.md), full API reference
