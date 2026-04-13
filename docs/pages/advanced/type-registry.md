# TypeRegistry

Home Assistant sends nearly all values as strings over its API — even numbers and booleans. The TypeRegistry is Hassette's mechanism for automatically converting those strings to the correct Python types before they reach your code.

The TypeRegistry provides automatic type conversion for raw values from Home Assistant — converting string values to their proper Python types (integers, floats, booleans, datetimes, etc.) throughout the framework.

## When Do I Need This?

**Most apps never need to touch the TypeRegistry.** The built-in converters handle all standard Home Assistant types automatically.

You need this page when:

- You have a custom state model whose `value_type` is a type Hassette does not know how to convert (e.g., a third-party type or an enum).
- You need to register a converter for a custom extractor in the dependency injection system.
- A built-in conversion is giving unexpected results and you need to understand or override it.

## Purpose

Home Assistant's WebSocket API and state system primarily work with string representations of values. For example:

- A temperature sensor might report `"23.5"` as a string
- A boolean sensor reports `"on"` or `"off"` rather than `True`/`False`
- Timestamps arrive as ISO 8601 strings

The TypeRegistry automatically converts these string values to their proper Python types, making your code cleaner and more type-safe.

## Core Concepts

??? note "Implementation details: TypeConverterEntry"
    Each registered converter is stored as a `TypeConverterEntry` dataclass containing:

    - **func**: The actual conversion function
    - **from_type**: Source type (e.g., `str`)
    - **to_type**: Target type (e.g., `int`)
    - **error_types**: Tuple of exception types to catch (defaults to `(ValueError,)`)
    - **error_message**: Optional custom error message template (uses `{value}`, `{from_type}`, `{to_type}` placeholders)

    ```python
    --8<-- "pages/advanced/snippets/type-registry/entry_example.py"
    ```

### Registration System

The TypeRegistry provides two ways to register converters:

#### Decorator Registration

Use `@register_type_converter_fn` to register a conversion function:

```python
--8<-- "pages/core-concepts/bus/snippets/dependency-injection/custom_type_converter.py"
```

#### Simple Type Registration

Use `register_simple_type_converter` for simple conversions:

```python
--8<-- "pages/advanced/snippets/type-registry/simple_registration.py"
```

### Conversion Lookup

The TypeRegistry uses a dictionary with `(from_type, to_type)` tuples as keys for O(1) lookup performance:

```python
--8<-- "pages/advanced/snippets/type-registry/lookup_example.py"
```

## Integration with State Models

The TypeRegistry integrates seamlessly with Hassette's state model system through the `value_type` ClassVar.

### The value_type ClassVar

Each state model class can declare a `value_type` ClassVar to specify the expected type(s) of the state value:

```python
--8<-- "pages/advanced/snippets/type-registry/state_model_value_type.py"
```

The `value_type` defines what types are valid for the `state` field. It can be:

- A single type: `value_type = int`
- A tuple of types: `value_type = (str, int, float)`
- Defaults to `str` if not specified

### Automatic Conversion in Models

When a state is created or validated, the `BaseState._validate_domain_and_state` model validator automatically uses the TypeRegistry to convert the raw state value:

```python
--8<-- "pages/advanced/snippets/type-registry/base_state_convert_call.py"
```

This means when you work with typed state models, values are automatically converted:

```python
--8<-- "pages/advanced/snippets/type-registry/typed_model_usage.py"
```

### Union Type Handling

The TypeRegistry intelligently handles Union types (including `value_type` tuples) by trying conversions in order:

```python
--8<-- "pages/advanced/snippets/type-registry/union_type_order.py"
```

The conversion attempts each type in the Union until one succeeds, preserving the original value if no conversion works.

## Integration with Dependency Injection

The TypeRegistry powers automatic type conversion in the dependency injection system, particularly for custom extractors.

### Type Conversion in Custom Extractors

When you use `Annotated` with custom extractors from `hassette.event_handling.accessors`, the TypeRegistry automatically converts extracted values:

```python
--8<-- "pages/advanced/snippets/type-registry/di_custom_extractor.py"
```

When a custom extractor returns a value, if the value type doesn't match the annotated type, the TypeRegistry is called to perform the conversion automatically.

## Relationship with StateRegistry

The TypeRegistry and StateRegistry work together but serve different purposes:

**StateRegistry**: Maps Home Assistant domains to Pydantic state model classes

- Purpose: Determines which model class to use for a given entity
- Example: `"sensor.temperature"` → `SensorState` class

**TypeRegistry**: Converts raw values to proper Python types

- Purpose: Ensures state values match expected types
- Example: `"23.5"` (string) → `23.5` (float)

### The Workflow

1. **StateRegistry** determines the model class based on domain
2. Pydantic validation begins with raw state data
3. `BaseState._validate_domain_and_state` checks the `value_type` ClassVar
4. **TypeRegistry** converts the state value to match `value_type`
5. Pydantic continues validation with the properly typed value


## Built-in Converters

Hassette includes comprehensive built-in conversion:

### Numeric Conversions

- `str` ↔ `int`: Basic integer conversion
- `str` ↔ `float`: Floating-point conversion
- `str` → `Decimal`: High-precision decimal parsing
- `float` → `Decimal`: Floating-point to high-precision decimal
- `Decimal` → `int` / `float`: Precision-loss conversion
- `int` → `float`: Integer to float conversion
- `float` → `int`: Float to integer (truncation)

### Boolean Conversions

- `str` → `bool`: Handles Home Assistant boolean strings
  - True values: `"on"`, `"true"`, `"yes"`, `"1"`
  - False values: `"off"`, `"false"`, `"no"`, `"0"`
- `bool` → `str`: Converts to `"True"` or `"False"` (Python `str()` — not HA format)

### DateTime Conversions

Uses the `whenever` library for robust datetime handling:

**`whenever` types:**

- `str` → `ZonedDateTime`: Parse HA datetime strings (ISO, plain, or date-only — assumed system timezone)
- `str` → `Date`: ISO date string via `Date.parse_iso`
- `str` → `Time`: ISO time string via `Time.parse_iso`
- `str` → `OffsetDateTime`: ISO datetime with UTC offset via `OffsetDateTime.parse_iso`
- `str` → `PlainDateTime`: ISO datetime without timezone via `PlainDateTime.parse_iso`
- `ZonedDateTime` → `Instant`: Strip timezone info (`to_instant`)
- `ZonedDateTime` → `PlainDateTime`: Drop timezone (`to_plain`)
- `ZonedDateTime` → `str`: ISO format (`format_iso`)
- `Time` → `str`: ISO format (`format_iso`)

**Stdlib datetime types:**

- `str` → `datetime`: Parse via `ZonedDateTime.py_datetime()`
- `str` → `time`: Parse via `Time.parse_iso().py_time()`
- `str` → `date`: Parse via `Date.parse_iso().py_date()`
- `Time` → `time`: Convert via `py_time()`

### Conversion Errors

When a conversion fails, the TypeRegistry wraps the error with context:

```python
--8<-- "pages/advanced/snippets/type-registry/conversion_error.py"
```

### Missing Converters

If no converter is registered for a type pair and the type's constructor also fails, an `UnableToConvertValueError` is raised:

```python
--8<-- "pages/advanced/snippets/type-registry/missing_converter.py"
```

### Custom Error Messages

Provide helpful error messages in your custom converters:

```python
--8<-- "pages/advanced/snippets/type-registry/custom_error_msg.py"
```

## Inspection and Debugging

??? note "Implementation details: inspection API"
    The TypeRegistry provides methods to inspect registered converters. These are primarily useful for Hassette core developers or for debugging unexpected conversion behavior.

    ### List All Conversions

    ```python
    --8<-- "pages/advanced/snippets/type-registry/inspect_list.py"
    ```

    Output example:
    ```
    --8<-- "pages/advanced/snippets/type-registry/inspect_list_output.txt"
    ```

    ### Check for Specific Converter

    ```python
    --8<-- "pages/advanced/snippets/type-registry/inspect_check.py"
    ```

    ### Get Converter Details

    ```python
    --8<-- "pages/advanced/snippets/type-registry/inspect_details.py"
    ```

### Union Type Performance

When converting to Union types, the TypeRegistry tries each type in order until one succeeds:

```python
--8<-- "pages/advanced/snippets/type-registry/union_type_performance.py"
```

For better performance with Union types, order the types from most specific to least specific:

- ✅ Good: `Union[int, float, str]` (tries int first, most specific)
- ❌ Less optimal: `Union[str, int, float]` (str matches everything)

## Best Practices

### 1. Define value_type in State Models

Always specify `value_type` in custom state models:

```python
--8<-- "pages/advanced/snippets/type-registry/best_practice_value_type.py"
```

### 2. Use Type Hints with Custom Extractors

Leverage type hints for automatic conversion in dependency injection:

```python
--8<-- "pages/advanced/snippets/type-registry/best_practice_type_hints.py"
```

### 3. Provide Clear Error Messages

When creating custom converters, write helpful error messages:

```python
--8<-- "pages/advanced/snippets/type-registry/best_practice_error_msg.py"
```

### 4. Register Converters Early

Register custom converters at module import time using decorators:

```python
--8<-- "pages/advanced/snippets/type-registry/best_practice_register_early.py"
```

Then import your converters module in your app's `__init__.py` or before first use.

### 5. Test Custom Converters

Always test custom converters with edge cases:

```python
--8<-- "pages/advanced/snippets/type-registry/best_practice_test_converter.py"
```
## Common Patterns

### Pattern 1: Enum Conversion

Convert Home Assistant string values to Python enums:

```python
--8<-- "pages/advanced/snippets/type-registry/pattern_enum.py"
```

### Pattern 2: Structured Data

Convert JSON strings to dataclasses:

```python
--8<-- "pages/advanced/snippets/type-registry/pattern_structured.py"
```

### Pattern 3: Units of Measurement

Convert strings with units to numeric values:

```python
--8<-- "pages/advanced/snippets/type-registry/pattern_units.py"
```

## See Also

- [State Registry](state-registry.md) - Domain to model class mapping
- [Dependency Injection](../core-concepts/bus/dependency-injection.md) - Using TypeRegistry with custom extractors
- [State Models](../core-concepts/states/index.md) - State model reference
