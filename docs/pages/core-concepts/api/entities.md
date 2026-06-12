# Retrieving Entities & States

Use the API to retrieve the current state of any entity in Home Assistant.

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

Entity service methods (`entity.turn_on()`, `entity.set_humidity(...)`, etc.) must be awaited. A forgotten `await` produces a [`HassetteForgottenAwaitWarning`][hassette.exceptions.HassetteForgottenAwaitWarning] — see [Forgotten `await`](../../troubleshooting.md#forgotten-await).

## API vs StateManager

The API methods above fetch states directly from Home Assistant over the network. Prefer `self.states` instead — it gives you instant, synchronous access from a local cache:

- `self.states.light["kitchen"]` — Domain-specific typed access
- `self.states.get("light.kitchen")` — Direct lookup by entity ID, no `await` needed

!!! warning "Prefer domain access for better typing"

    When you know the domain at write time, use `self.states.light` instead of `self.states.get()`. Domain access returns fully typed state objects (e.g., `LightState`) with autocomplete for domain-specific attributes. `get()` returns `BaseState | None`, so you lose attribute-level type safety.

Use the API when you need guaranteed fresh data from Home Assistant — otherwise, `self.states` is faster and simpler.

See [States](../states/index.md) for full details.

## See Also

- [Calling Services](services.md) - Invoke Home Assistant services
- [Utilities & History](utilities.md) - Templates, history, and advanced features
- [States](../states/index.md) - State management and caching
