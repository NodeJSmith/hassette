# State Registry

The **StateRegistry** is a core component of Hassette that maintains a mapping between Home Assistant domains (like `light`, `sensor`, `switch`) and their corresponding Pydantic state model classes. It enables automatic type conversion when working with state data from Home Assistant.

## What is the State Registry?

When Home Assistant sends state change events, the state data arrives as untyped dictionaries. The StateRegistry allows Hassette to automatically convert these dictionaries into typed Pydantic models based on the entity's domain:

```python
# Raw data from Home Assistant (untyped dict)
{
    "entity_id": "light.bedroom",
    "state": "on",
    "attributes": {"brightness": 200, "color_temp": 370},
    ...
}

# After StateRegistry conversion (typed model)
LightState(
    entity_id="light.bedroom",
    state="on",
    attributes=LightAttributes(brightness=200, color_temp=370),
    ...
)
```

## How It Works

### Automatic Registration

All classes that inherit from BaseState are registered automatically at class creation time if they have a valid domain.

This is done via the `__init_subclass__` hook in BaseState, which adds the class to the global StateRegistry.

```python
from hassette.models.states import BaseState

class LightState(BaseState):
    """State model for light entities."""
    domain: ClassVar[str] = "light"
    attributes: LightAttributes
```


### Domain Lookup

When you need to convert state data, the registry provides lookup functions:

```python
from hassette.context import get_state_registry

registry = get_state_registry()

# Get class for a domain
state_class = registry.resolve(domain="light")
# Returns: LightState
```

## Relationship with TypeRegistry

The StateRegistry and [TypeRegistry](type-registry.md) work together to provide complete type conversion for Home Assistant state data:

**StateRegistry** → Determines which state model class to use based on domain
**TypeRegistry** → Converts raw values to proper Python types during model validation

### The Complete Flow

When state data arrives from Home Assistant, both registries cooperate:

```python
# 1. Raw data from Home Assistant
state_dict = {
    "entity_id": "sensor.temperature",
    "state": "23.5",  # String from HA
    "attributes": {"unit_of_measurement": "°C"}
}

2. StateRegistry determines model class based on "sensor" domain
# → Returns SensorState class

3. Pydantic model validation begins
4. BaseState._validate_domain_and_state checks value_type ClassVar
5. TypeRegistry converts "23.5" (str) → 23.5 (float)
6. Validation completes with properly typed value

sensor_state = registry.try_convert_state(state_dict)
# Result: SensorState with state=23.5 (float)
```

### The value_type ClassVar

State model classes use the `value_type` ClassVar to declare expected state value types:

```python
from typing import ClassVar
from hassette.models.states import BaseState

class SensorState(BaseState):
    """State model for sensor entities."""
    domain: ClassVar[str] = "sensor"
    value_type: ClassVar[type | tuple[type, ...]] = (str, int, float)
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
from hassette import STATE_REGISTRY

# StateRegistry determines this is a LightState
light_state = STATE_REGISTRY.try_convert_state(light_dict)

# TypeRegistry also works in dependency injection
from hassette import accessors as A

async def handler(
    # TypeRegistry converts attribute values too
    brightness: Annotated[int, A.get_attr_new("brightness")],
):
    # brightness is int, not string, thanks to TypeRegistry
    pass
```

See [TypeRegistry](type-registry.md) for more details on automatic value conversion.

## State Conversion

The primary use of the StateRegistry is converting raw state dictionaries to typed models:

### Direct Conversion

```python
from hassette import STATE_REGISTRY

# Raw state data from Home Assistant
state_dict = {
    "entity_id": "light.bedroom",
    "state": "on",
    "attributes": {"brightness": 200},
    # ... more fields
}

# Convert to typed model
light_state = STATE_REGISTRY.try_convert_state(state_dict)
# Returns: LightState instance
```

The `try_convert_state` method:
- Extracts the domain from the entity_id
- Looks up the corresponding state class
- Converts the dictionary to a Pydantic model instance
- Falls back to `BaseState` for unknown domains

### Via Dependency Injection

The StateRegistry integrates seamlessly with [dependency injection](dependency-injection.md):

```python
from hassette import App, dependencies as D, states

class MyApp(App):
    async def on_light_change(
        self,
        new_state: D.StateNew[states.LightState],  # Automatically converted
    ):
        # new_state is already a LightState instance
        brightness = new_state.attributes.brightness
```

Behind the scenes, the DI system uses `convert_state_dict_to_model()` which calls the StateRegistry.

## Custom State Classes

You can define custom state classes for your own integrations or to extend existing ones:

### Basic Custom State

```python
from typing import ClassVar
from pydantic import BaseModel
from hassette.models.states import BaseState

class RedditAttributes(BaseModel):
    karma: int | None = None
    subreddit: str | None = None
    friendly_name: str | None = None

class RedditState(BaseState):
    """State model for custom reddit sensor."""
    domain: ClassVar[str] = "reddit"
    attributes: RedditAttributes
```

Once defined, your custom state class is automatically registered and can be used throughout Hassette:

```python
from hassette import dependencies as D

async def on_reddit_change(self, new_state: D.StateNew[RedditState]):
    print(f"Reddit karma: {new_state.attributes.karma}")
```

### Domain Override

If you want to override the default state class for a domain (for example, to add custom attributes), define your class after imports:

```python
from typing import ClassVar
from hassette.models.states import SensorState, SensorAttributes

class CustomSensorAttributes(SensorAttributes):
    custom_field: str | None = None

class CustomSensorState(SensorState):
    """Extended sensor state with custom attributes."""
    domain: ClassVar[str] = "sensor"
    attributes: CustomSensorAttributes
```

The StateRegistry will log a warning but use your custom class:

```
WARNING - Overriding original state class SensorState for domain 'sensor' with CustomSensorState
```

## Union Type Support

The StateRegistry works with Union types, automatically selecting the correct state class:

```python
from hassette import dependencies as D, states

async def on_sensor_change(
    self,
    new_state: D.StateNew[states.SensorState | states.BinarySensorState],
):
    # StateRegistry determines the correct type based on domain
    if new_state.domain == "sensor":
        # new_state is SensorState
        value = float(new_state.state)
    else:
        # new_state is BinarySensorState
        is_on = new_state.state == "on"
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
from hassette import STATE_REGISTRY
from hassette.exceptions import InvalidDataForStateConversionError

try:
    state = STATE_REGISTRY.try_convert_state(None)  # Invalid data
except InvalidDataForStateConversionError as e:
    print(f"Invalid state data: {e}")
```

### InvalidEntityIdError

Raised when the entity_id format is invalid:

```python
from hassette import STATE_REGISTRY
from hassette.exceptions import InvalidEntityIdError

try:
    # Entity ID must have format "domain.entity"
    state = STATE_REGISTRY.try_convert_state({"entity_id": "invalid"})
except InvalidEntityIdError as e:
    print(f"Invalid entity ID: {e}")
```

### UnableToConvertStateError

Raised when conversion to the target state class fails:

```python
from hassette.exceptions import UnableToConvertStateError

try:
    state = registry.try_convert_state(data)
except UnableToConvertStateError as e:
    print(f"Conversion failed: {e}")
    # Falls back to BaseState or re-raises depending on context
```

## Integration with Other Components

### With Dependency Injection

The StateRegistry powers all state type conversions in [dependency injection](dependency-injection.md):

```python
# DI annotation uses StateRegistry internally
new_state: D.StateNew[states.LightState]
```

### With API Resource

The API's `get_state()` method uses the StateRegistry:

```python
# Automatically converts to LightState
light_state = await self.api.get_state("light.bedroom", states.LightState)
```

### With States Resource

The States cache uses the StateRegistry for all state lookups:

```python
# Returns typed LightState instance
light = self.states.light.get("light.bedroom")
```

## Advanced Usage

### Accessing the Registry

The StateRegistry can be imported from Hassette directly:

```python
from hassette import STATE_REGISTRY

registry = STATE_REGISTRY
```

In apps, you typically don't need direct access - the DI system and API methods handle conversions automatically.

If you do need to access it, it is accessible through `self.hassette.state_registry`.

### Custom Converters

For advanced use cases, you can use the lower-level conversion functions:

```python
from hassette.core.state_registry import convert_state_dict_to_model
from hassette.models import states

# Convert with explicit target type
state = convert_state_dict_to_model(state_dict, states.LightState)

# Convert with Union type
state = convert_state_dict_to_model(
    state_dict,
    states.LightState | states.SwitchState
)
```

## See Also

- [Type Registry](type-registry.md) - automatic value type conversion
- [Dependency Injection](dependency-injection.md) - using StateRegistry via DI annotations
- [Custom States](custom-states.md) - defining your own state classes
