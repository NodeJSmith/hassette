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

State classes register themselves automatically when they define a `domain` class variable:

```python
from hassette.models.states import BaseState

class LightState(BaseState):
    """State model for light entities."""
    domain: ClassVar[str] = "light"
    attributes: LightAttributes
```

During Hassette startup, the StateRegistry:

1. Scans all subclasses of `BaseState` using breadth-first search
2. Calls each class's `get_domain()` method
3. Builds a bidirectional mapping: `domain` ↔ `StateClass`

### Domain Lookup

When you need to convert state data, the registry provides lookup functions:

```python
from hassette.context import get_state_registry

registry = get_state_registry()

# Get class for a domain
state_class = registry.get_class_for_domain("light")
# Returns: LightState

# Get domain for a class
domain = registry.get_domain_for_class(LightState)
# Returns: "light"

# List all registered domains
domains = registry.all_domains()
# Returns: ["binary_sensor", "light", "sensor", "switch", ...]

# List all registered classes
classes = registry.all_classes()
# Returns: [BinarySensorState, LightState, SensorState, ...]
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

# 2. StateRegistry determines model class based on "sensor" domain
# → Returns SensorState class

# 3. Pydantic model validation begins
# 4. BaseState._validate_domain_and_state checks value_type ClassVar
# 5. TypeRegistry converts "23.5" (str) → 23.5 (float)
# 6. Validation completes with properly typed value

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

During validation, if the raw state value doesn't match `value_type`, the TypeRegistry automatically converts it:

```python
# Without value_type: state would be "23.5" (string)
# With value_type = (str, int, float): state is 23.5 (float)
```

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
# StateRegistry determines this is a LightState
light_state = registry.try_convert_state(light_dict)

# TypeRegistry also works in dependency injection
from hassette import dependencies as D, accessors as A

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
from hassette.context import get_state_registry

registry = get_state_registry()

# Raw state data from Home Assistant
state_dict = {
    "entity_id": "light.bedroom",
    "state": "on",
    "attributes": {"brightness": 200},
    # ... more fields
}

# Convert to typed model
light_state = registry.try_convert_state(state_dict)
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

async def on_reddit_change(
    self,
    new_state: D.StateNew[RedditState],
):
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

### RegistryNotReadyError

Raised when trying to use the registry before it's initialized:

```python
from hassette.exceptions import RegistryNotReadyError

try:
    state_class = registry.get_class_for_domain("light")
except RegistryNotReadyError:
    print("StateRegistry not yet initialized")
```

**Solution:** Wait for Hassette to complete initialization, or ensure you're using the registry within app lifecycle methods (e.g., `on_initialize`).

### InvalidDataForStateConversionError

Raised when state data is malformed or missing required fields:

```python
from hassette.exceptions import InvalidDataForStateConversionError

try:
    state = registry.try_convert_state(None)  # Invalid data
except InvalidDataForStateConversionError as e:
    print(f"Invalid state data: {e}")
```

### InvalidEntityIdError

Raised when the entity_id format is invalid:

```python
from hassette.exceptions import InvalidEntityIdError

try:
    # Entity ID must have format "domain.entity"
    state = registry.try_convert_state({"entity_id": "invalid"})
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

The StateRegistry is available via the application context:

```python
from hassette.context import get_state_registry

registry = get_state_registry()
```

In apps, you typically don't need direct access - the DI system and API methods handle conversions automatically.

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

### Registry Inspection

Useful for debugging or dynamic code generation:

```python
registry = get_state_registry()

# Check if a domain is registered
if "light" in registry.domain_to_class:
    print("Light domain is registered")

# Get all domains
for domain in registry.all_domains():
    state_class = registry.get_class_for_domain(domain)
    print(f"{domain} -> {state_class.__name__}")

# Check if a class is registered
if LightState in registry.class_to_domain:
    domain = registry.get_domain_for_class(LightState)
    print(f"LightState handles domain: {domain}")
```

## Implementation Notes

### Initialization Sequence

1. **Hassette startup**: StateRegistry is created as a core resource
2. **After initialization phase**: `build_registry()` scans all BaseState subclasses
3. **Registration**: Each state class with a domain is registered
4. **Ready**: Registry is marked as ready for use

### Thread Safety

The StateRegistry is built once during initialization and is read-only afterward, making it safe for concurrent access from multiple apps and handlers.

### Performance

- Domain lookups are O(1) dictionary operations
- Registration happens once at startup
- State conversion uses Pydantic's optimized validation

### Listing Domain Mappings

For debugging or inspection, you can list all registered domain mappings:

```python
from hassette.context import get_state_registry

registry = get_state_registry()

# Get list of (domain, state_class) tuples
mappings = registry.list_domain_mappings()
for domain, state_class in mappings:
    print(f"{domain} → {state_class.__name__}")
```

Output example:
```
binary_sensor → BinarySensorState
light → LightState
sensor → SensorState
switch → SwitchState
...
```

This is useful for:
- Verifying custom state classes are registered
- Debugging domain resolution issues
- Generating documentation or reports
- Understanding which domains are supported

## See Also

- [Type Registry](type-registry.md) — automatic value type conversion
- [Dependency Injection](dependency-injection.md) — using StateRegistry via DI annotations
- [Custom States](custom-states.md) — defining your own state classes
- [Value Converters](value-converters.md) — complete list of built-in type conversions
