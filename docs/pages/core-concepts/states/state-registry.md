# State Registry

`StateRegistry` maps Home Assistant domains to Python state model classes. When state data arrives as an untyped dictionary, the registry determines which `BaseState` subclass handles conversion.

Most apps never interact with the registry directly. The [DI system](../bus/dependency-injection.md) and [`self.states`](index.md) use it automatically on every state event.

This page is relevant when overriding a default domain mapping, writing a custom state class, or debugging an unexpected state type at runtime.

```python
--8<-- "pages/advanced/snippets/state-registry/raw_data_example.py"
```

## How Registration Works

Any class that inherits from `BaseState` and declares a `domain: Literal["domain_name"]` field annotation registers itself automatically at class definition time. No explicit registration call is needed.

`BaseState.__init_subclass__` runs when Python evaluates the class body. It calls `get_domain()`, which reads the `Literal` type argument from the `domain` field annotation. If a domain string is found, `register_state_converter` records the class in the registry under that domain.

Classes without a `domain` annotation are silently skipped.

??? note "Implementation: `__init_subclass__` and `register_state_converter`"

    `BaseState.__init_subclass__` calls `register_state_converter(cls, domain=cls.get_domain())`, which in turn calls `StateRegistry.register()`.

    `get_domain()` uses `typing.get_args()` to extract the string from a `Literal["domain_name"]` annotation on the `domain` field. A `ClassVar[str]` annotation or a plain `str` annotation will not register. The annotation must be `Literal["domain_name"]`.

    ```python
    --8<-- "pages/advanced/snippets/state-registry/automatic_registration.py"
    ```

## Domain Lookup

`StateRegistry.resolve(domain=...)` returns the registered state class for a domain, or `None` if no class is registered for that domain.

```python
--8<-- "pages/advanced/snippets/state-registry/domain_lookup.py"
```

The `None` return for an unregistered domain is intentional. `try_convert_state` handles the fallback to `BaseState` when `resolve` returns `None`.

## Overriding a Domain Mapping

A custom class declared with the same `Literal` domain as a built-in replaces the existing mapping in the registry. The override takes effect at class definition time, so placing the class after the import of the original is sufficient.

```python
--8<-- "pages/advanced/snippets/state-registry/domain_override.py"
```

The registry silently replaces the previous mapping. All subsequent state events for `sensor` entities produce `CustomSensorState` instances.

When direct registry access is needed outside an app, `STATE_REGISTRY` is available as a top-level import: `from hassette import STATE_REGISTRY`.

## The Conversion Flow

When state data arrives from Home Assistant, `StateRegistry` and `TypeRegistry` cooperate to produce a typed object.

1. Raw dict arrives from Home Assistant:
   ```python
   --8<-- "pages/advanced/snippets/state-registry/flow_raw_input.py"
   ```

2. `StateRegistry.resolve(domain="time")` returns `TimeState`.

3. Pydantic validation begins on `TimeState`.

4. The `_validate_domain_and_state` model validator reads `value_type` and delegates to `TypeRegistry`.

5. `TypeRegistry` converts `"12:01:01"` (str) to `whenever.Time`.

6. Validation completes with a fully typed state object:
   ```python
   --8<-- "pages/advanced/snippets/state-registry/flow_converted_output.py"
   ```

The `value_type` ClassVar declares which Python types the `state` field accepts. `TypeRegistry` performs the actual conversion from raw string to that type. `StateRegistry` answers "which class?"; `TypeRegistry` answers "which type for the value?". [Type Registry](type-registry.md) covers value conversion in detail.

```python
--8<-- "pages/advanced/snippets/state-registry/value_type_example.py"
```

## Union Type Support

`StateRegistry` resolves union-typed DI annotations by checking each type's domain against the incoming entity's domain.

```python
--8<-- "pages/advanced/snippets/state-registry/union_type_support.py"
```

For `D.StateNew[states.SensorState | states.BinarySensorState]`, the DI system extracts the domain from the entity ID. It checks each type in the union and selects the one whose `Literal` domain matches. When no type in the union matches, conversion falls back to `BaseState`.

## Error Handling

`try_convert_state` raises specific exceptions for distinct failure modes. Catching these allows apps to distinguish a malformed payload from a bad entity ID or a type mismatch.

### `InvalidDataForStateConversionError`

Raised when the state data is malformed or missing required fields. For example, the input is `None` or contains an `event` key instead of a state dict.

```python
--8<-- "pages/advanced/snippets/state-registry/error_invalid_data.py"
```

### `InvalidEntityIdError`

Raised when the `entity_id` field is missing, not a string, or lacks a `.` separator between domain and entity name.

```python
--8<-- "pages/advanced/snippets/state-registry/error_invalid_entity_id.py"
```

### `UnableToConvertStateError`

Raised when Pydantic validation fails for both the resolved state class and the `BaseState` fallback.

```python
--8<-- "pages/advanced/snippets/state-registry/error_unable_to_convert.py"
```

## See Also

- [Type Registry](type-registry.md): value-level type conversion during state validation
- [Custom States](custom-states.md): defining state classes that register automatically
- [Dependency Injection](../bus/dependency-injection.md): how `D.StateNew[T]` uses the registry
- [States](index.md): the `self.states` cache that sits above the registry
