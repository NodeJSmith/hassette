# API Calls

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
    Calling `self.api.call_service()` without `await` returns a coroutine object and does nothing. If service calls appear to have no effect, check that every call site has `await`.

## Setting States

=== "AppDaemon"

    ```python
    --8<-- "pages/migration/snippets/api_appdaemon_set_state.py"
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/api_hassette_set_state.py"
    ```

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
