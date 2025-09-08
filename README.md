# Hassette

[![PyPI version](https://badge.fury.io/py/hassette.svg)](https://badge.fury.io/py/hassette)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A modern, async-first Python framework for building Home Assistant automations with type safety and developer experience in mind.

Hassette brings the developer experience of modern Python projects to Home Assistant automation development. Think of it as an alternative to AppDaemon, built with today's Python tooling and best practices.

## ✨ Key Features

- **🌟 Async-first**: Built on `asyncio` with proper async/await patterns
- **🔧 Type-safe**: Full typing support for entities, events, and configurations
- **⚡ Event-driven**: Powerful event bus with flexible filtering and routing
- **⏰ Flexible scheduling**: Custom scheduler with cron and interval support
- **🎯 Simple configuration**: TOML-based app configuration with Pydantic validation
- **🧪 Tested**: Core and utilities are tested with unit and integration tests, user testing framework is coming soon!

## 🚀 Quick Start

### Installation

```bash
pip install hassette
```

### Basic Example

Create a simple battery monitoring app:

```python
from hassette import App, AppConfig

class BatteryConfig(AppConfig):
    threshold: float = 20
    notify_entity: str = "my_mobile_phone"

class BatteryMonitor(App[BatteryConfig]):
    async def initialize(self):
        # Run battery check every morning at 9 AM
        self.scheduler.run_cron(self.check_batteries, hour=9)

    async def check_batteries(self):
        states = await self.api.get_states()
        low_batteries = []

        for device in states:
            if hasattr(device.attributes, 'battery_level'):
                level = device.attributes.battery_level
                if level and level < self.app_config.threshold:
                    low_batteries.append(f"{device.entity_id}: {level}%")

        if low_batteries:
            message = "Low battery devices: " + ",".join(low_batteries)
            await self.api.call_service("notify", self.app_config.notify_entity, message=message)
```

### Configuration

Create `hassette.toml`:

```toml
[apps.battery_monitor]
enabled = true
app_path = "battery_monitor.py"
class_name = "BatteryMonitor"

[apps.battery_monitor.config]
threshold = 15
notify_entity = "notify.mobile_app_phone"
```

### Running

```bash
run-hassette
```

## 📚 Core Concepts

### Apps

Apps are the building blocks of your automations. They can:
- 👂 Listen to Home Assistant events and state changes
- ⏰ Schedule recurring tasks
- 📞 Call Home Assistant services
- 💾 Maintain their own state and configuration

### Configuration

Apps are configured via a `hassette.toml` file using Pydantic models for validation. Custom configuration is optional but recommended for most use cases.

**Configuration file (`hassette.toml`):**
```toml
[apps.my_app]  # Validated by AppManifest during Hassette startup
enabled = true
app_path = "my_app.py"
class_name = "MyApp"

[apps.my_app.config]  # Validated by your Pydantic class when MyApp initializes
entity_id = "light.living_room"
brightness_when_home = 200
brightness_when_away = 50
```

**App with typed configuration:**
```python
from hassette import App, AppConfig
from pydantic import Field

class MyAppConfig(AppConfig):
    entity_id: str = Field(..., description="Entity ID of the light")
    brightness_when_home: int = Field(200, ge=0, le=255)
    brightness_when_away: int = Field(50, ge=0, le=255)

class MyApp(App[MyAppConfig]):
    async def initialize(self):
        # Fully typed access to configuration
        light_id = self.app_config.entity_id
        brightness = self.app_config.brightness_when_home
```

### Event Handling

Subscribe to state changes with powerful filtering options:

```python
# Listen to all light state changes
self.bus.on_entity("light.*", handler=self.light_changed)

# Listen to specific state transitions
self.bus.on_entity("binary_sensor.motion", handler=self.motion_detected, changed_to="on")

# Listen to specific attribute changes
self.bus.on_attribute("mobile_device.my_phone", "battery_level", self.battery_level_changed)

# Listen to Hassette events (including your own apps' events)
self.bus.on_hassette_service_started(handler=self.my_app_started)
```

**Advanced filtering with complex conditions:**
```python
from hassette import predicates

# Create specific attribute change filters
light_color_changed = predicates.AttrChanged("color", to="alice_blue")
brightness_changed = predicates.AttrChanged("brightness", from_=0)  # leaving 'to' undefined means "any value"

# Combine multiple conditions
self.bus.on_entity("light.*", handler=self.light_changed,
                   where=predicates.AllOf(brightness_changed, light_color_changed))
```

### Scheduling

Schedule tasks with cron expressions or intervals using [`whenever`](https://github.com/ariebovenberg/whenever):

```python
# Every day at 6 AM
self.scheduler.run_cron(self.morning_routine, hour=6)

# Every 30 seconds
from whenever import TimeDelta
self.scheduler.run_every(self.check_sensors, TimeDelta(seconds=30))
# or simply:
self.scheduler.run_every(self.check_sensors, interval=30)

# One-time delayed execution
self.scheduler.run_in(self.delayed_task, delay=60*5)  # In 5 minutes
```

### Type Safety

Hassette provides comprehensive typing for Home Assistant entities and events:

```python
async def handle_light_change(self, event: StateChangeEvent[LightState]):
    # Event structure: event → payload → data
    # - event: Contains payload and topic (used for bus filtering)
    # - payload: Either HassPayload or HassettePayload with event_type and data
    # - data: The actual state change information

    light = event.payload.data
    if light.new_state_value == "on":
        brightness = light.new_state.attributes.brightness
        self.logger.info(f"Light turned on with brightness {brightness}")

    # Type information available at every level:
    reveal_type(light)                           # StateChangePayload[LightState]
    reveal_type(light.new_state)                 # LightState
    reveal_type(light.new_state.value)           # str (the "state" value)
    reveal_type(light.new_state.attributes.color_temp_kelvin)  # float
```

## 📁 Project Structure

```
your_project/
├── hassette.toml          # Configuration
├── apps/
│   ├── battery_monitor.py
│   ├── presence.py
│   └── climate_control.py
└── .env                   # Environment variables (optional)
```

## 🔧 Advanced Features

### Multiple App Instances

Configure multiple instances of the same app with different configurations:

```toml
[apps.presence]
enabled = true
app_path = "presence.py"
class_name = "PresenceApp"

# Multiple instances using [[apps.presence.config]]
[[apps.presence.config]]
name = "upstairs"
motion_sensor = "binary_sensor.upstairs_motion"
lights = ["light.bedroom", "light.hallway"]

[[apps.presence.config]]
name = "downstairs"
motion_sensor = "binary_sensor.downstairs_motion"
lights = ["light.living_room", "light.kitchen"]
```

**Single instance configuration:**
```toml
[apps.presence.config]  # Note: single [config] instead of [[config]]
name = "main"
motion_sensor = "binary_sensor.main_motion"
lights = ["light.living_room", "light.kitchen"]
```


### Synchronous Apps

For simpler synchronous use cases, use `AppSync`. Only a few changes are required:

1. Inherit from `AppSync` instead of `App`.
2. Implement `initialize_sync` instead of `initialize`.
3. Use the `.sync` API for Home Assistant calls.

```python
from hassette import AppSync

class SimpleApp(AppSync[AppConfig]):
    def initialize_sync(self):
        # scheduler and bus are available in sync apps too with no changes required
        self.scheduler.run_in(self.check_batteries, 10)
        self.bus.on_entity("*", handler=self.handle_sensor_event)

    def my_task(self):
        # Use .sync API for synchronous Home Assistant calls
        states = self.api.sync.get_states()
        # All async API methods have sync equivalents
```


## 📖 Examples

Check out the [`examples/`](examples/) directory for more complete examples:
- [Battery monitoring](examples/battery.py)
- [Presence detection](examples/presence.py)
- [Sensor notifications](examples/sensor_notification.py)

## 🛣️ Status & Roadmap

Hassette is brand new and under active development. We follow semantic versioning and recommend pinning a minor version while the API stabilizes.

### Current Focus Areas

- 📚 **Comprehensive documentation**
- 🔐 **Enhanced type safety**: Service calls/responses, additional state types
- 🏗️ **Entity classes**: Include state data and service functionality (e.g. `LightEntity.turn_on()`)
- 🔄 **Enhanced error handling**: Better retry logic and error recovery
- 🧪 **Testing improvements**:
  - 📊 More tests for core and utilities
  - 🛠️ Test fixtures and framework for user apps
  - 🚫 No more manual state changes in HA Developer Tools for testing!
- 🐳 **Docker deployment support**

See the full [roadmap](roadmap.md) for details - open an issue or PR if you'd like to contribute or provide feedback!

## 🤝 Contributing

Hassette is in active development and contributions are welcome! Whether you're:

- 🐛 Reporting bugs
- 💡 Suggesting features
- 📝 Improving documentation
- 🔧 Contributing code

Early feedback and contributions help shape the project's direction.

## 📄 License

[MIT](LICENSE)

---

**Note**: Hassette requires Python 3.11+ and a running Home Assistant instance with WebSocket API access.
