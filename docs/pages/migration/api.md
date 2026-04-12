# API Calls

This page covers how to migrate AppDaemon API access to Hassette's `self.api` and `self.states` attributes.

## Overview

AppDaemon provides synchronous API access via methods on `self`: `self.get_state()`, `self.call_service()`, `self.set_state()`. Responses are raw strings or dicts.

Hassette provides two ways to access state:

1. **`self.states`** — a local state cache that stays up-to-date via WebSocket events. This is the preferred way to read entity state and is most similar to AppDaemon's `self.get_state()` behavior.
2. **`self.api`** — direct async API calls to Home Assistant. Use this for writes (`call_service`, `set_state`) and for cases where you specifically need a fresh read from HA.

## Getting Entity State

### AppDaemon

AppDaemon maintains an internal cache and `self.get_state()` reads from it. You can get just the state string or the full dict with attributes:

```python
--8<-- "pages/migration/snippets/api_appdaemon_get_state.py"
```

Returns a raw dict with string values. No type safety.

### Hassette: State Cache (recommended)

The `self.states` attribute provides immediate access to all entity states without API calls. It is updated automatically via state change events — no `await` needed:

```python
--8<-- "pages/migration/snippets/api_hassette_states_cache.py"
```

Access patterns:

| Pattern | What it returns |
|---------|----------------|
| `self.states.light.get("light.kitchen")` | A `LightState` object, or `None` if not found |
| `for entity_id, state in self.states.light` | Iterates over all light entities in cache |
| `self.states[states.LightState].get("light.kitchen")` | Typed access for any domain |

### Hassette: Direct API Call

For cases where you need to force a fresh read from Home Assistant (rare):

```python
--8<-- "pages/migration/snippets/api_hassette_get_state_api.py"
```

!!! note "Type narrowing"
    `get_state()` is annotated as returning `BaseState`. Use type narrowing or casting to tell the type checker the specific state type you expect.

**When to use each approach:**

- **`self.states`** (recommended): For reading current state in event handlers, scheduled tasks, or any time you need quick access to entity state. The cache is automatically kept up-to-date via state change events.
- **`self.api.get_state()`**: Only when you specifically need a fresh read from Home Assistant (rare) or if you're outside the normal app lifecycle.

## Calling Services

### AppDaemon

```python
def my_callback(self, **kwargs):
    self.call_service("light/turn_on", entity_id="light.kitchen", brightness=200)

    # or use the helper
    self.turn_on("light.kitchen", brightness=200)
```

AppDaemon uses a `domain/service` string format. The call is synchronous.

### Hassette

```python
--8<-- "pages/migration/snippets/api_hassette_call_service.py"
```

Hassette uses separate `domain` and `service` arguments. The call is async. Helpers like `turn_on()` are also available.

!!! warning "Don't forget `await`"
    Forgetting `await` on an API call returns a coroutine object instead of executing the call. If your service calls appear to do nothing, check that you have `await` on each one.

## Setting States

=== "AppDaemon"

    ```python
    self.set_state("sensor.custom", state="42", attributes={"unit": "widgets"})
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/api_hassette_set_state.py"
    ```

## Logging

AppDaemon provides `self.log()` and `self.error()`. Hassette uses Python's standard `logging` module via `self.logger`:

=== "AppDaemon"

    ```python
    self.log("This is a log message")
    self.log(f"Value: {value}")
    self.error("Something went wrong")
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/api_logging.py"
    ```

The Hassette logger automatically includes the instance name, calling method, and line number in every log line. Use `%s`-style formatting rather than f-strings to defer string construction until needed.

## Full State Migration Example

The following example shows the complete migration of a state-reading pattern:

```python
--8<-- "pages/migration/snippets/api_migration_getting_states.py"
```

## See Also

- [API Overview](../core-concepts/api/index.md) — the full API reference
- [Entities & States](../core-concepts/api/entities.md) — typed entity state access
- [Services](../core-concepts/api/services.md) — calling HA services
- [States](../core-concepts/states/index.md) — state cache and state models
