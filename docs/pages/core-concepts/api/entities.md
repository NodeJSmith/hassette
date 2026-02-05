# Retrieving Entities & States

The API allows you to retrieve the current state of any entity in Home Assistant.

## Terminology

Hassette uses precise terminology:

- **State Value**: The raw value (e.g., `"on"`, `"23.5"`).
- **State**: A snapshot including value, attributes, and last changed time.
- **Entity**: A rich object wrapping the state with helper methods (e.g., `.turn_off()`).

## Retrieving States

Use `get_state` to retrieve a typed state object.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_state.py"
```

### Raw vs Typed

Most methods return typed Pydantic models. You can use `get_state_raw` if you want a dict.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_state_raw.py"
```

### Checking Existence

Use `get_state_or_none` to safely check for an entity.

```python
--8<-- "pages/core-concepts/api/snippets/api_check_existence.py"
```

## Retrieving Multiple States

Use `get_states` to fetch all states at once. This is more efficient than calling `get_state` in a loop.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_states.py"
```

## Entities

Entities wrap the state object. Currently `BaseEntity` and `LightEntity` are available.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_entity.py"
```

## See Also

- [Calling Services](services.md) - Invoke Home Assistant services
- [Utilities & History](utilities.md) - Templates, history, and advanced features
- [States](../states/index.md) - State management and caching
