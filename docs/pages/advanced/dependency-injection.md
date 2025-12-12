# Dependency Injection

Hassette uses **dependency injection** (DI) to automatically extract and provide event data to your event handlers. Instead of manually parsing event payloads, you declare what data you need using type annotations, and Hassette handles the extraction and type conversion for you.

## Quick Example

```python
from hassette import App, dependencies as D, states

class LightMonitor(App):
    async def on_initialize(self):
        self.bus.on_state_change(
            "light.bedroom",
            handler=self.on_light_change,
        )

    async def on_light_change(
        self,
        new_state: D.StateNew[states.LightState],
        entity_id: D.EntityId,
    ):
        brightness = new_state.attributes.brightness
        self.logger.info("%s brightness: %s", entity_id, brightness)
```

In this example, `new_state` and `entity_id` are automatically extracted from the `RawStateChangeEvent` and injected into your handler based on their type annotations.

## Three Event Handling Patterns

Hassette supports three patterns for handling events, from lowest to highest level:

### Pattern 1: Raw Event (Untyped)

Receive the full event object with state data as untyped dictionaries:

```python
from hassette.events import RawStateChangeEvent

async def on_motion(self, event: RawStateChangeEvent):
    entity_id = event.payload.data.entity_id
    new_state_dict = event.payload.data.new_state
    state_value = new_state_dict.get("state") if new_state_dict else None
    self.logger.info("Motion: %s -> %s", entity_id, state_value)
```

**Use when:** You need full control or are working with dynamic/unknown state structures.

!!! warning
    While typed State models use `value` for the actual state value, raw state dictionaries are accessed via the `"state"` key, as
    this is the key used by Home Assistant in its event payloads.

### Pattern 2: Typed Event

Receive the full event with state objects converted to typed Pydantic models:

```python
from hassette import dependencies as D, states

async def on_motion(
    self,
    event: D.TypedStateChangeEvent[states.BinarySensorState],
):
    entity_id = event.payload.data.entity_id
    new_state = event.payload.data.new_state
    if new_state:
        state_value = new_state.value
        self.logger.info("Motion: %s -> %s", entity_id, state_value)
```

**Use when:** You want type safety but need access to the full event structure (topic, context, etc.).

!!! note
    Notice that in this example we use `new_state.value` instead of `new_state.state` because typed State models use the `value` property for the actual state value.

### Pattern 3: DI Extraction (Recommended)

Extract only the specific data you need:

```python
from hassette import dependencies as D, states

async def on_motion(
    self,
    new_state: D.StateNew[states.BinarySensorState],
    entity_id: D.EntityId,
):
    friendly_name = new_state.attributes.friendly_name or entity_id
    self.logger.info("Motion detected: %s", friendly_name)
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
from hassette import dependencies as D, states

async def on_light_change(
    self,
    new_state: D.StateNew[states.LightState],
    old_state: D.MaybeStateOld[states.LightState],
):
    if old_state:
        brightness_changed = (
            new_state.attributes.brightness != old_state.attributes.brightness
        )
        if brightness_changed:
            self.logger.info(
                "Brightness: %s -> %s",
                old_state.attributes.brightness,
                new_state.attributes.brightness,
            )
```

### Identity Extractors

Extract entity IDs and domains from events:

| Annotation      | Type                    | Description                                    |
| --------------- | ----------------------- | ---------------------------------------------- |
| `EntityId`      | `str`                   | Extract entity ID, raises if missing           |
| `MaybeEntityId` | `str \| FalseySentinel` | Extract entity ID, returns sentinel if missing |
| `Domain`        | `str`                   | Extract domain, raises if missing              |
| `MaybeDomain`   | `str \| FalseySentinel` | Extract domain, returns sentinel if missing    |

```python
from hassette import dependencies as D

async def on_any_light(
    self,
    entity_id: D.EntityId,
    domain: D.Domain,
):
    self.logger.info("Light entity %s in domain %s changed", entity_id, domain)
```

### Other Extractors

| Annotation                 | Type                       | Description                          |
| -------------------------- | -------------------------- | ------------------------------------ |
| `EventContext`             | `HassContext`              | Extract Home Assistant event context |
| `TypedStateChangeEvent[T]` | `TypedStateChangeEvent[T]` | Convert raw event to typed event     |

```python
from hassette import dependencies as D, states

async def on_light_change(
    self,
    new_state: D.StateNew[states.LightState],
    context: D.EventContext,
):
    self.logger.info(
        "Light %s changed by user %s",
        new_state.entity_id,
        context.user_id or "system",
    )
```

## Union Type Support

DI extractors support Union types, allowing handlers to work with multiple state types:

```python
from hassette import dependencies as D, states

async def on_sensor_change(
    self,
    new_state: D.StateNew[states.SensorState | states.BinarySensorState],
    entity_id: D.EntityId,
):
    # new_state is automatically converted to the correct type
    # based on the entity's domain
    if isinstance(new_state, states.SensorState):
        self.logger.info("Sensor %s: %s", entity_id, new_state.state)
    elif isinstance(new_state, states.BinarySensorState):
        self.logger.info("Binary sensor %s: %s", entity_id, new_state.state)
```

The StateRegistry determines the correct state class based on the entity's domain, and the DI system converts the raw state dictionary to the appropriate Pydantic model.

## Combining Multiple Dependencies

You can extract multiple pieces of data in a single handler:

```python
from hassette import dependencies as D, states

async def on_climate_change(
    self,
    new_state: D.StateNew[states.ClimateState],
    old_state: D.MaybeStateOld[states.ClimateState],
    entity_id: D.EntityId,
    context: D.EventContext,
):
    old_temp = old_state.attributes.current_temperature if old_state else None
    new_temp = new_state.attributes.current_temperature

    if old_temp != new_temp:
        self.logger.info(
            "Climate %s temperature changed: %s -> %s (user: %s)",
            entity_id,
            old_temp,
            new_temp,
            context.user_id or "system",
        )
```

## Mixing DI with Custom kwargs

Dependency injection works seamlessly with custom keyword arguments passed when registering handlers:

```python
async def on_initialize(self):
    self.bus.on_state_change(
        "sensor.temperature",
        handler=self.on_temp_change,
        kwargs={"threshold": 75.0, "alert_level": "warning"},
    )

async def on_temp_change(
    self,
    new_state: D.StateNew[states.SensorState],
    entity_id: D.EntityId,
    threshold: float,  # From kwargs
    alert_level: str,  # From kwargs
):
    temp = float(new_state.state) if new_state.state else 0.0
    if temp > threshold:
        self.logger.log(
            alert_level,
            "Temperature %s (%.1f°F) exceeds threshold %.1f°F",
            entity_id,
            temp,
            threshold,
        )
```

## Custom Extractors

You can create custom extractors using the `Annotated` type and either existing accessors from [`accessors`][hassette.event_handling.accessors] or your own callable:

### Using Built-in Accessors

```python
from typing import Annotated
from hassette import accessors as A
from hassette.events import RawStateChangeEvent

async def on_light_change(
    self,
    brightness: Annotated[float | None, A.get_attr_new("brightness")],
    color_temp: Annotated[int | None, A.get_attr_new("color_temp")],
):
    self.logger.info("Brightness: %s, Color temp: %s", brightness, color_temp)
```

### Writing Your Own Extractor

Any callable that accepts an event and returns a value can be used as an extractor:

```python
from typing import Annotated
from hassette.events import RawStateChangeEvent

def get_friendly_name(event: RawStateChangeEvent) -> str:
    """Extract friendly_name from new state attributes."""
    new_state = event.payload.data.new_state
    if new_state and "attributes" in new_state:
        return new_state["attributes"].get("friendly_name", "Unknown")
    return "Unknown"

async def on_state_change(
    self,
    name: Annotated[str, get_friendly_name],
):
    self.logger.info("Changed: %s", name)
```

### Advanced: Extractor + Converter Pattern

For more complex scenarios, you can use the `AnnotationDetails` class to combine extraction and type conversion:

```python
from typing import Annotated
from hassette import dependencies as D
from hassette.dependencies.annotations import AnnotationDetails
from hassette.events import RawStateChangeEvent

def extract_timestamp(event: RawStateChangeEvent) -> str:
    """Extract last_changed timestamp from new state."""
    new_state = event.payload.data.new_state
    return new_state.get("last_changed", "") if new_state else ""

def convert_to_datetime(value: str, _to_type: type) -> datetime:
    """Convert ISO string to datetime."""
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

LastChanged = Annotated[
    datetime,
    AnnotationDetails(extractor=extract_timestamp, converter=convert_to_datetime),
]

async def on_state_change(
    self,
    changed_at: LastChanged,
):
    self.logger.info("State changed at: %s", changed_at)
```

## Automatic Type Conversion with TypeRegistry

Hassette's dependency injection system uses the [TypeRegistry](type-registry.md) to automatically convert extracted values to match your type annotations. This works seamlessly with custom extractors.

### How It Works

When you use a custom extractor with a type annotation, the DI system:

1. **Extracts the value** using your extractor function
2. **Checks the type** of the extracted value against your annotation
3. **Automatically converts** if needed using the TypeRegistry
4. **Injects the converted value** into your handler

This means you can write simple extractors that return raw values, and let TypeRegistry handle the type conversion:

```python
from typing import Annotated
from hassette import accessors as A

async def on_light_change(
    self,
    # Extractor returns string "200" from HA
    # TypeRegistry automatically converts to int
    brightness: Annotated[int | None, A.get_attr_new("brightness")],

    # Extractor returns string "on" from HA
    # TypeRegistry automatically converts to bool
    is_on: Annotated[bool, A.get_attr_new("state")],
):
    if is_on and brightness and brightness > 200:
        self.logger.info("Light is very bright: %d", brightness)
```

### Built-in Conversions

The TypeRegistry provides comprehensive built-in conversions for common types:

- **Numeric types**: `str` ↔ `int`, `float`, `Decimal`
- **Boolean**: `str` → `bool` (handles `"on"`, `"off"`, `"true"`, `"false"`, etc.)
- **DateTime types**: `str` → `datetime`, `date`, `time` (stdlib), and `whenever` types
- **And more**: See [Value Converters Reference](value-converters.md)

**Examples:**
```python
from typing import Annotated
from hassette import accessors as A
from decimal import Decimal
from datetime import datetime

async def on_sensor_change(
    self,
    # String "23.5" → float 23.5
    temperature: Annotated[float, A.get_attr_new("temperature")],

    # String "99" → int 99
    battery: Annotated[int | None, A.get_attr_new("battery_level")],

    # String "0.1234" → Decimal("0.1234") (high precision)
    precise_value: Annotated[Decimal | None, A.get_attr_new("value")],

    # ISO string → datetime object
    last_seen: Annotated[datetime | None, A.get_attr_new("last_seen")],
):
    self.logger.info(
        "Temp: %.1f°C, Battery: %d%%, Precise: %s, Last seen: %s",
        temperature,
        battery or 0,
        precise_value,
        last_seen,
    )
```

### Custom Type Converters

You can register your own type converters for custom types:

```python
from hassette.core.type_registry import register_type_converter_fn
from enum import Enum

class FanSpeed(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

@register_type_converter_fn(error_message="'{value}' is not a valid FanSpeed")
def str_to_fan_speed(value: str) -> FanSpeed:
    """Convert string to FanSpeed enum.

    Types are inferred from the function signature.
    """
    return FanSpeed(value.lower())

# Now you can use it in handlers
async def on_fan_change(
    self,
    # String "high" → FanSpeed.HIGH (automatic)
    speed: Annotated[FanSpeed, A.get_attr_new("speed")],
):
    self.logger.info("Fan speed: %s", speed.value)
```

### When Conversion Happens

Type conversion only occurs when:
1. The extracted value type doesn't match the annotation type
2. A converter is registered for the `(from_type, to_type)` pair

If types already match, no conversion is performed (zero overhead).

### Bypassing Automatic Conversion

If you want to handle conversion yourself, you can:

1. **Use `Any` type annotation** to receive the raw value:
   ```python
   from typing import Any, Annotated

   async def handler(
       # No conversion - receive raw value
       raw_value: Annotated[Any, A.get_attr_new("brightness")],
   ):
       # Handle conversion yourself
       brightness = int(raw_value) if raw_value else None
   ```

2. **Provide a custom converter** in `AnnotationDetails`:
   ```python
   from hassette.dependencies.annotations import AnnotationDetails

   def my_converter(value: Any, to_type: type) -> int:
       # Your custom conversion logic
       return int(value) * 100

   BrightnessPercent = Annotated[
       int,
       AnnotationDetails(
           extractor=A.get_attr_new("brightness"),
           converter=my_converter,
       ),
   ]
   ```

### Error Handling

When type conversion fails, Hassette provides clear error messages:

```python
# If "not_a_number" can't be converted to int
async def handler(
    self,
    value: Annotated[int, A.get_attr_new("invalid_field")],
):
    pass

# Error: "Cannot convert 'not_a_number' to integer"
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
3. **Builds extractors** for each parameter that knows how to pull data from events
4. **Converts types** using the StateRegistry for state objects, converting raw dictionaries to typed Pydantic models
5. **Injects values** at call time, passing extracted and converted values as keyword arguments

The core implementation lives in:
- [`extraction`][hassette.bus.extraction] - Signature inspection and parameter extraction
- [`dependencies`][hassette.event_handling.dependencies] - Pre-defined DI annotations
- [`accessors`][hassette.event_handling.accessors] - Low-level event data accessors

## See Also

- [Type Registry](type-registry.md) — automatic type conversion system
- [Value Converters](value-converters.md) — complete list of built-in type conversions
- [State Registry](state-registry.md) — domain to state model mapping
