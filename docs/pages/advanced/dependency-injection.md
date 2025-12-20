# Dependency Injection

Hassette uses **dependency injection** (DI) to automatically extract and provide event data to your event handlers. Instead of manually parsing event payloads, you declare what data you need using type annotations, and Hassette handles the extraction and type conversion for you.

## Quick Example

```python
--8<-- "pages/advanced/snippets/dependency-injection/quick_example.py"
```

In this example, `new_state` and `entity_id` are automatically extracted from the `RawStateChangeEvent` and injected into your handler based on their type annotations.

## Three Event Handling Patterns

Hassette supports three patterns for handling events, from lowest to highest level:

### Pattern 1: Raw Event (Untyped)

Receive the full event object with state data as untyped dictionaries:

```python
--8<-- "pages/advanced/snippets/dependency-injection/pattern1_raw.py"
```

**Use when:** You need full control or are working with dynamic/unknown state structures.

!!! warning
    While typed State models use `value` for the actual state value, raw state dictionaries are accessed via the `"state"` key, as
    this is the key used by Home Assistant in its event payloads.

### Pattern 2: Typed Event

Receive the full event with state objects converted to typed Pydantic models:

```python
--8<-- "pages/advanced/snippets/dependency-injection/pattern2_typed.py"
```

**Use when:** You want type safety but need access to the full event structure (topic, context, etc.).

!!! note
    Notice that in this example we use `new_state.value` instead of `new_state.state` because typed State models use the `value` property for the actual state value.

### Pattern 3: DI Extraction (Recommended)

Extract only the specific data you need:

```python
--8<-- "pages/advanced/snippets/dependency-injection/pattern3_di.py"
```

**Use when:** You want clean, focused handlers with minimal boilerplate (recommended for most cases).

## Available DI Annotations

All dependency injection annotations are available in the `hassette.dependencies` module (commonly imported as `D`).

### State Object Extractors

Extract typed state objects from state change events:

| Annotation         | Type        | Description                                  |
| ------------------ | ----------- | -------------------------------------------- |
| `StateNew[T]`      | `T`         | Extract new state, raises if missing         |
| `StateOld[T]`      | `T`         | Extract old state, raises if missing         |
| `MaybeStateNew[T]` | `T \| None` | Extract new state, returns `None` if missing |
| `MaybeStateOld[T]` | `T \| None` | Extract old state, returns `None` if missing |

```python
--8<-- "pages/advanced/snippets/dependency-injection/state_object_extractors.py"
```

### Identity Extractors

Extract entity IDs and domains from events:

| Annotation      | Type                    | Description                                    |
| --------------- | ----------------------- | ---------------------------------------------- |
| `EntityId`      | `str`                   | Extract entity ID, raises if missing           |
| `MaybeEntityId` | `str \| Sentinel` | Extract entity ID, returns sentinel if missing    |
| `Domain`        | `str`                   | Extract domain, raises if missing              |
| `MaybeDomain`   | `str \| Sentinel` | Extract domain, returns sentinel if missing    |

```python
--8<-- "pages/advanced/snippets/dependency-injection/identity_extractors.py"
```

### Other Extractors

| Annotation                 | Type                       | Description                          |
| -------------------------- | -------------------------- | ------------------------------------ |
| `EventContext`             | `HassContext`              | Extract Home Assistant event context |
| `TypedStateChangeEvent[T]` | `TypedStateChangeEvent[T]` | Convert raw event to typed event     |

```python
--8<-- "pages/advanced/snippets/dependency-injection/other_extractors.py"
```

## Union Type Support

DI extractors support Union types, allowing handlers to work with multiple state types:

```python
--8<-- "pages/advanced/snippets/dependency-injection/union_types.py"
```

The StateRegistry determines the correct state class based on the entity's domain, and the DI system converts the raw state dictionary to the appropriate Pydantic model.

## Combining Multiple Dependencies

You can extract multiple pieces of data in a single handler:

```python
--8<-- "pages/advanced/snippets/dependency-injection/multiple_dependencies.py"
```

## Mixing DI with Custom kwargs

Dependency injection works seamlessly with custom keyword arguments passed when registering handlers:

```python
--8<-- "pages/advanced/snippets/dependency-injection/mixing_kwargs.py"
```

## Custom Extractors

You can create custom extractors using the `Annotated` type with either existing accessors from [`accessors`][hassette.event_handling.accessors] or custom callables:

### Using Built-in Accessors

```python
--8<-- "pages/advanced/snippets/dependency-injection/custom_extractor_builtin.py"
```

### Writing Your Own Extractor

Any callable that accepts an event and returns a value can be used as an extractor:

```python
--8<-- "pages/advanced/snippets/dependency-injection/custom_extractor_own.py"
```

### Advanced: Extractor + Converter Pattern

For more complex scenarios, you can use the `AnnotationDetails` class to combine extraction and type conversion:

```python
--8<-- "pages/advanced/snippets/dependency-injection/custom_extractor_converter.py"
```

## Automatic Type Conversion with TypeRegistry

Hassette's dependency injection system uses the [TypeRegistry](type-registry.md) to automatically convert extracted values to match your type annotations. This integrates seamlessly with custom extractors.

### How It Works

When you use a custom extractor with a type annotation, the DI system:

1. **Extracts the value** using your extractor function
2. **Checks the type** of the extracted value against your annotation
3. **Automatically converts** if needed using the TypeRegistry
4. **Injects the converted value** into your handler

This means you can write simple extractors that return raw values, and let TypeRegistry handle the type conversion:

```python
--8<-- "pages/advanced/snippets/dependency-injection/builtin_conversions_implicit.py"
```

### Built-in Conversions

The TypeRegistry provides comprehensive built-in conversions for common types:

- **Numeric types**: `str` ↔ `int`, `float`, `Decimal`
- **Boolean**: `str` → `bool` (handles `"on"`, `"off"`, `"true"`, `"false"`, etc.)
- **DateTime types**: `str` → `datetime`, `date`, `time` (stdlib), and `whenever` types

**Examples:**
```python
--8<-- "pages/advanced/snippets/dependency-injection/builtin_conversions_explicit.py"
```

### Custom Type Converters

You can register your own type converters for custom types:

```python
--8<-- "pages/advanced/snippets/dependency-injection/custom_type_converter.py"
```

### When Conversion Happens

Type conversion is skipped if the returned value is already the correct type or is `None`.

If the value is not `None` and does not match the expected type, Hassette will attempt to convert it using the TypeRegistry.
The TypeRegistry will first look for a registered converter for the `(from_type, to_type)` pair. If `to_type` is a `tuple`, it will iterate
through each type in the tuple and use the first converter that succeeds.

If there is no registered converter for the `(from_type, to_type)` pair, Hassette will attempt to call `to_type` as a constructor with the value as the sole argument.

If type conversion fails, Hassette will raise a `UnableToConvertValueError`. For tuples, this will be raised only if all conversions fail.


### Bypassing Automatic Conversion

If you want to handle conversion yourself, you can:

1. **Use `Any` type annotation** to receive the raw value:

   ```python
   --8<-- "pages/advanced/snippets/dependency-injection/bypass_conversion_any.py"
   ```

2. **Provide a custom converter** in `AnnotationDetails`:

   ```python
   --8<-- "pages/advanced/snippets/dependency-injection/bypass_conversion_custom.py"
   ```

### Error Handling

When type conversion fails, Hassette provides clear error messages:

```python
--8<-- "pages/advanced/snippets/dependency-injection/error_handling.py"
```

## Handler Signature Restrictions

DI handlers have some restrictions to ensure unambiguous parameter injection:

!!! warning "Handler Signature Rules"
    Handlers using DI **cannot** have:

    - Positional-only parameters (parameters before `/`)
    - Variadic positional arguments (`*args`)

    These restrictions ensure that Hassette can reliably match parameters to extracted values.

!!! info "Type Annotations Required"
    All parameters using dependency injection must have type annotations. Hassette uses these annotations to determine what to extract from events and how to convert the data.

## How It Works

Under the hood, Hassette's DI system:

1. **Inspects handler signatures** using Python's `inspect` module to find annotated parameters
2. **Extracts type information** from `Annotated` types and recognizes special DI annotations
3. **Builds extractors** for each parameter that know how to pull data from events
4. **Converts types** using the StateRegistry for state objects, converting raw dictionaries to typed Pydantic models
5. **Injects values** at call time, passing extracted and converted values as keyword arguments

The core implementation lives in:
- [`extraction`][hassette.bus.extraction] - Signature inspection and parameter extraction
- [`dependencies`][hassette.event_handling.dependencies] - Pre-defined DI annotations
- [`accessors`][hassette.event_handling.accessors] - Low-level event data accessors

## See Also

- [Type Registry](type-registry.md) - automatic type conversion system
- [State Registry](state-registry.md) - domain to state model mapping
