# States

The `States` resource provides typed, domain-organized access to all Home Assistant entity states through a local cache that's automatically kept up-to-date via state change events.

## Overview

Similar to AppDaemon's state cache, Hassette maintains a local copy of all entity states and updates them in real-time as state changes occur in Home Assistant. This eliminates the need for API calls when reading state and provides instant, synchronous-like access to entity data.

### Key Features

- **Automatic updates** - Listens to state change events and keeps the cache current
- **Domain-specific accessors** - Access entities by domain with full typing (e.g., `self.states.light`, `self.states.sensor`)
- **No async/await needed** - Direct, synchronous access to cached states
- **Type-safe** - Full Pydantic model support with IDE autocompletion
- **Efficient iteration** - Iterate over all entities in a domain
- **Generic access** - Typed getter for any domain using `self.states.get[ModelType]("entity_id")`

## Basic Usage

### Accessing States by Domain

Each domain has a dedicated property that returns a `DomainStates` container:

```python
from hassette import App

class MyApp(App):
    async def on_initialize(self):
        # Get a specific light
        bedroom_light = self.states.light.get("light.bedroom")
        if bedroom_light:
            self.logger.info(f"Bedroom light is {bedroom_light.value}")
            self.logger.info(f"Brightness: {bedroom_light.attributes.brightness}")

        # Get a specific sensor
        temp_sensor = self.states.sensor.get("sensor.living_room_temp")
        if temp_sensor:
            self.logger.info(f"Temperature: {temp_sensor.value}°F")
```

### Iterating Over Domain Entities

```python
async def on_initialize(self):
    # Iterate over all lights
    for entity_id, light in self.states.light:
        self.logger.info(f"{entity_id}: {light.value} (brightness: {light.attributes.brightness})")

    # Count entities in a domain
    light_count = len(self.states.light)
    self.logger.info(f"Found {light_count} lights")

    # Find sensors with low battery
    for entity_id, sensor in self.states.sensor:
        if hasattr(sensor.attributes, "battery_level"):
            if sensor.attributes.battery_level < 20:
                self.logger.warning(f"{entity_id} battery low: {sensor.attributes.battery_level}%")
```

### Typed Generic Access

For domains without dedicated properties or when you need explicit typing:

```python
from hassette.models import states

async def on_initialize(self):
    # Typed access for any entity
    my_light = self.states.get[states.LightState]("light.bedroom")
    my_climate = self.states.get[states.ClimateState]("climate.living_room")

    # Use .get() method for None-safe access
    optional_light = self.states.get[states.LightState].get("light.maybe_exists")
    if optional_light:
        self.logger.info(f"Light exists: {optional_light.value}")
```

### Accessing All States

```python
async def on_initialize(self):
    # Get all states as a dictionary
    all_states = self.states.all

    # Filter or process as needed
    for entity_id, state in all_states.items():
        if state.is_unavailable:
            self.logger.warning(f"{entity_id} is unavailable")
```

## Common Patterns

### Checking Entity Availability

```python
async def safe_turn_on(self, entity_id: str):
    light = self.states.light.get(entity_id)

    if not light:
        self.logger.error(f"{entity_id} not found in state cache")
        return

    if light.is_unavailable:
        self.logger.warning(f"{entity_id} is unavailable")
        return

    await self.api.turn_on(entity_id)
```

### Monitoring Multiple Entities

```python
async def check_all_doors(self):
    door_entities = [
        "binary_sensor.front_door",
        "binary_sensor.back_door",
        "binary_sensor.garage_door"
    ]

    open_doors = []
    for entity_id in door_entities:
        door = self.states.binary_sensor.get(entity_id)
        if door and door.value == "on":  # Binary sensors: on = open
            open_doors.append(entity_id)

    if open_doors:
        self.logger.warning(f"Open doors: {', '.join(open_doors)}")
```

### Aggregating Sensor Data

```python
async def calculate_average_temp(self):
    temp_sensors = [
        "sensor.bedroom_temp",
        "sensor.living_room_temp",
        "sensor.kitchen_temp"
    ]

    temps = []
    for entity_id in temp_sensors:
        sensor = self.states.sensor.get(entity_id)
        if sensor and not sensor.is_unavailable:
            try:
                temps.append(float(sensor.value))
            except (ValueError, TypeError):
                pass

    if temps:
        avg = sum(temps) / len(temps)
        self.logger.info(f"Average temperature: {avg:.1f}°F")
        return avg
```

### Finding Entities by Criteria

```python
async def find_lights_above_brightness(self, threshold: int):
    bright_lights = []

    for entity_id, light in self.states.light:
        if light.value == "on" and light.attributes.brightness:
            if light.attributes.brightness > threshold:
                bright_lights.append((entity_id, light.attributes.brightness))

    # Sort by brightness
    bright_lights.sort(key=lambda x: x[1], reverse=True)
    return bright_lights
```

### Using State in Event Handlers

```python
async def on_initialize(self):
    self.bus.on_state_change(
        "binary_sensor.motion",
        handler=self.on_motion,
        changed_to="on"
    )

async def on_motion(self):
    # Check if lights are off before turning on
    living_room_light = self.states.light.get("light.living_room")

    if living_room_light and living_room_light.value == "off":
        # Check time of day from sun state
        sun = self.states.sun.get("sun.sun")
        if sun and sun.value == "below_horizon":
            await self.api.turn_on("light.living_room", brightness=128)
```

## Performance Considerations

### When to Use `self.states` vs `self.api`

**Use `self.states` (recommended):**
- Reading current state in event handlers
- Scheduled tasks that check entity states
- Iterating over multiple entities
- Any synchronous state access
- Checking entity availability before service calls

**Use `self.api.get_state()` (rare):**
- When you specifically need to force a fresh read from Home Assistant
- During app initialization if you need state before the cache is populated
- For entities that change extremely rapidly and you need the absolute latest value

### Cache Behavior

The state cache is:
- **Initialized on startup** - Fetches all states from Home Assistant when Hassette starts
- **Automatically updated** - Listens to `state_changed` events and updates the cache in real-time
- **Cleared on HA restart** - Automatically resyncs when Home Assistant restarts
- **Thread-safe** - Protected by locks for safe concurrent access

### Memory Efficiency

The states cache uses memory proportional to the number of entities in your Home Assistant instance. For typical installations (hundreds of entities), this is negligible. For very large installations (thousands of entities), the cache still uses only a few megabytes of RAM.

## Examples

### Complete App Using States

```python
from hassette import App, AppConfig
from hassette.models import states
from pydantic import Field

class LightManagerConfig(AppConfig):
    motion_sensor: str = Field(..., description="Motion sensor entity ID")
    lights: list[str] = Field(..., description="Light entity IDs to control")
    timeout_seconds: int = Field(300, description="Turn off after this many seconds")

class LightManager(App[LightManagerConfig]):
    async def on_initialize(self):
        # Subscribe to motion sensor
        self.bus.on_state_change(
            self.app_config.motion_sensor,
            handler=self.on_motion,
            changed_to="on"
        )

        # Subscribe to motion clearing
        self.bus.on_state_change(
            self.app_config.motion_sensor,
            handler=self.on_motion_cleared,
            changed_to="off"
        )

    async def on_motion(self):
        # Check if any lights are already on using state cache
        lights_on = []
        for light_id in self.app_config.lights:
            light = self.states.light.get(light_id)
            if light and light.value == "on":
                lights_on.append(light_id)

        if lights_on:
            self.logger.info(f"Lights already on: {lights_on}")
            return

        # Check if it's dark using sun state
        sun = self.states.sun.get("sun.sun")
        if sun and sun.value == "below_horizon":
            self.logger.info("Motion detected after sunset, turning on lights")
            for light_id in self.app_config.lights:
                await self.api.turn_on(light_id, brightness=255)

    async def on_motion_cleared(self):
        # Schedule lights to turn off after timeout
        self.scheduler.run_in(
            self.turn_off_if_no_motion,
            delay=self.app_config.timeout_seconds
        )

    async def turn_off_if_no_motion(self):
        # Check if motion is still clear
        motion = self.states.binary_sensor.get(self.app_config.motion_sensor)
        if motion and motion.value == "off":
            self.logger.info("No motion for timeout period, turning off lights")
            for light_id in self.app_config.lights:
                await self.api.turn_off(light_id)
```

## See Also

- [API Documentation](../api/index.md) - For direct API calls to Home Assistant
- [Event Bus](../bus/index.md) - For listening to state changes
- [State Models](../../api-reference/models/states.md) - Complete list of state models
