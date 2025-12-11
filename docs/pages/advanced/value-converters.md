# Value Converters Reference

This page provides a comprehensive reference of all built-in type converters registered in Hassette's TypeRegistry. These converters enable automatic type conversion throughout the framework, particularly when working with Home Assistant's string-based state values.

## Overview

All built-in converters are registered in `src/hassette/types/value_converters.py` and are available immediately when Hassette initializes. You can view all registered conversions programmatically:

```python
from hassette.context import get_type_registry

# Get the TypeRegistry instance
type_registry = get_type_registry()

# List all conversions
conversions = type_registry.list_conversions()
for from_type, to_type, entry in conversions:
    print(f"{from_type.__name__} → {to_type.__name__}: {entry.description}")
```

## Numeric Conversions

### Integer Conversions

| From Type | To Type | Description               | Notes                                   |
| --------- | ------- | ------------------------- | --------------------------------------- |
| `str`     | `int`   | Parse string to integer   | Raises `ValueError` for invalid strings |
| `int`     | `str`   | Convert integer to string | Simple string conversion                |
| `int`     | `float` | Convert integer to float  | Always succeeds                         |
| `float`   | `int`   | Truncate float to integer | Loses decimal precision                 |

**Examples:**
```python
from hassette.context import get_type_registry

type_registry = get_type_registry()
type_registry.convert("42", int)      # → 42
type_registry.convert(42, str)        # → "42"
type_registry.convert(42, float)      # → 42.0
type_registry.convert(42.7, int)      # → 42 (truncates)
```

### Floating-Point Conversions

| From Type | To Type | Description             | Notes                                   |
| --------- | ------- | ----------------------- | --------------------------------------- |
| `str`     | `float` | Parse string to float   | Raises `ValueError` for invalid strings |
| `float`   | `str`   | Convert float to string | Standard string representation          |

**Examples:**
```python
from hassette.context import get_type_registry

type_registry = get_type_registry()
type_registry.convert("23.5", float)  # → 23.5
type_registry.convert(23.5, str)      # → "23.5"
```

### Decimal Conversions

High-precision decimal arithmetic using Python's `Decimal` type.

| From Type | To Type   | Description              | Notes                                       |
| --------- | --------- | ------------------------ | ------------------------------------------- |
| `str`     | `Decimal` | Parse string to Decimal  | Raises `ValueError` or `InvalidOperation`   |
| `float`   | `Decimal` | Convert float to Decimal | May have floating-point precision artifacts |
| `Decimal` | `float`   | Convert Decimal to float | May lose precision                          |
| `Decimal` | `int`     | Convert Decimal to int   | Truncates decimal part                      |

**Examples:**
```python
from decimal import Decimal
from hassette.context import get_type_registry

type_registry = get_type_registry()
type_registry.convert("0.1", Decimal)      # → Decimal('0.1')
type_registry.convert(0.1, Decimal)        # → Decimal('0.1000000000000000055511151231257827021181583404541015625')
type_registry.convert(Decimal("42.7"), int)  # → 42
```

## Boolean Conversions

### String to Boolean

Hassette provides Home Assistant-aware boolean conversion that handles HA's string representations.

| From Type | To Type | True Values                      | False Values                      | Error                                 |
| --------- | ------- | -------------------------------- | --------------------------------- | ------------------------------------- |
| `str`     | `bool`  | `"on"`, `"true"`, `"yes"`, `"1"` | `"off"`, `"false"`, `"no"`, `"0"` | Raises `ValueError` for other strings |

**Case Insensitive**: All string comparisons are case-insensitive.

**Examples:**
```python
from hassette.context import get_type_registry

type_registry = get_type_registry()
type_registry.convert("on", bool)      # → True
type_registry.convert("OFF", bool)     # → False
type_registry.convert("true", bool)    # → True
type_registry.convert("yes", bool)     # → True
type_registry.convert("0", bool)       # → False
type_registry.convert("invalid", bool) # → Raises ValueError
```

### Other Boolean Conversions

| From Type | To Type | Description                      |
| --------- | ------- | -------------------------------- |
| `bool`    | `str`   | Convert to string representation |

**Examples:**
```python
from hassette.context import get_type_registry

type_registry = get_type_registry()
type_registry.convert(True, str)   # → "True"
type_registry.convert(False, str)  # → "False"
```

## DateTime Conversions

Hassette uses the [`whenever`](https://github.com/ariebovenberg/whenever) library for robust datetime handling, providing timezone-aware datetime objects by default.

### String to whenever Types

| From Type | To Type          | Description                       | Error Handling                                                   |
| --------- | ---------------- | --------------------------------- | ---------------------------------------------------------------- |
| `str`     | `ZonedDateTime`  | Parse ISO 8601 to system timezone | Tries multiple parse strategies, raises `ValueError` if all fail |
| `str`     | `OffsetDateTime` | Parse ISO 8601 with offset        | Raises `ValueError` for invalid format                           |
| `str`     | `PlainDateTime`  | Parse ISO 8601 as naive datetime  | Raises `ValueError` for invalid format                           |
| `str`     | `Date`           | Parse ISO 8601 date               | Raises `ValueError` for invalid format                           |
| `str`     | `Time`           | Parse ISO 8601 time               | Raises `ValueError` for invalid format                           |

**ZonedDateTime Parse Strategy**: The `str → ZonedDateTime` converter tries multiple strategies in order:
1. Parse as full ISO 8601 datetime string (e.g., `"2023-12-25T09:00:00-05:00"`)
2. Parse as plain datetime and assume system timezone (e.g., `"2023-12-25T09:00:00"`)
3. Parse as date and assume midnight in system timezone (e.g., `"2023-12-25"`)

**Examples:**
```python
from whenever import ZonedDateTime, Date, Time
from hassette.context import get_type_registry

type_registry = get_type_registry()

# Full ISO 8601 datetime
type_registry.convert("2023-12-25T09:00:00-05:00", ZonedDateTime)
# → ZonedDateTime with Eastern timezone

# Plain datetime (assumes system timezone)
type_registry.convert("2023-12-25T09:00:00", ZonedDateTime)
# → ZonedDateTime in system timezone

# Date only (assumes midnight)
type_registry.convert("2023-12-25", ZonedDateTime)
# → ZonedDateTime at midnight in system timezone

# Date
type_registry.convert("2023-12-25", Date)
# → Date(2023, 12, 25)

# Time
type_registry.convert("09:30:00", Time)
# → Time(9, 30, 0)
```

### whenever to String

| From Type       | To Type | Description        |
| --------------- | ------- | ------------------ |
| `ZonedDateTime` | `str`   | Format as ISO 8601 |
| `Time`          | `str`   | Format as ISO 8601 |

**Examples:**
```python
from whenever import ZonedDateTime, Time
from hassette.context import get_type_registry

type_registry = get_type_registry()
zdt = ZonedDateTime(2023, 12, 25, 9, 0, 0, tz="America/New_York")
type_registry.convert(zdt, str)  # → "2023-12-25T09:00:00-05:00"

t = Time(9, 30, 0)
type_registry.convert(t, str)    # → "09:30:00"
```

### whenever Type Conversions

| From Type       | To Type         | Description                          |
| --------------- | --------------- | ------------------------------------ |
| `ZonedDateTime` | `Instant`       | Convert to timezone-agnostic instant |
| `ZonedDateTime` | `PlainDateTime` | Convert to naive local datetime      |

**Examples:**
```python
from whenever import ZonedDateTime
from hassette.context import get_type_registry

type_registry = get_type_registry()
zdt = ZonedDateTime(2023, 12, 25, 9, 0, 0, tz="America/New_York")
type_registry.convert(zdt, Instant)       # → Instant representing same moment
type_registry.convert(zdt, PlainDateTime) # → PlainDateTime(2023, 12, 25, 9, 0, 0)
```

### String to Python stdlib DateTime Types

For compatibility with code expecting Python's standard library datetime types:

| From Type | To Type    | Description                          | Error Handling                            |
| --------- | ---------- | ------------------------------------ | ----------------------------------------- |
| `str`     | `datetime` | Parse and convert to stdlib datetime | Uses ZonedDateTime parsing, then converts |
| `str`     | `date`     | Parse ISO 8601 date to stdlib date   | Raises `ValueError` for invalid format    |
| `str`     | `time`     | Parse ISO 8601 time to stdlib time   | Raises `ValueError` for invalid format    |

**Examples:**
```python
from datetime import datetime, date, time
from hassette.context import get_type_registry

type_registry = get_type_registry()

# Datetime (timezone-aware)
type_registry.convert("2023-12-25T09:00:00-05:00", datetime)
# → datetime.datetime(2023, 12, 25, 9, 0, 0, tzinfo=...)

# Date
type_registry.convert("2023-12-25", date)
# → datetime.date(2023, 12, 25)

# Time
type_registry.convert("09:30:00", time)
# → datetime.time(9, 30, 0)
```

### whenever to Python stdlib

| From Type | To Type | Description                          |
| --------- | ------- | ------------------------------------ |
| `Time`    | `time`  | Convert whenever Time to stdlib time |

**Examples:**
```python
from whenever import Time
from datetime import time as stdlib_time
from hassette.context import get_type_registry

type_registry = get_type_registry()
wt = Time(9, 30, 0)
type_registry.convert(wt, stdlib_time)  # → time(9, 30, 0)
```

## Usage in State Models

The TypeRegistry automatically applies these conversions when validating state models. The `value_type` ClassVar determines which conversions are attempted:

```python
from hassette.models.states.base import BaseState
from typing import ClassVar

class TemperatureSensorState(BaseState):
    """Temperature sensor with float value."""
    value_type: ClassVar[type] = float

# When created from Home Assistant data:
# {"entity_id": "sensor.temp", "state": "23.5"}
# The string "23.5" is automatically converted to float 23.5
```

## Usage in Dependency Injection

The TypeRegistry powers automatic conversion in custom extractors:

```python
from typing import Annotated
from hassette import dependencies as D
from hassette import accessors as A

async def handler(
    # Automatically converted from string to float
    temperature: Annotated[float, A.get_attr_new("temperature")],
    # Automatically converted from string to int
    battery: Annotated[int | None, A.get_attr_new("battery_level")],
):
    if temperature > 25.0:
        print(f"Hot! Temp: {temperature}°C, Battery: {battery}%")
```

## Error Handling

All converters raise exceptions when conversion fails:

- **ValueError**: The value cannot be converted (e.g., `"abc"` to `int`)
- **InvalidOperation**: Decimal conversion failed
- **TypeError**: No converter registered for the type pair

**Examples of Error Cases:**
```python
from hassette.context import get_type_registry

type_registry = get_type_registry()

# Invalid integer
try:
    type_registry.convert("not_a_number", int)
except ValueError as e:
    print(e)  # "Cannot convert 'not_a_number' to integer"

# Invalid boolean
try:
    type_registry.convert("maybe", bool)
except ValueError as e:
    print(e)  # "String must be a boolean-like value..."

# No converter registered
try:
    type_registry.convert("value", list)
except TypeError as e:
    print(e)  # "No converter registered for str -> list"
```

## Creating Custom Converters

You can register your own converters for custom types. See [TypeRegistry - Creating Custom Converters](type-registry.md#creating-custom-converters) for detailed examples.

**Quick Example:**
```python
from hassette.core.type_registry import register_type_converter_fn
from enum import Enum

class Status(Enum):
    ONLINE = "online"
    OFFLINE = "offline"

@register_type_converter_fn(error_message="'{value}' is not a valid Status")
def str_to_status(value: str) -> Status:
    """Convert string to Status enum."""
    return Status(value.lower())
```

## Performance Notes

### Lookup Performance

All converter lookups are O(1) dictionary lookups using `(from_type, to_type)` tuple keys.

### Union Types

When converting to Union types (e.g., `int | float | str`), the TypeRegistry tries each type in order until one succeeds. For best performance, order Union types from most specific to least specific:

- ✅ **Good**: `int | float | str` (tries specific types first)
- ❌ **Less optimal**: `str | int | float` (str matches everything)

### No Result Caching

The TypeRegistry does not cache conversion results because:
1. Conversion operations are typically very fast (simple type coercion)
2. Values are usually converted once during model creation
3. Caching would add memory overhead with minimal benefit

If you need to convert the same value repeatedly, consider application-level caching:

```python
from functools import lru_cache
from hassette.context import get_type_registry

@lru_cache(maxsize=128)
def parse_config(config_str: str) -> MyConfig:
    type_registry = get_type_registry()
    return type_registry.convert(config_str, MyConfig)
```

## Complete Conversion Table

### Quick Reference

All built-in conversions at a glance:

| From            | To               | Method                                |
| --------------- | ---------------- | ------------------------------------- |
| `str`           | `int`            | `int()`                               |
| `str`           | `float`          | `float()`                             |
| `str`           | `bool`           | Home Assistant boolean parsing        |
| `str`           | `Decimal`        | `Decimal()`                           |
| `str`           | `datetime`       | ISO 8601 parsing with system timezone |
| `str`           | `date`           | ISO 8601 date parsing                 |
| `str`           | `time`           | ISO 8601 time parsing                 |
| `str`           | `ZonedDateTime`  | Multi-strategy parsing                |
| `str`           | `OffsetDateTime` | ISO 8601 parsing                      |
| `str`           | `PlainDateTime`  | ISO 8601 parsing                      |
| `str`           | `Date`           | ISO 8601 parsing                      |
| `str`           | `Time`           | ISO 8601 parsing                      |
| `int`           | `float`          | Type promotion                        |
| `int`           | `str`            | String conversion                     |
| `float`         | `int`            | Truncation                            |
| `float`         | `str`            | String conversion                     |
| `float`         | `Decimal`        | Decimal conversion                    |
| `bool`          | `str`            | String conversion                     |
| `Decimal`       | `float`          | Float conversion                      |
| `Decimal`       | `int`            | Truncation                            |
| `ZonedDateTime` | `Instant`        | Timezone removal                      |
| `ZonedDateTime` | `PlainDateTime`  | Timezone removal                      |
| `ZonedDateTime` | `str`            | ISO 8601 formatting                   |
| `Time`          | `time`           | stdlib conversion                     |
| `Time`          | `str`            | ISO 8601 formatting                   |

## See Also

- [Type Registry](type-registry.md) - Detailed TypeRegistry documentation
- [State Registry](state-registry.md) - Domain to model mapping
- [Dependency Injection](dependency-injection.md) - Using type conversion with DI
- [whenever library](https://github.com/ariebovenberg/whenever) - DateTime library used by Hassette
