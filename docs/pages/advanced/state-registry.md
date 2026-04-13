# State Registry

!!! info "Prerequisites"
    This page assumes familiarity with [Custom States](custom-states.md). Read that first if you haven't defined a custom state class yet.

The **StateRegistry** maintains a mapping between Home Assistant domains (like `light`, `sensor`, `switch`) and their corresponding Pydantic state model classes. It enables automatic type conversion when working with state data from Home Assistant.

## When Do I Need This?

**Most apps never need to touch the StateRegistry directly.** The built-in state classes cover all standard Home Assistant domains, and the DI system and `self.states` cache use the registry automatically.

You need this page when:

- You are writing a [custom state class](custom-states.md) for a domain Hassette does not yet know about.
- You want to override the default state class for an existing domain (e.g., to add custom attributes).
- You are seeing unexpected state types at runtime and need to understand how the mapping works.

## What is the State Registry?

When Home Assistant sends state change events, the state data arrives as untyped dictionaries. The StateRegistry allows Hassette to automatically convert these dictionaries into typed Pydantic models based on the entity's domain:

```python
--8<-- "pages/advanced/snippets/state-registry/raw_data_example.py"
```

## How It Works

### Automatic Registration

All classes that inherit from `BaseState` — the root model class that all Hassette state types extend — are registered automatically at class creation time if they have a valid domain. You do not need to call any registration function — defining the class is sufficient.

??? note "Implementation details: `__init_subclass__` hook"
    Registration happens via the `__init_subclass__` hook in `BaseState`, which adds the class to the global `StateRegistry` as soon as the class body is evaluated.

    ```python
    --8<-- "pages/advanced/snippets/state-registry/automatic_registration.py"
    ```

### Domain Lookup

When you need to convert state data, the registry provides lookup functions:

```python
--8<-- "pages/advanced/snippets/state-registry/domain_lookup.py"
```

## Relationship with TypeRegistry

The StateRegistry and [TypeRegistry](type-registry.md) work together to provide complete type conversion for Home Assistant state data:

- **StateRegistry** → Determines which state model class to use based on domain
- **TypeRegistry** → Converts raw values to proper Python types during model validation

### The Complete Flow

When state data arrives from Home Assistant, both registries cooperate:

1. **Raw data arrives** from Home Assistant:
   ```python
   --8<-- "pages/advanced/snippets/state-registry/flow_raw_input.py"
   ```

2. **StateRegistry** determines the model class based on the `time` domain → returns `TimeState`

3. **Pydantic validation** begins on the `TimeState` model

4. **BaseState._validate_domain_and_state** checks the `value_type` ClassVar

5. **TypeRegistry** converts `"12:01:01"` (str) → `whenever.Time`

6. **Validation completes** with the properly typed value:
   ```python
   --8<-- "pages/advanced/snippets/state-registry/flow_converted_output.py"
   ```

### The value_type ClassVar

State model classes use the `value_type` ClassVar to declare expected state value types:

```python
--8<-- "pages/advanced/snippets/state-registry/value_type_example.py"
```

During validation, if the raw state value doesn't match `value_type`, the TypeRegistry automatically converts it.

This means when you work with state models, numeric values, booleans, and datetimes are automatically the correct Python type, not strings.

### Why Two Registries?

**Separation of Concerns:**

- StateRegistry: **"What model class?"** (domain → model mapping)
- TypeRegistry: **"What type?"** (value → type conversion)

This separation allows:

1. StateRegistry to focus on domain logic and model selection
2. TypeRegistry to be reused throughout the framework (DI system, custom extractors, etc.)
3. Easy extension of either system independently

**Example Benefits:**
```python
--8<-- "pages/advanced/snippets/state-registry/example_benefits.py"
```

See [TypeRegistry](type-registry.md) for more details on automatic value conversion.

## State Conversion

The primary use of the StateRegistry is converting raw state dictionaries to typed models:

### Direct Conversion

```python
--8<-- "pages/advanced/snippets/state-registry/direct_conversion.py"
```

The `try_convert_state` method:

- Extracts the domain from the entity_id
- Looks up the corresponding state class
- Converts the dictionary to a Pydantic model instance
- Falls back to `BaseState` for unknown domains

### Via Dependency Injection

The StateRegistry integrates seamlessly with [dependency injection](../core-concepts/bus/dependency-injection.md):

```python
--8<-- "pages/advanced/snippets/state-registry/di_integration.py"
```

Behind the scenes, the DI system uses `convert_state_dict_to_model()` which calls the StateRegistry.

## Domain Override

If you want to override the default state class for a domain (for example, to add custom attributes), define your class after imports:

```python
--8<-- "pages/advanced/snippets/state-registry/domain_override.py"
```

The StateRegistry silently replaces the existing class with your custom one.

## Union Type Support

The StateRegistry works with Union types, automatically selecting the correct state class:

```python
--8<-- "pages/advanced/snippets/state-registry/union_type_support.py"
```

The conversion logic:
1. Extracts the domain from the entity_id
2. Checks each type in the Union
3. Uses the state class whose domain matches
4. Falls back to `BaseState` if no match

## Error Handling

The StateRegistry raises specific exceptions for different error conditions:

### InvalidDataForStateConversionError

Raised when state data is malformed or missing required fields:

```python
--8<-- "pages/advanced/snippets/state-registry/error_invalid_data.py"
```

### InvalidEntityIdError

Raised when the entity_id format is invalid:

```python
--8<-- "pages/advanced/snippets/state-registry/error_invalid_entity_id.py"
```

### UnableToConvertStateError

Raised when conversion to the target state class fails:

```python
--8<-- "pages/advanced/snippets/state-registry/error_unable_to_convert.py"
```

## Integration with Other Components

### With Dependency Injection

The StateRegistry powers all state type conversions in [dependency injection](../core-concepts/bus/dependency-injection.md):

```python
--8<-- "pages/advanced/snippets/state-registry/integration_di.py"
```

### With States Resource

The States cache uses the StateRegistry for all state lookups:

```python
--8<-- "pages/advanced/snippets/state-registry/integration_states.py"
```

## Advanced Usage

### Accessing the Registry

The StateRegistry can be imported from Hassette directly:

```python
--8<-- "pages/advanced/snippets/state-registry/accessing_registry.py"
```

In apps, you typically don't need direct access - the DI system and API methods handle conversions automatically.

If you do need to access it, it is accessible through `self.hassette.state_registry`.


## See Also

- [Type Registry](type-registry.md) - automatic value type conversion
- [Dependency Injection](../core-concepts/bus/dependency-injection.md) - using StateRegistry via DI annotations
- [Custom States](custom-states.md) - defining your own state classes
