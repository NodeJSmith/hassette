# AI Agent Guide for Hassette

This document provides guidance for AI coding agents working with the Hassette project. Hassette is a modern, async-first Python framework for building Home Assistant automations with strong typing and developer experience focus.

## Project Overview

**Purpose**: Hassette is a framework for building Home Assistant automations with async-first design and strong typing. It provides a simple, transparent framework with minimal magic and clear extension points.

**Key Features**:
- Modern developer experience with typed APIs, Pydantic models, and IDE-friendly design
- Async-first architecture designed for modern Python
- Simple, transparent framework with minimal magic
- Focused mission: run user-defined apps that interact with Home Assistant

## Architecture Overview

### Core Components

- **Runtime Core**: `src/hassette/core/core.py` (`Hassette`) builds a tree of `Resource`/`Service` instances
- **Task Orchestration**: `core/resources/tasks.py` (`TaskBucket`) handles background task management
- **Background Services**: Located in `src/hassette/core/services/`
  - `_Websocket`: Streams Home Assistant events
  - `BusService`: Routes events to appropriate handlers
  - `ApiResource`: Manages REST/WebSocket clients
  - `SchedulerService`: Runs scheduled jobs
  - `AppHandler`: Loads and manages user apps
  - `FileWatcherService`: Listens for file/config changes
  - `ServiceWatcher`: Supervises service dependencies
  - `HealthService`: Exposes system status

### Data Flow
```
_Websocket → events.create_event_from_hass → BusService.dispatch → per-owner Bus resources → app handlers
```

API calls reuse both the shared WebSocket and REST client managed by `ApiResource`.

## App Development Pattern

### Base App Structure

Apps inherit from `App[AppConfigT]` (async) or `AppSync` (sync) and implement lifecycle hooks:

```python
from typing import Annotated
from hassette import App, AppConfig, states
from hassette import dependencies as D

class MyConfig(AppConfig):
    light: str

class MyApp(App[MyConfig]):
    async def on_initialize(self):
        self.bus.on_state_change(
            self.app_config.light,
            handler=self.on_light_change,
            changed_to="on",
        )

    async def on_light_change(
        self,
        new_state: D.StateNew[states.LightState],
        entity_id: D.EntityId,
    ):
        friendly_name = new_state.attributes.friendly_name or entity_id
        await self.api.call_service("notify", "mobile_app_me", message=f"{friendly_name} turned on")
```

### Key Lifecycle Hooks
- `before_initialize`, `on_initialize`, `after_initialize`
- `before_shutdown`, `on_shutdown`, `after_shutdown`
- **Important**: `initialize()` and `shutdown()` are `@final` - override the lifecycle hooks instead
- **Important**: Use `initialize()` and `shutdown()` for work that must not be overridden by subclasses; anything in the lifecycle hooks can be customized by subclasses and therefore skipped if `super()` is not called.

### App Resources
Each app has access to:
- `self.api`: API for Home Assistant interaction
- `self.bus`: Event bus for handling Home Assistant events
- `self.scheduler`: Task scheduling functionality
- `self.task_bucket`: Background task management
- `self.app_config`: Typed configuration specific to the app

## Configuration System

### Configuration Hierarchy
Source priority (highest → lowest):
1. CLI args
2. Init kwargs
3. Environment variables
4. `.env` files
5. Secrets files
6. TOML files (`/config/hassette.toml`, `./hassette.toml`, `./config/hassette.toml`)


### App Configuration
Apps are defined under `[apps.<name>]` in TOML:

```toml
[hassette]
base_url = "http://localhost:8123"
app_dir = "src/apps"

[apps.my_app]
filename = "my_app.py"
class_name = "MyApp"
enabled = true
config = {threshold = 10, always_send = false}
```

**Required fields**: `filename`, `class_name`
**Optional fields**: `app_dir`, `enabled`, `display_name`, `config`

## Dependency Injection System

**Location**: `src/hassette/dependencies/`

Hassette provides a dependency injection system for event handlers, allowing automatic extraction and injection of event data as handler parameters.

### Key Components

**Files**:
- `dependencies/__init__.py` - Public API and documentation
- `dependencies/annotations.py` - Dependency marker classes
- `dependencies/extraction.py` - Signature inspection and extraction logic
- `dependencies/injector.py` - Runtime injector for dependency injection

**Integration**: The `Bus` resource (`core/resources/bus/bus.py`) uses `extract_from_signature` and `validate_di_signature` to process handler signatures and inject values at runtime.

### Available Dependencies

**State Extractors**:
- `StateNew[T]` - Extract new state object, raises if missing
- `StateOld[T]` - Extract old state object, raises if missing
- `MaybeStateNew[T]` - Extract new state object, allows None
- `MaybeStateOld[T]` - Extract old state object, allows None

**Identity Extractors**:
- `EntityId` - Extract entity ID, raises if missing
- `MaybeEntityId` - Extract entity ID, returns sentinel if missing
- `Domain` - Extract domain (e.g., "light", "sensor"), raises if missing
- `MaybeDomain` - Extract domain, returns sentinel if missing

**Other Extractors**:
- `EventContext` - Extract Home Assistant event context
- `TypedStateChangeEvent[T]` - Convert raw event to typed event

**Note**: For attribute extraction and other advanced use cases, use custom extractors with the `Annotated` type and accessors from `hassette.bus.accessors`. See the DI documentation for examples.

### Usage Pattern

```python
from typing import Annotated
from hassette import states
from hassette import dependencies as D
from hassette import accessors as A

async def handler(
    new_state: D.StateNew[states.LightState],
    entity_id: D.EntityId,
):
    # Parameters automatically extracted and injected
    brightness = new_state.attributes.brightness
    # Or use a custom extractor for attributes:
    # brightness: Annotated[int | None, A.get_attr_new("brightness")]
    if brightness and brightness > 200:
        self.logger.info("%s is bright: %d", entity_id, brightness)
```

### Restrictions

- Handlers cannot use positional-only parameters (before `/`)
- Handlers cannot use variadic positional args (`*args`)
- All DI parameters must have type annotations

## Event Bus Usage

### Topics and Events
- Topics defined in `src/hassette/topics.py`
- Common events: `HASS_EVENT_STATE_CHANGED`, `HASSETTE_EVENT_SERVICE_STATUS`, `HASSETTE_EVENT_APP_LOAD_COMPLETED`

### Bus Helpers
```python
# State change handlers with DI
self.bus.on_state_change("binary_sensor.motion", handler=self.on_motion, changed_to="on")
self.bus.on_attribute_change("mobile_device.me", "battery_level", handler=self.on_battery_drop)
self.bus.on_call_service(domain="light", service="turn_on", handler=self.on_turn_on)
```

### Event Filtering
- Predicates located in `core/resources/bus/predicates`
- Config exclusions: `bus_excluded_domains`, `bus_excluded_entities`

## API Conventions

### Async API (`Api`)
```python
# Common operations
states = await self.api.get_states()
state = await self.api.get_state("light.bedroom", states.LightState)
await self.api.call_service("light", "turn_on", entity_id="light.bedroom")
await self.api.fire_event("custom_event", data={"key": "value"})
template_result = await self.api.render_template("{{ states('sensor.temperature') }}")
```

### Sync API (`ApiSyncFacade`)
```python
# For sync apps or when needed
states = self.api.sync.get_states()
self.api.sync.call_service("light", "turn_on", entity_id="light.bedroom")
```

## Scheduler Usage

### Scheduling Patterns
```python
# One-time execution
self.scheduler.run_in(self.poll_devices, 30)  # Run in 30 seconds
self.scheduler.run_once(self.startup_task, "2023-12-25 09:00:00")

# Recurring execution
self.scheduler.run_every(self.flush_cache, interval=300)  # Every 5 minutes
self.scheduler.run_minutely(self.minute_task, minute=30)  # At 30 seconds past each minute
self.scheduler.run_hourly(self.hourly_task, minute=0)     # At the top of each hour
self.scheduler.run_daily(self.daily_task, hour=6, minute=0)  # Daily at 6:00 AM

# Cron-style scheduling
self.scheduler.run_cron(self.morning_job, hour=6, minute=0, name="wake_up")
```

## Development Workflow

### Running Locally
```bash
uv pip install -e .
uv run hassette -c ./config/hassette.toml -e ./config/.env
```

### Testing
```bash
uv run nox -s tests
uv run nox -s tests_with_coverage
```

### Development Flags
- `@only_app`: Decorator to run only one app (dev mode unless `allow_only_app_in_prod=True`)
- `dev_mode`: Enables development features
- `watch_files`: Enables file watching for auto-reload
- `allow_reload_in_prod`: Allows file watching in production

## Code Conventions

### Type Hints
- Strong typing is first-class: use `typing` and `typing_extensions` liberally
- Leverage existing types in `src/hassette/types.py`
- Use domain-specific models in `src/hassette/models/`

### Code Quality
- **Pyright**: Type checking enforced via `pyrightconfig.json`
- **Ruff**: Linting enforced via `ruff.toml`
- **Pre-commit**: Hooks defined in `.pre-commit-config.yaml`

### Documentation
- **Docstrings**: Google style for all public classes/methods/functions
- **Examples**: Include usage examples in docstrings
- **Format**: Documentation uses reStructuredText (`.rst`) in `docs/` directory

## Common Patterns and Best Practices

### Background Tasks
```python
# Use TaskBucket for background work
self.task_bucket.spawn(self.background_task)
self.task_bucket.run_in_thread(self.blocking_operation)
result = await self.task_bucket.run_sync(self.sync_operation)
```

### Error Handling
- REST requests retry with jitter automatically
- `EntityNotFoundError` raised on 404s
- Use try/catch around API calls as needed

### State Management
```python
# Typed state access
light_state = await self.api.get_state("light.bedroom", states.LightState)
brightness = light_state.attributes.brightness  # float | None

# Raw state access (TypedDict)
raw_states = await self.api.get_states_raw()
```

### Multi-Instance Apps
Apps can be configured for multiple instances:
```toml
[apps.sensor_monitor]
filename = "sensor_monitor.py"
class_name = "SensorMonitor"
config = [
    {sensor = "sensor.temperature", threshold = 25},
    {sensor = "sensor.humidity", threshold = 60}
]
```

## Common Pitfalls and Solutions

1. **Lifecycle Hooks**: Don't override `initialize()` or `shutdown()` - use the lifecycle hooks instead
2. **Event Loop**: Use `TaskBucket` methods for cross-thread operations
3. **File Watching**: Only enabled when `watch_files=True` and in dev mode (or `allow_reload_in_prod=True`)
4. **Import Namespace**: `app_dir` leaf name becomes import namespace - keep it stable
5. **Log Levels**: Use config settings rather than hardcoding log levels
6. **Sync vs Async**: Use appropriate base class (`App` vs `AppSync`) and API methods

## File Structure Reference

### Core Files
- `src/hassette/core/core.py`: Main Hassette runtime
- `src/hassette/core/resources/base.py`: Base Resource/Service classes
- `src/hassette/core/context.py`: Application context management

### Services
- `src/hassette/core/services/`: All background services
- Key services: `websocket_service.py`, `api_resource.py`, `bus_service.py`, `scheduler_service.py`, `app_handler.py`

### App Resources
- `src/hassette/core/resources/api/`: API functionality
- `src/hassette/core/resources/bus/`: Event bus functionality
- `src/hassette/core/resources/scheduler/`: Scheduling functionality
- `src/hassette/core/resources/app/`: App base classes

### Configuration
- `src/hassette/config/core.py`: Main configuration model
- `src/hassette/config/classes.py`: Configuration classes
- `src/hassette/config/helpers.py`: Configuration helpers
- `src/hassette/config/defaults.py`: Default configuration values

### Models and Events
- `src/hassette/events/`: Event definitions and handling
- `src/hassette/models/`: Home Assistant entity and state models
- `src/hassette/topics.py`: Event topic definitions

### Examples and Tests
- `examples/`: Complete example applications
- `tests/`: Test suite (fixtures in `tests/conftest.py`)

## Getting Started for Agents

1. **Read the Architecture**: Understand the core components and data flow
2. **Study Examples**: Look at `examples/apps/` for real-world patterns
3. **Follow Conventions**: Use strong typing, proper lifecycle hooks, and TaskBucket for background work
4. **Leverage Resources**: Use `self.api`, `self.bus`, `self.scheduler` appropriately
5. **Test Thoroughly**: Use the provided test framework and ensure type safety

This framework prioritizes developer experience, type safety, and clear patterns. When working with Hassette, focus on these principles to create maintainable and robust Home Assistant automations.

# Code Conventions
- Use strong typing with `typing` and `typing_extensions`
- Follow Google style docstrings
- Adhere to linting and formatting rules via Ruff and pre-commit
- Pyright is used for type checking, do not use `mypy` style type ignore directives
- Write tests for all new features and bug fixes
- Add examples to docstrings where applicable
- All tests should have docstrings
- Use clear and descriptive names for variables, functions, and classes
- Adhere to SOLID principles and best practices for clean code
- Use `ruff check --fix` to automatically fix linting issues
