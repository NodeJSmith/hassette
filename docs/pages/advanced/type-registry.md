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
from hassette.core.type_registry import TypeConverterEntry

entry = TypeConverterEntry(
    func=int,
    from_type=str,
    to_type=int,
    error_message="Cannot convert '{value}' to integer"
)
```

### Registration System

The TypeRegistry provides two ways to register converters:

#### Decorator Registration

Use `@register_type_converter_fn` to register a conversion function:

```python
from hassette.core.type_registry import register_type_converter_fn

@register_type_converter_fn(error_message="String must be a boolean-like value, got {from_type}")
def str_to_bool(value: str) -> bool:
    """Convert HA boolean strings like 'on'/'off' to Python bool.

    The decorator infers from_type and to_type from the function signature.
    """
    value_lower = value.lower()
    if value_lower in ("on", "true", "yes", "1"):
        return True
    elif value_lower in ("off", "false", "no", "0"):
        return False
    raise ValueError(f"Invalid boolean value: {value}")
```

#### Function Registration

Use `register_simple_type_converter` for simple conversions:

```python
from hassette.core.type_registry import register_simple_type_converter

# Register a simple converter (uses int() as the converter function)
register_simple_type_converter(
    from_type=str,
    to_type=int,
    fn=int,  # Optional - defaults to to_type constructor if not provided
    error_message="Cannot convert '{value}' to integer"  # Optional
)
```

### Conversion Lookup

The TypeRegistry uses a dictionary with `(from_type, to_type)` tuples as keys for O(1) lookup performance:

```python
from hassette import TYPE_REGISTRY

# Convert a value
result = TYPE_REGISTRY.convert("42", int)  # Returns 42 as int
```

## Integration with State Models

The TypeRegistry integrates seamlessly with Hassette's state model system through the `value_type` ClassVar.

### The value_type ClassVar

Each state model class can declare a `value_type` ClassVar to specify the expected type(s) of the state value:

```python
from hassette.models.states.base import BaseState
from typing import ClassVar

class SensorState(BaseState):
    """State model for sensor entities."""
    value_type: ClassVar[type | tuple[type, ...]] = (str, int, float)
```

The `value_type` defines what types are valid for the `state` field. It can be:
- A single type: `value_type = int`
- A tuple of types: `value_type = (str, int, float)`
- Defaults to `str` if not specified

### Automatic Conversion in Models

When a state is created or validated, the `BaseState._validate_domain_and_state` model validator automatically uses the TypeRegistry to convert the raw state value:

```python
# In BaseState._validate_domain_and_state
if self.value_type is not None and not isinstance(data["state"], self.value_type):
    try:
        # TypeRegistry is accessed via the Hassette instance
        data["state"] = self.hassette.type_registry.convert(data["state"], self.value_type)
    except (TypeError, ValueError) as e:
        # Error handling...
```

This means when you work with typed state models, values are automatically converted:

```python
from hassette import states

# Raw state data from Home Assistant
raw_data = {
    "entity_id": "sensor.temperature",
    "state": "23.5",  # String from HA
    "attributes": {"unit_of_measurement": "°C"}
}

# Creating a typed state model automatically converts the value
sensor_state = states.SensorState(**raw_data)
print(type(sensor_state.state))  # <class 'float'> - automatically converted!
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
from typing import Annotated
from hassette import dependencies as D
from hassette import accessors as A

async def handler(
    # Brightness is returned as a string from HA, but TypeRegistry
    # automatically converts it to int based on the type hint
    brightness: Annotated[int | None, A.get_attr_new("brightness")],
    entity_id: D.EntityId,
):
    if brightness and brightness > 200:
        self.logger.info("%s is very bright: %d", entity_id, brightness)
```

When a custom extractor returns a value, if the value type doesn't match the annotated type, the TypeRegistry is called to perform the conversion automatically.

### Bypassing Automatic Conversion

If you want to bypass automatic conversion, you can:

1. Use `Any` as the type hint to accept any type without conversion
2. Provide a custom converter function in your extractor

```python
from typing import Annotated, Any

async def handler(
    # No automatic conversion - accepts whatever type is returned
    brightness_raw: Annotated[Any, A.get_attr_new("brightness")],
):
    # Handle conversion yourself
    brightness = int(brightness_raw) if brightness_raw else None
```

Or to use your own converter function:

```python
from typing import Annotated, Any

# define your own conversion method
def converter(value: Any) -> int:
    return int(value) if value else 0

async def handler(
    # Pass `converter` after extractor function
    brightness: Annotated[int, A.get_attr_new("brightness"), converter],
):
    assert isinstance(brightness, int)
```


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

### Complex Type Conversions
- `str` → `list`: JSON string to list
- `str` → `dict`: JSON string to dict
- `list` → `str`: List to JSON string
- `dict` → `str`: Dict to JSON string

## Creating Custom Converters

### Simple Custom Converter

For straightforward conversions, use the decorator:

```python
from hassette.core.type_registry import register_type_converter_fn
from enum import Enum

class LightMode(Enum):
    NORMAL = "normal"
    NIGHT = "night"
    BRIGHT = "bright"

@register_type_converter_fn(error_message="'{value}' is not a valid LightMode")
def str_to_light_mode(value: str) -> LightMode:
    """Convert string to LightMode enum.

    Types are inferred from the function signature:
    - from_type: str (from 'value' parameter)
    - to_type: LightMode (from return annotation)
    """
    try:
        return LightMode(value.lower())
    except ValueError:
        valid_modes = ", ".join(m.value for m in LightMode)
        raise ValueError(f"Must be one of: {valid_modes}")
```

### Complex Custom Converter

For more complex conversions, you can create a full converter function with validation:

```python
from hassette.core.type_registry import register_type_converter_fn
from dataclasses import dataclass

@dataclass
class RGBColor:
    """RGB color representation."""
    red: int
    green: int
    blue: int

    def __post_init__(self):
        """Validate RGB values."""
        for name, value in [("red", self.red), ("green", self.green), ("blue", self.blue)]:
            if not 0 <= value <= 255:
                raise ValueError(f"{name} must be between 0 and 255, got {value}")

@register_type_converter_fn(error_message="Cannot parse '{value}' as RGB color (expected 'R,G,B')")
def str_to_rgb(value: str) -> RGBColor:
    """Convert string like '255,128,0' to RGBColor.

    Types inferred from signature: str → RGBColor
    """
    try:
        parts = value.split(",")
        if len(parts) != 3:
            raise ValueError("Expected 3 comma-separated values")

        r, g, b = (int(p.strip()) for p in parts)
        return RGBColor(red=r, green=g, blue=b)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid RGB format: {e}")

@register_type_converter_fn
def rgb_to_str(value: RGBColor) -> str:
    """Convert RGBColor to string like '255,128,0'.

    Types inferred from signature: RGBColor → str
    """
    return f"{value.red},{value.green},{value.blue}"
```

### Using Custom Converters

Once registered, custom converters work automatically throughout Hassette:

```python
# In state models
class CustomLightState(BaseState):
    value_type: ClassVar[type] = LightMode

# In dependency injection
async def handler(
    mode: Annotated[LightMode, A.get_attr_new("mode")],
    color: Annotated[RGBColor | None, A.get_attr_new("rgb_color")],
):
    if mode == LightMode.NIGHT:
        # TypeRegistry already converted the strings!
        self.logger.info("Night mode with color %s", color)
```

### Conversion Errors

When a conversion fails, the TypeRegistry wraps the error with context:

```python
from hassette import TYPE_REGISTERY

try:
    result = TYPE_REGISTRY.convert("not_a_number", int)
except ValueError as e:
    # Error message uses the error_message from the converter
    print(e)  # Error details about the conversion failure
```

### Missing Converters

If no converter is registered for a type pair, a `TypeError` is raised:

```python
from hassette import TYPE_REGISTRY

class CustomType:
    pass

try:
    result = TYPE_REGISTRY.convert("value", CustomType)
except TypeError as e:
    print(e)  # "No converter registered for str -> CustomType"
```

### Custom Error Messages

Provide helpful error messages in your custom converters:

```python
@register_type_converter_fn(error_message="'{value}' is not a valid port number")
def str_to_port(value: str) -> int:
    """Convert string to port number (1-65535).

    Types inferred from signature: str → int
    """
    try:
        port = int(value)
        if not 1 <= port <= 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {port}")
        return port
    except ValueError as e:
        raise ValueError(str(e))
```

## Inspection and Debugging

The TypeRegistry provides methods to inspect registered converters:

### List All Conversions

```python
from hassette import TYPE_REGISTRY

# Get all registered conversions
conversions = TYPE_REGISTRY.list_conversions()

for from_type, to_type, entry in conversions:
    print(f"{from_type.__name__} → {to_type.__name__}: {entry.description}")
```

Output example:
```
str → int: Convert string to integer
str → float: Convert string to float
str → bool: Convert Home Assistant boolean strings
int → float: Convert integer to float
...
```

### Check for Specific Converter

```python
from hassette import TYPE_REGISTRY

# Check if a converter exists
key = (str, int)
if key in TYPE_REGISTRY.conversion_map:
    entry = TYPE_REGISTRY.conversion_map[key]
    print(f"Converter found: {entry.description}")
else:
    print("No converter registered")
```

### Get Converter Details

```python
from hassette import TYPE_REGISTRY

# Get details about a specific converter
entry = TYPE_REGISTRY.conversion_map.get((str, bool))
if entry:
    print(f"Description: {entry.description}")
    print(f"Error format: {entry.error_message_format}")
    print(f"Converter: {entry.converter}")
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
from enum import Enum
from hassette.core.type_registry import register_type_converter_fn

class FanSpeed(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

@register_type_converter_fn
def str_to_fan_speed(value: str) -> FanSpeed:
    """Convert string to FanSpeed enum.

    Types inferred from signature: str → FanSpeed
    """
    return FanSpeed(value.lower())
```

### Pattern 2: Structured Data

Convert JSON strings to dataclasses:

```python
from dataclasses import dataclass
import json

@dataclass
class DeviceInfo:
    name: str
    version: str
    manufacturer: str

@register_type_converter_fn
def str_to_device_info(value: str) -> DeviceInfo:
    """Parse device info JSON.

    Types inferred from signature: str → DeviceInfo
    """
    data = json.loads(value)
    return DeviceInfo(**data)
```

### Pattern 3: Units of Measurement

Convert strings with units to numeric values:

```python
import re

@register_type_converter_fn
def str_with_units_to_float(value: str) -> float:
    """Extract numeric value from string with units.

    Example: '23.5 °C' → 23.5
    Types inferred from signature: str → float
    """
    match = re.match(r"^([-+]?[0-9]*\.?[0-9]+)", value.strip())
    if match:
        return float(match.group(1))
    raise ValueError(f"Cannot extract number from '{value}'")
```

## See Also

- [State Registry](state-registry.md) - Domain to model class mapping
- [Dependency Injection](dependency-injection.md) - Using TypeRegistry with custom extractors
- [State Models](../core-concepts/states/index.md) - State model reference
- [Value Converters](value-converters.md) - Complete list of built-in converters
