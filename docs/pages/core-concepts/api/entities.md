# Entities & States

`self.api` retrieves entity state directly from Home Assistant over the network. Three methods cover three levels of detail. The right choice depends on what the calling code does with the result.

The [API overview](index.md) covers when to prefer `self.api` over `self.states`.

## Get the Value

`get_state_value(entity_id)` returns the raw state value for an entity. A **state value** is the string Home Assistant stores in its state machine: `"on"`, `"23.5"`, `"above_horizon"`. No attributes, no timestamps, no type conversion.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_state_value.py"
```

`get_state_value` is the cheapest call when the value is all the code needs.

## Get the Full State

`get_state(entity_id)` returns a **state**, a snapshot of an entity at a point in time. A state includes `.value`, `.attributes`, `.last_changed`, `.last_updated`, and `.context`. The `.value` field is coerced to the domain's Python type. Lights and switches produce `bool`. Numeric sensors produce `float`. Most others remain `str`.

The return type is a [`BaseState`][hassette.models.states.base.BaseState] subclass matched to the entity's domain. `light.kitchen` returns a [`LightState`][hassette.models.states.light.LightState] with typed attribute access.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_state.py"
```

### Optional Lookup

`get_state_or_none(entity_id)` returns `None` instead of raising when the entity does not exist. `entity_exists(entity_id)` returns a plain `bool`.

```python
--8<-- "pages/core-concepts/api/snippets/api_check_existence.py"
```

### Raw Dict

`get_state_raw(entity_id)` returns the untyped `HassStateDict` from the REST response. This suits code that works outside the type registry or that inspects the raw HA payload for debugging.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_state_raw.py"
```

## Get an Entity

`get_entity(entity_id, model)` wraps a state in a `BaseEntity` subclass. An **entity** adds domain-specific action methods to the state snapshot: `turn_on()`, `turn_off()`, `toggle()`, and `refresh()`. The `model` argument specifies which entity class to use.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_entity.py"
```

`get_entity_or_none(entity_id, model)` follows the same pattern as `get_state_or_none`, returning `None` when the entity is not found.

### Refreshing State

`entity.refresh()` re-fetches the entity's state from Home Assistant and updates the entity's `.state` in place. The updated state is also returned.

??? note "Generic Type Parameters"

    `BaseEntity` is generic over two type variables: `StateT` (the `BaseState` subclass) and `StateValueT` (the Python type of `.value`). For `LightEntity`, `StateT` is `LightState` and `StateValueT` is `bool | None`. These parameters are resolved at class definition time. Call sites supply no type arguments. They matter when creating custom entity types that extend `BaseEntity`.

## Fetching Multiple States

`get_states()` retrieves all entities from Home Assistant in a single call and returns them as a list of typed `BaseState` objects. The method skips states that fail to convert and logs an error for each. `get_states_raw()` returns the untyped list.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_states.py"
```

`get_states()` accepts no filtering parameters. Filtering happens in Python after the call.

## Which Method to Use

| Need | Method |
|---|---|
| Just the raw state value | `get_state_value` |
| Typed value, attributes, or timestamps | `get_state` |
| Domain action methods (`turn_on`, `turn_off`, `toggle`) | `get_entity` |

## See Also

- [States](../states/index.md) — local cache for instant, synchronous state access
- [API overview](index.md) — when to use the API vs the state cache
- [Calling Services](services.md) — invoke Home Assistant services directly
