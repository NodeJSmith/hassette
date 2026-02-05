# TypeRegistry

The TypeRegistry is a core component of Hassette that provides automatic type conversion for raw values from Home Assistant. It enables seamless conversion of string values to their proper Python types (integers, floats, booleans, datetimes, etc.) throughout the framework.

## Purpose

Home Assistant's WebSocket API and state system primarily work with string representations of values. For example:

- A temperature sensor might report `"23.5"` as a string
- A boolean sensor reports `"on"` or `"off"` rather than `True`/`False`
- Timestamps arrive as ISO 8601 strings

The TypeRegistry automatically converts these string values to their proper Python types, making your code cleaner and more type-safe.

## Core Concepts

### TypeConverterEntry

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
--8<-- "pages/advanced/snippets/dependency-injection/custom_type_converter.py"
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
# In BaseState._validate_domain_and_state
values["state"] = TYPE_REGISTRY.convert(state, cls.value_type)
```

This means when you work with typed state models, values are automatically converted:

```python
--8<-- "pages/advanced/snippets/type-registry/typed_model_usage.py"
```

### Union Type Handling

The TypeRegistry intelligently handles Union types (including `value_type` tuples) by trying conversions in order:

```python
from typing import Union

# value_type = (int, float, str) becomes Union[int, float, str]
# TypeRegistry tries: str → int, then str → float, then keeps as str
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
- `str` ↔ `Decimal`: High-precision decimal conversion
- `int` → `float`: Integer to float conversion
- `float` → `int`: Float to integer (truncation)

### Boolean Conversions

- `str` → `bool`: Handles Home Assistant boolean strings
  - True values: `"on"`, `"true"`, `"yes"`, `"1"`
  - False values: `"off"`, `"false"`, `"no"`, `"0"`
- `bool` → `str`: Converts to `"on"` or `"off"` (HA format)
- `int` → `bool`: Standard truthiness conversion

### DateTime Conversions

Uses the `whenever` library for robust datetime handling:

- `str` → `Instant`: Parse ISO 8601 to timezone-aware instant
- `str` → `ZonedDateTime`: Parse to zoned datetime
- `str` → `OffsetDateTime`: Parse to offset-aware datetime
- `str` → `SystemDateTime`: Parse to system datetime
- `str` → `LocalDateTime`: Parse to naive local datetime
- And reverse conversions back to strings

### Conversion Errors

When a conversion fails, the TypeRegistry wraps the error with context:

```python
from hassette import TYPE_REGISTRY

try:
    result = TYPE_REGISTRY.convert("not_a_number", int)
except ValueError as e:
    # Error message uses the error_message from the converter
    print(e)  # Error details about the conversion failure
```

### Missing Converters

If no converter is registered for a type pair, a `TypeError` is raised:

```python
--8<-- "pages/advanced/snippets/type-registry/missing_converter.py"
```

### Custom Error Messages

Provide helpful error messages in your custom converters:

```python
--8<-- "pages/advanced/snippets/type-registry/custom_error_msg.py"
```

## Inspection and Debugging

The TypeRegistry provides methods to inspect registered converters:

### List All Conversions

```python
--8<-- "pages/advanced/snippets/type-registry/inspect_list.py"
```

Output example:
```
str → int
str → float
str → bool
int → float
...
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
# For Union[int, float, str]
# 1. Try str → int
# 2. If that fails, try str → float
# 3. If that fails, try str → str (identity)
```

For better performance with Union types, order the types from most specific to least specific:

- ✅ Good: `Union[int, float, str]` (tries int first, most specific)
- ❌ Less optimal: `Union[str, int, float]` (str matches everything)

## Best Practices

### 1. Define value_type in State Models

Always specify `value_type` in custom state models:

```python
class CustomState(BaseState):
    # Explicitly define expected types
    value_type: ClassVar[type | tuple[type, ...]] = int
```

### 2. Use Type Hints with Custom Extractors

Leverage type hints for automatic conversion in dependency injection:

```python
# TypeRegistry converts automatically based on type hint
async def handler(
    temperature: Annotated[float, A.get_attr_new("temperature")],
    humidity: Annotated[int, A.get_attr_new("humidity")],
):
    # temperature and humidity are already the correct types
    pass
```

### 3. Provide Clear Error Messages

When creating custom converters, write helpful error messages:

```python
@register_type_converter_fn(error_message="Cannot convert '{value}' to MyType. Expected format: X,Y,Z")
def str_to_mytype(value: str) -> MyType:
    """Convert string to MyType with clear error handling.

    Types inferred from signature: str → MyType
    """
    # ... conversion logic with helpful ValueError messages
```

### 4. Register Converters Early

Register custom converters at module import time using decorators:

```python
# my_converters.py
from hassette import register_type_converter_fn

@register_type_converter_fn(...)  # Registered when module is imported
def my_converter(...):
    pass
```

Then import your converters module in your app's `__init__.py` or before first use.

### 5. Test Custom Converters

Always test custom converters with edge cases:

```python
import pytest
from hassette import TYPE_REGISTRY

def test_custom_converter():
    """Test custom RGB converter."""
    # Valid conversion
    result = TYPE_REGISTRY.convert("255,128,0", RGBColor)
    assert result.red == 255
    assert result.green == 128
    assert result.blue == 0

    # Invalid format
    with pytest.raises(ValueError, match="Invalid RGB format"):
        TYPE_REGISTRY.convert("not_rgb", RGBColor)

    # Out of range
    with pytest.raises(ValueError, match="must be between 0 and 255"):
        TYPE_REGISTRY.convert("300,128,0", RGBColor)
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
- [Dependency Injection](dependency-injection.md) - Using TypeRegistry with custom extractors
- [State Models](../core-concepts/states/index.md) - State model reference
