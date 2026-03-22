# Research Brief: HA Integration Deep Dive -- Implementation Patterns

**Date**: 2026-03-21
**Status**: Ready for Decision
**Proposal**: Deep technical analysis of how to build the Home Assistant custom integration for Hassette, focusing on HA-side implementation patterns, entity platforms, push-based updates, dynamic entity management, service registration, config flows, testing, and development workflow.
**Initiated by**: Follow-up to the high-level integration research brief. The user has never built an HA integration before and needs thorough technical grounding.

---

## 1. ESPHome Pattern Analysis

ESPHome is the closest architectural reference for Hassette's integration. Both involve an HA integration connecting to an external process, discovering entities dynamically, and receiving push-based state updates. Here is how ESPHome structures this, annotated with what Hassette would adapt.

### 1.1 Connection Management (manager.py)

ESPHome uses a `ReconnectLogic` helper (from `aioesphomeapi`) that manages the full connection lifecycle:

```python
# ESPHome pattern in manager.py
reconnect_logic = ReconnectLogic(
    client=self.cli,
    on_connect=self.on_connect,
    on_disconnect=self.on_disconnect,
    zeroconf_instance=self.zeroconf_instance,
    name=entry.data.get(CONF_DEVICE_NAME, self.host),
    on_connect_error=self.on_connect_error,
)
```

**Key behaviors:**
- `on_connect()`: Validates device identity (MAC address matching), then calls `entry_data.async_on_connect()` to mark entities available. Calls `cli.device_info_and_list_entities()` to discover all entities. Loads required platforms via `_ensure_platforms_loaded()`.
- `on_disconnect()`: Marks all entity states as stale, sets `available = False`, fires disconnect callbacks.
- `on_connect_error()`: Special handling for auth failures (triggers reauth flow) vs transient errors (retries with backoff).

**What Hassette would adapt:** Hassette's integration would NOT use `aioesphomeapi` -- it would use `aiohttp` to connect to Hassette's FastAPI server. But the connection lifecycle pattern is identical: maintain a persistent WebSocket, handle disconnect/reconnect, re-sync entity state on reconnect. The integration needs its own `HassetteConnectionManager` class that implements the same callback structure (`on_connect`, `on_disconnect`, `on_connect_error`).

### 1.2 Runtime Entry Data (entry_data.py)

ESPHome's `RuntimeEntryData` is the central state container shared between the manager, coordinator, and entity platforms:

```python
class RuntimeEntryData:
    # Connection state
    available: bool = False
    device_info: DeviceInfo | None = None

    # Entity state storage -- grouped by type, then by key
    state: defaultdict[type[EntityState], dict[int, EntityState]]

    # Stale state tracking for reconnection
    stale_state: set[EntityStateKey]

    # Callback registries
    entity_info_callbacks: dict[type[EntityInfo], list[Callable]]
    state_subscriptions: dict[tuple[type, int, int], list[Callable]]
```

**Callback registration patterns:**

```python
# Platform registers to be notified when new entities of a type are discovered
unsub = entry_data.async_register_static_info_callback(SensorInfo, callback)

# Individual entities subscribe to state updates
unsub = entry_data.async_subscribe_state_update(
    state_type=SensorState,
    device_id=0,
    state_key=entity_key,
    callback=self._on_state_update,
)
```

Both return unsubscribe callables for cleanup.

**What Hassette would adapt:** Hassette's `HassetteRuntimeData` would be simpler since entities are plain dicts (not protobuf types). The key concept to preserve is: platforms register callbacks to be notified when new entities of their type appear, and individual entities subscribe to state updates for their specific entity_id.

### 1.3 Entity Discovery Flow

When ESPHome connects, the discovery flow is:

1. `manager.on_connect()` calls `cli.device_info_and_list_entities()`
2. Returns a list of `EntityInfo` objects (one per discovered entity)
3. Manager calls `entry_data.async_update_static_infos(infos)`
4. `async_update_static_infos()` determines which platforms are needed (sensor, switch, etc.)
5. Calls `_ensure_platforms_loaded()` to forward entry setup for any new platforms
6. Distributes entity info to registered callbacks per type
7. Callbacks (registered by platform files) create entity instances and call `async_add_entities()`

**Critical insight:** `async_add_entities()` CAN be called multiple times. It is not limited to the initial `async_setup_entry()` call. ESPHome calls it whenever new entities are discovered (e.g., after a device reconnects with a changed config). This is exactly what Hassette needs for dynamic entity creation.

### 1.4 Base Entity Class (entity.py)

ESPHome's `EsphomeEntity` is generic over info type and state type:

```python
class EsphomeEntity(Entity, Generic[_InfoT, _StateT]):
    _attr_should_poll = False

    def __init__(self, entry_data: RuntimeEntryData, entity_info: _InfoT, state_type: type[_StateT]):
        self._entry_data = entry_data
        self._static_info = entity_info
        self._state_type = state_type
        # Sets up device_info, unique_id from entity_info

    async def async_added_to_hass(self) -> None:
        # Registers 4 callbacks:
        # 1. Device state updates (availability)
        # 2. Entity state updates (value changes)
        # 3. Static info updates (metadata changes)
        # 4. Entity removal signals

    def _on_state_update(self) -> None:
        # Gets latest state from entry_data, calls async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._entry_data.available

    @property
    def unique_id(self) -> str:
        return build_device_unique_id(self._entry_data.device_info.mac_address, self._static_info)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, device_mac)},
            name=device_name,
            manufacturer="...",
        )
```

**What Hassette would adapt:** Hassette's `HassetteEntity` would be simpler since there is no protobuf serialization. The base entity would store the entity declaration data (from Hassette's `/api/integration/entities` response) and the current state. The key patterns to preserve:
- `should_poll = False` (push-based)
- Register callbacks in `async_added_to_hass()`
- Unregister in `async_will_remove_from_hass()`
- `available` derived from connection status
- `unique_id` derived from app_key + declared_id
- `device_info` pointing to the parent app device

### 1.5 Platform Files (sensor.py, switch.py, etc.)

Each platform file follows a consistent pattern:

```python
# sensor.py
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: HassetteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = config_entry.runtime_data
    # Register a callback that creates entities when new sensors are discovered
    entry_data.register_platform_callback(
        "sensor",
        lambda infos: async_add_entities(
            [HassetteSensor(entry_data, info) for info in infos]
        ),
    )

class HassetteSensor(HassetteEntity, SensorEntity):
    @property
    def native_value(self) -> str | int | float | None:
        return self._state.get("value")

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._entity_info.get("unit_of_measurement")

    @property
    def device_class(self) -> SensorDeviceClass | None:
        return self._entity_info.get("device_class")

    @property
    def state_class(self) -> SensorStateClass | None:
        return self._entity_info.get("state_class")
```

For controllable entities (switch, button, number), the pattern adds command methods:

```python
# ESPHome switch.py pattern
class EsphomeSwitch(EsphomeEntity[SwitchInfo, SwitchState], SwitchEntity):
    @esphome_state_property
    def is_on(self) -> bool | None:
        return self._state.state

    @convert_api_error_ha_error
    async def async_turn_on(self, **kwargs: Any) -> None:
        self._client.switch_command(self._static_info.key, True, self._static_info.device_id)

    @convert_api_error_ha_error
    async def async_turn_off(self, **kwargs: Any) -> None:
        self._client.switch_command(self._static_info.key, False, self._static_info.device_id)
```

**What Hassette would adapt:** For controllable entities, the command methods would call back to Hassette's API (e.g., `POST /api/integration/entities/{entity_id}/command`). The command payload would include the action ("turn_on", "turn_off", "set_value", "press", etc.) and any parameters.

### 1.6 The detailed_hello_world_push Pattern (Official Example)

This is a simpler reference that shows the direct callback pattern WITHOUT a DataUpdateCoordinator:

**Hub class** (external connection):
```python
class Hub:
    def __init__(self, hass: HomeAssistant, host: str):
        self._host = host
        self._hass = hass
        self.rollers = [Roller(f"{self._id}_1", f"{self._name} 1", self), ...]
        self.online = True

class Roller:
    _callbacks: set  # Set of callback functions

    def register_callback(self, callback: Callable[[], None]) -> None:
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        self._callbacks.discard(callback)

    async def publish_updates(self) -> None:
        self._current_position = self._target_position
        for callback in self._callbacks:
            callback()
```

**Entity registration:**
```python
class HelloWorldCover(CoverEntity):
    should_poll = False

    async def async_added_to_hass(self) -> None:
        self._roller.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        self._roller.remove_callback(self.async_write_ha_state)

    @property
    def available(self) -> bool:
        return self._roller.online and self._roller.hub.online
```

**Key insight:** The callback is simply `self.async_write_ha_state` -- the entity's built-in method that reads the entity's current properties and writes them to HA's state machine. When the hub calls the callback, the entity re-reads its properties (which now reflect new data from the device) and pushes the update.

---

## 2. Entity Platform Reference

For each platform type Hassette should support, here is what the entity class requires.

### 2.1 SensorEntity

**Base class:** `homeassistant.components.sensor.SensorEntity`

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `native_value` | `str \| int \| float \| date \| datetime \| Decimal \| None` | Yes | The sensor's current reading |
| `native_unit_of_measurement` | `str \| None` | No | Unit (e.g., "C", "kWh", "%") |
| `device_class` | `SensorDeviceClass \| None` | No | 80+ classes: TEMPERATURE, ENERGY, HUMIDITY, PRESSURE, POWER, etc. |
| `state_class` | `SensorStateClass \| None` | No | MEASUREMENT, TOTAL, TOTAL_INCREASING |
| `suggested_display_precision` | `int \| None` | No | Decimal places to display |
| `last_reset` | `datetime \| None` | No | For accumulating sensors (TOTAL state_class) |
| `options` | `list[str] \| None` | No | Required for ENUM device_class |

**No command methods** -- sensors are read-only.

### 2.2 BinarySensorEntity

**Base class:** `homeassistant.components.binary_sensor.BinarySensorEntity`

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `is_on` | `bool \| None` | Yes | Current on/off state |
| `device_class` | `BinarySensorDeviceClass \| None` | No | 26 classes: MOTION, DOOR, WINDOW, OCCUPANCY, CONNECTIVITY, etc. |

**No command methods** -- binary sensors are read-only.

### 2.3 SwitchEntity

**Base class:** `homeassistant.components.switch.SwitchEntity`

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `is_on` | `bool \| None` | Yes | Current on/off state |
| `device_class` | `SwitchDeviceClass \| None` | No | OUTLET, SWITCH |

| Command Method | Signature | Description |
|---------------|-----------|-------------|
| `async_turn_on` | `(**kwargs) -> None` | Turn the switch on |
| `async_turn_off` | `(**kwargs) -> None` | Turn the switch off |
| `async_toggle` | `(**kwargs) -> None` | Optional -- auto-derived from is_on if not implemented |

**Hassette implementation:** `async_turn_on()` would POST to Hassette's API with `{"action": "turn_on"}`.

### 2.4 ButtonEntity

**Base class:** `homeassistant.components.button.ButtonEntity`

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `device_class` | `ButtonDeviceClass \| None` | No | IDENTIFY, RESTART, UPDATE (deprecated) |

| Command Method | Signature | Description |
|---------------|-----------|-------------|
| `async_press` | `() -> None` | Trigger the button action |

**Note:** Buttons are stateless -- they have no `native_value` or `is_on`. They only fire an action.

### 2.5 NumberEntity

**Base class:** `homeassistant.components.number.NumberEntity`

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `native_value` | `float` | Yes | Current numeric value |
| `native_min_value` | `float` | No | Minimum (default: 0) |
| `native_max_value` | `float` | No | Maximum (default: 100) |
| `native_step` | `float \| None` | No | Increment resolution |
| `native_unit_of_measurement` | `str \| None` | No | Unit of measurement |
| `mode` | `str` | No | "auto", "box", or "slider" (UI presentation) |
| `device_class` | `NumberDeviceClass \| None` | No | TEMPERATURE, HUMIDITY, etc. (50+ classes) |

| Command Method | Signature | Description |
|---------------|-----------|-------------|
| `async_set_native_value` | `(value: float) -> None` | Set the number to a new value |

### 2.6 SelectEntity

**Base class:** `homeassistant.components.select.SelectEntity`

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `current_option` | `str \| None` | Yes | Currently selected option |
| `options` | `list[str]` | Yes | Available options |

| Command Method | Signature | Description |
|---------------|-----------|-------------|
| `async_select_option` | `(option: str) -> None` | Select a new option |

### 2.7 TextEntity

**Base class:** `homeassistant.components.text.TextEntity`

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `native_value` | `str` | Yes | Current text value |
| `native_min` | `int` | No | Min characters (default: 0) |
| `native_max` | `int` | No | Max characters (default: 100) |
| `pattern` | `str \| None` | No | Regex validation pattern |
| `mode` | `str` | No | "text" or "password" |

| Command Method | Signature | Description |
|---------------|-----------|-------------|
| `async_set_value` | `(value: str) -> None` | Set the text value |

### 2.8 Common Entity Properties (All Platforms)

These come from the base `Entity` class and apply to every platform:

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `unique_id` | `str \| None` | None | Must be unique per platform, stable across restarts |
| `name` | `str \| None` | None | Entity display name |
| `has_entity_name` | `bool` | False | **Required for new integrations.** When True, name is the data point name, not the full device name |
| `should_poll` | `bool` | True | Set to False for push-based entities |
| `available` | `bool` | True | Whether the entity is currently reachable |
| `device_info` | `DeviceInfo \| None` | None | Links entity to a device in the device registry |
| `entity_category` | `EntityCategory \| None` | None | CONFIG or DIAGNOSTIC (for non-primary entities) |
| `icon` | `str \| None` | None | Material Design Icon (e.g., "mdi:thermometer") |
| `extra_state_attributes` | `dict \| None` | None | Additional attributes stored in state machine |
| `entity_registry_enabled_default` | `bool` | True | Whether entity is enabled on first discovery |

### 2.9 The _attr_ Pattern

HA supports two ways to set entity properties:

**Pattern 1: Property methods** (read from dynamic state)
```python
@property
def native_value(self) -> float:
    return self._current_reading
```

**Pattern 2: _attr_ class/instance attributes** (simpler, for static values)
```python
class MySensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = "C"
    _attr_has_entity_name = True

    def __init__(self, info):
        self._attr_unique_id = f"hassette_{info['app_key']}_{info['id']}"
        self._attr_name = info["name"]
```

**Recommendation for Hassette:** Use `_attr_` for static metadata (device_class, unit, name, unique_id) set once at entity creation, and property methods for dynamic state (native_value, is_on, available) that changes at runtime.

### 2.10 Entity Lifecycle Methods

```python
async def async_added_to_hass(self) -> None:
    """Called when entity is added to HA and has entity_id + hass assigned.
    Register callbacks, restore state, set up subscriptions here."""

async def async_will_remove_from_hass(self) -> None:
    """Called before entity is removed. Unsubscribe, disconnect, clean up."""
```

These are the two critical lifecycle hooks for push-based entities. The pattern:
1. In `async_added_to_hass()`: subscribe to updates from the external connection
2. In `async_will_remove_from_hass()`: unsubscribe

### 2.11 DeviceInfo Structure

```python
from homeassistant.helpers.device_registry import DeviceInfo

DeviceInfo(
    identifiers={(DOMAIN, unique_device_id)},  # Required: set of (domain, id) tuples
    name="My Device",                           # Device display name
    manufacturer="Hassette",                    # Manufacturer string
    model="Hassette App",                       # Model string
    sw_version="0.23.0",                        # Software version
    via_device=(DOMAIN, hub_device_id),          # Parent device (the Hassette instance)
    configuration_url="http://host:8126",        # Link to device config page
)
```

---

## 3. Push-Based Update Patterns

There are two valid approaches for push-based integrations in HA. ESPHome uses direct callbacks (no coordinator). The coordinator approach is simpler but less flexible.

### 3.1 Approach A: Direct Entity Callbacks (ESPHome Pattern)

**How it works:**
- Each entity registers a callback directly with the connection layer
- When data arrives, the connection layer calls the entity's callback
- The callback triggers `async_write_ha_state()`

**Pros:**
- Fine-grained: each entity only updates when ITS data changes
- No unnecessary state writes for unrelated entities
- More efficient for integrations with many entities
- Natural fit when the external source pushes per-entity updates (which Hassette does)

**Cons:**
- More callback management code
- Each entity needs explicit subscribe/unsubscribe
- Harder to implement "refresh everything" scenarios

**ESPHome's implementation:**
```python
# Entity subscribes to its specific state key
class EsphomeEntity(Entity):
    async def async_added_to_hass(self):
        self._unsub_state = entry_data.async_subscribe_state_update(
            state_type=self._state_type,
            state_key=self._entity_key,
            callback=self._on_state_update,
        )

    def _on_state_update(self):
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        self._unsub_state()
```

### 3.2 Approach B: Push-Based DataUpdateCoordinator

**How it works:**
- A single coordinator holds all entity data
- When data arrives via push, call `coordinator.async_set_updated_data(data)`
- All entities subscribed to the coordinator get notified
- Entities read their specific data from the coordinator's `data` dict

**Implementation:**
```python
class HassetteCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, client):
        super().__init__(
            hass,
            logger=_LOGGER,
            name="Hassette",
            config_entry=entry,
            # No update_interval = push-only mode
            # No update_method = push-only mode
        )
        self.client = client

    async def _async_setup(self):
        """One-time setup: called during async_config_entry_first_refresh."""
        # Connect WebSocket, discover initial entities
        entities = await self.client.get_entities()
        self.async_set_updated_data(entities)
        # Start WebSocket listener
        self.client.on_entity_update = self._handle_entity_update

    def _handle_entity_update(self, entity_id, new_state):
        """Called when Hassette pushes an entity state change."""
        current_data = dict(self.data)
        current_data[entity_id] = new_state
        self.async_set_updated_data(current_data)
```

**Entity using CoordinatorEntity:**
```python
class HassetteSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entity_info):
        super().__init__(coordinator)
        self._entity_id_key = entity_info["entity_id"]

    @property
    def native_value(self):
        return self.coordinator.data.get(self._entity_id_key, {}).get("state")
```

**Pros:**
- Less code -- CoordinatorEntity handles subscribe/unsubscribe automatically
- Built-in `available` property (False when coordinator is in error state)
- Built-in `async_config_entry_first_refresh()` with retry logic
- Familiar pattern for HA reviewers if pursuing core integration later

**Cons:**
- Every state change notifies ALL entities, not just the one that changed
- The `always_update=False` flag mitigates this (skips write if data unchanged), but entities still have their `_handle_coordinator_update()` called
- Less natural for per-entity push updates
- Coordinator's `data` is a single blob -- entities need to parse their specific data from it

### 3.3 Recommendation for Hassette

**Use the direct callback pattern (Approach A)**, matching ESPHome. Rationale:

1. Hassette's WebSocket already pushes per-entity updates (`entity_state_changed` messages with a specific `entity_id`). This maps directly to per-entity callbacks.
2. Hassette apps can declare many entities. Updating all entities when one changes would be wasteful.
3. The Hassette integration needs dynamic entity addition/removal at runtime. The coordinator pattern makes this more complex because entities need to be added to the coordinator's data dict AND to HA's entity platform.
4. The connection lifecycle (connect, disconnect, reconnect) is better managed by a dedicated connection manager class than by a coordinator.

However, use `DataUpdateCoordinator` for ONE thing: the initial connection check. Call `async_config_entry_first_refresh()` during setup to get the retry-on-failure behavior (raises `ConfigEntryNotReady` automatically). After that, switch to direct callbacks for entity updates.

**Hybrid approach:**
```python
class HassetteCoordinator(DataUpdateCoordinator):
    """Used only for connection management, not for entity state distribution."""

    async def _async_update_data(self):
        """Called once during first_refresh to validate connection."""
        try:
            info = await self.client.get_info()
            return info
        except ConnectionError as err:
            raise UpdateFailed(f"Cannot connect to Hassette: {err}") from err

# Entities do NOT inherit from CoordinatorEntity.
# Instead, they register callbacks with the connection manager.
```

---

## 4. Dynamic Entity Lifecycle

### 4.1 Adding Entities After Initial Setup

`async_add_entities()` can be called multiple times. It is NOT limited to the initial `async_setup_entry()` call. The key is to retain a reference to the `async_add_entities` callback:

```python
# sensor.py
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: HassetteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data = config_entry.runtime_data

    # Store the callback for later use
    runtime_data.register_add_entities_callback("sensor", async_add_entities)

    # Add any entities that are already known
    existing = runtime_data.get_entities_for_platform("sensor")
    if existing:
        async_add_entities([HassetteSensor(runtime_data, info) for info in existing])
```

When Hassette pushes an `entity_added` WebSocket message for a sensor:
```python
# In the connection manager
def _handle_entity_added(self, entity_data):
    platform = entity_data["platform"]  # e.g., "sensor"
    add_callback = self._add_entities_callbacks.get(platform)
    if add_callback:
        entity = create_entity(platform, entity_data)
        add_callback([entity])
```

### 4.2 Removing Entities at Runtime

There are two approaches:

**Approach 1: Entity self-removal** (simpler)
```python
# Call from within the entity
await self.async_remove()
```
This removes the entity from HA's state machine and calls cleanup callbacks. However, the entity registry entry persists (can be cleaned up separately).

**Approach 2: Registry removal** (complete)
```python
entity_registry = er.async_get(hass)
entity_id = entity_registry.async_get_entity_id(DOMAIN, "sensor", unique_id)
if entity_id:
    entity_registry.async_remove(entity_id)
```
This removes the entity from the registry entirely, including any user customizations.

**Recommendation:** When Hassette sends `entity_removed`, use Approach 1 (entity self-removal). When an entire app is removed, use Approach 2 to clean up registry entries.

### 4.3 Entity Registry Restoration

HA's entity registry stores entity metadata in `.storage/core.entity_registry`. When HA restarts:

1. `async_setup_entry()` is called
2. Integration connects to Hassette, queries entities
3. For each entity, `async_add_entities()` is called
4. HA's `EntityPlatform` checks the registry: if a `unique_id` matches an existing registry entry, the entity_id, customized name, area assignment, icon override, etc. are all restored automatically
5. No special code needed -- this is handled by the framework

**Critical requirement:** `unique_id` must be stable across restarts. For Hassette, the format `hassette_{instance_id}_{app_key}_{declared_id}` provides this stability. The `instance_id` comes from the config entry's unique_id, ensuring multiple Hassette instances don't collide.

### 4.4 Platform Loading Order

Platforms can be loaded dynamically after initial setup. ESPHome does this:

```python
async def _ensure_platforms_loaded(self, needed_platforms: set[str]):
    """Load platforms that haven't been loaded yet."""
    new_platforms = needed_platforms - self._loaded_platforms
    if new_platforms:
        await hass.config_entries.async_forward_entry_setups(entry, new_platforms)
        self._loaded_platforms |= new_platforms
```

This means the integration doesn't need to declare ALL platforms upfront. If Hassette initially has only sensors, only `sensor.py` is loaded. If a switch entity appears later, `switch.py` gets loaded on demand.

**Important:** Track which platforms have been loaded in `runtime_data.loaded_platforms` so `async_unload_entry()` only unloads what was actually loaded:
```python
async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(
        entry, entry.runtime_data.loaded_platforms
    )
```

---

## 5. Service System

### 5.1 Integration-Level Services

Registered in `async_setup_entry()` (not `async_setup()`), scoped to the integration domain:

```python
async def async_setup_entry(hass: HomeAssistant, entry: HassetteConfigEntry) -> bool:
    # ... setup code ...

    async def handle_reload_app(call: ServiceCall) -> None:
        app_key = call.data["app_key"]
        client = entry.runtime_data.client
        await client.post(f"/api/integration/services/reload_app", json={"app_key": app_key})

    hass.services.async_register(
        DOMAIN,
        "reload_app",
        handle_reload_app,
        schema=vol.Schema({
            vol.Required("app_key"): cv.string,
        }),
    )
```

**Note on `async_setup` vs `async_setup_entry`:** The HA developer docs say services should be registered in `async_setup` so they're available even without config entries. However, for Hassette, services are meaningless without a connection. Registering in `async_setup_entry` and removing in `async_unload_entry` is the pragmatic approach.

### 5.2 Voluptuous Schema Examples

```python
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

# Simple string parameter
vol.Schema({vol.Required("app_key"): cv.string})

# Optional parameter with default
vol.Schema({
    vol.Required("app_key"): cv.string,
    vol.Optional("timeout", default=30): cv.positive_int,
})

# Complex schema with enum
vol.Schema({
    vol.Required("entity_id"): cv.string,
    vol.Required("action"): vol.In(["start", "stop", "restart"]),
    vol.Optional("data"): dict,
})
```

### 5.3 services.yaml Format

```yaml
reload_app:
  name: "Reload App"
  description: "Reload a specific Hassette automation app"
  fields:
    app_key:
      name: "App Key"
      description: "The unique key of the app to reload"
      required: true
      example: "my_thermostat"
      selector:
        text:

fire_event:
  name: "Fire Event"
  description: "Fire a custom event in Hassette's event bus"
  fields:
    event_type:
      name: "Event Type"
      description: "The type of event to fire"
      required: true
      selector:
        text:
    event_data:
      name: "Event Data"
      description: "Optional data to include with the event"
      required: false
      selector:
        object:
```

**Selectors** control how fields appear in HA's developer tools and automation editor. Common selectors:
- `text:` -- free text input
- `number:` with `min`, `max`, `step` -- numeric input
- `select:` with `options` -- dropdown
- `boolean:` -- toggle
- `object:` -- YAML/JSON editor
- `entity:` with `domain` -- entity picker
- `device:` with `integration` -- device picker

### 5.4 Service Response Data

Since HA 2023.7, services can return data. This is useful for Hassette's query-style services:

```python
from homeassistant.core import SupportsResponse

hass.services.async_register(
    DOMAIN,
    "get_app_status",
    handle_get_app_status,
    schema=vol.Schema({vol.Required("app_key"): cv.string}),
    supports_response=SupportsResponse.ONLY,  # Always returns data
)

async def handle_get_app_status(call: ServiceCall) -> ServiceResponse:
    client = entry.runtime_data.client
    status = await client.get(f"/api/apps/{call.data['app_key']}/status")
    return {
        "app_key": call.data["app_key"],
        "status": status["status"],
        "entity_count": status["entity_count"],
        "uptime": status["uptime"],
    }
```

`SupportsResponse` options:
- `SupportsResponse.NONE` -- no response data (default, traditional behavior)
- `SupportsResponse.OPTIONAL` -- conditionally returns data based on `call.return_response`
- `SupportsResponse.ONLY` -- always returns data, no side effects expected

### 5.5 Entity Services

For services that target specific entities (not the integration as a whole):

```python
from homeassistant.helpers import entity_platform

async def async_setup_entry(hass, config_entry, async_add_entities):
    platform = entity_platform.async_get_current_platform()

    platform.async_register_entity_service(
        "set_custom_attribute",
        {
            vol.Required("attribute"): cv.string,
            vol.Required("value"): cv.string,
        },
        "async_set_custom_attribute",  # method name on entity
    )
```

This creates a service `hassette.set_custom_attribute` that targets specific Hassette entities. The user can select entities in the HA UI and the platform calls the named method on each targeted entity.

### 5.6 Dynamic Service Registration/Removal

Services can be registered and removed at any time:

```python
# Register
hass.services.async_register(DOMAIN, service_name, handler, schema=schema)

# Remove
hass.services.async_remove(DOMAIN, service_name)
```

For Hassette's dynamic app services, the connection manager would:
1. On `service_registered` WebSocket message: call `hass.services.async_register()`
2. On `service_removed` WebSocket message: call `hass.services.async_remove()`
3. On disconnect: remove all dynamic services
4. On reconnect: re-register services from the fresh service list

---

## 6. Config & Discovery Flow

### 6.1 Config Flow Implementation

The minimal config flow for Hassette needs one step (host + port):

```python
# config_flow.py
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST, default="127.0.0.1"): str,
    vol.Required(CONF_PORT, default=8126): cv.port,
})

class HassetteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await self._test_connection(user_input[CONF_HOST], user_input[CONF_PORT])
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Use Hassette's instance ID as unique ID
                await self.async_set_unique_id(f"hassette_{info['instance_id']}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Hassette ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def _test_connection(self, host: str, port: int) -> dict:
        """Test connection to Hassette and return instance info."""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{host}:{port}/api/integration/info") as resp:
                if resp.status != 200:
                    raise CannotConnect
                return await resp.json()
```

### 6.2 Error Handling Patterns

Config flows communicate errors through a dictionary mapping field names to error keys:

```python
errors = {}
errors["base"] = "cannot_connect"    # Shows error on the entire form
errors["host"] = "invalid_host"      # Shows error on the host field specifically
```

Standard error keys (defined in `strings.json`):
- `cannot_connect` -- connection failed
- `invalid_auth` -- authentication failed (if/when Hassette adds auth)
- `unknown` -- unexpected error
- `already_configured` -- this instance is already set up

### 6.3 Unique ID Management

The unique_id MUST be:
- **Stable**: doesn't change across restarts, reboots, IP changes
- **Unique**: no two config entries should have the same unique_id
- **String**: must be a string type

For Hassette: Use the instance ID that Hassette's `/api/integration/info` endpoint returns. This should be a UUID or similar persistent identifier that Hassette generates on first run and stores in its config.

Do NOT use host:port as unique_id -- IP addresses and ports can change.

### 6.4 Reconfigure Flow

Allows users to change host/port after setup without deleting and re-adding the integration:

```python
async def async_step_reconfigure(
    self, user_input: dict[str, Any] | None = None
) -> config_entries.ConfigFlowResult:
    if user_input is not None:
        # Validate new connection
        try:
            info = await self._test_connection(user_input[CONF_HOST], user_input[CONF_PORT])
        except CannotConnect:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=STEP_USER_DATA_SCHEMA,
                errors={"base": "cannot_connect"},
            )
        # Verify it's the same Hassette instance
        await self.async_set_unique_id(f"hassette_{info['instance_id']}")
        self._abort_if_unique_id_mismatch()
        return self.async_update_reload_and_abort(
            self._get_reconfigure_entry(),
            data_updates=user_input,
        )

    return self.async_show_form(
        step_id="reconfigure",
        data_schema=self.add_suggested_values_to_schema(
            STEP_USER_DATA_SCHEMA,
            self._get_reconfigure_entry().data,
        ),
    )
```

### 6.5 Options Flow

For runtime configuration changes (e.g., which apps to expose, polling fallback interval):

```python
class HassetteOptionsFlow(config_entries.OptionsFlowWithReload):
    """Handle Hassette options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({
                    vol.Optional("entity_prefix", default=""): str,
                    vol.Optional("poll_interval", default=0): cv.positive_int,
                }),
                self.config_entry.options,
            ),
        )

# In the ConfigFlow class:
@staticmethod
@callback
def async_get_options_flow(config_entry: ConfigEntry) -> HassetteOptionsFlow:
    return HassetteOptionsFlow()
```

`OptionsFlowWithReload` automatically reloads the integration when options change, avoiding manual update listeners.

### 6.6 Auto-Discovery via Zeroconf/mDNS

Hassette COULD advertise itself via mDNS so HA auto-discovers it. This would require:

**Hassette side:** Advertise a mDNS service on startup:
```python
# In Hassette's startup, using python-zeroconf
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceInfo

info = AsyncServiceInfo(
    "_hassette._tcp.local.",
    "Hassette._hassette._tcp.local.",
    addresses=[socket.inet_aton("192.168.1.100")],
    port=8126,
    properties={"version": "0.23.0", "instance_id": "abc123"},
)
await async_zeroconf.async_register_service(info)
```

**Integration manifest.json:**
```json
{
    "zeroconf": ["_hassette._tcp.local."]
}
```

**Integration config_flow.py:**
```python
async def async_step_zeroconf(
    self, discovery_info: zeroconf.ZeroconfServiceInfo
) -> config_entries.ConfigFlowResult:
    """Handle zeroconf discovery."""
    host = discovery_info.host
    port = discovery_info.port
    instance_id = discovery_info.properties.get("instance_id")

    await self.async_set_unique_id(f"hassette_{instance_id}")
    self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})

    self.context["title_placeholders"] = {"name": f"Hassette ({host})"}

    # Store for use in confirmation step
    self._discovered_host = host
    self._discovered_port = port

    return await self.async_step_confirm()

async def async_step_confirm(
    self, user_input: dict[str, Any] | None = None
) -> config_entries.ConfigFlowResult:
    """Confirm zeroconf discovery."""
    if user_input is not None:
        return self.async_create_entry(
            title=f"Hassette ({self._discovered_host})",
            data={CONF_HOST: self._discovered_host, CONF_PORT: self._discovered_port},
        )
    return self.async_show_form(step_id="confirm")
```

**Important:** Discovery flows must NEVER auto-complete. They must always show a confirmation step so the user explicitly approves adding the integration.

**Assessment:** mDNS discovery is a nice-to-have for v1 but not essential. The user will know Hassette is running on the same host. Prioritize the manual config flow and add zeroconf later.

### 6.7 strings.json Structure

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Connect to Hassette",
        "description": "Enter the host and port of your Hassette instance.",
        "data": {
          "host": "Host",
          "port": "Port"
        }
      },
      "confirm": {
        "title": "Discovered Hassette",
        "description": "Hassette was found at {host}:{port}. Add it?"
      },
      "reconfigure": {
        "title": "Reconfigure Hassette",
        "description": "Update the connection settings for your Hassette instance.",
        "data": {
          "host": "Host",
          "port": "Port"
        }
      }
    },
    "error": {
      "cannot_connect": "Failed to connect to Hassette. Is it running?",
      "unknown": "Unexpected error"
    },
    "abort": {
      "already_configured": "This Hassette instance is already configured.",
      "reauth_successful": "Re-authentication was successful."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "Hassette Options",
        "data": {
          "entity_prefix": "Entity name prefix",
          "poll_interval": "Fallback poll interval (seconds, 0 to disable)"
        }
      }
    }
  }
}
```

Copy this to `translations/en.json` with the same content.

---

## 7. Testing Strategy

### 7.1 Test Framework: pytest-homeassistant-custom-component

This package extracts HA's test infrastructure for use with custom integrations:

```
pip install pytest-homeassistant-custom-component
```

It provides:
- The `hass` fixture (a test instance of HomeAssistant)
- `MockConfigEntry` for creating test config entries
- `enable_custom_integrations` fixture (required since HA 2021.6)
- `aioclient_mock` for mocking HTTP requests
- Snapshot testing support via syrupy

### 7.2 Test Directory Structure

```
tests/
    __init__.py
    conftest.py              # Shared fixtures
    fixtures/                # JSON/YAML test data
        entities.json
    test_config_flow.py      # Config flow tests
    test_init.py             # Setup/teardown tests
    test_sensor.py           # Sensor entity tests
    test_switch.py           # Switch entity tests
    test_connection.py       # Connection manager tests
```

### 7.3 conftest.py Setup

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_HOST, CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hassette.const import DOMAIN

@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "127.0.0.1", CONF_PORT: 8126},
        unique_id="hassette_test_instance",
        title="Hassette (127.0.0.1)",
    )

@pytest.fixture
def mock_hassette_client():
    """Create a mock Hassette API client."""
    client = AsyncMock()
    client.get_info.return_value = {
        "instance_id": "test_instance",
        "version": "0.23.0",
        "app_count": 2,
    }
    client.get_entities.return_value = [
        {
            "entity_id": "sensor.test_temp",
            "platform": "sensor",
            "unique_id": "test_app_temp",
            "name": "Test Temperature",
            "state": "22.5",
            "device_class": "temperature",
            "unit_of_measurement": "C",
            "app_key": "test_app",
        },
    ]
    return client

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    yield
```

### 7.4 Testing Config Flows

```python
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

async def test_user_flow_success(hass, mock_hassette_client):
    """Test successful user config flow."""
    with patch(
        "custom_components.hassette.config_flow.HassetteApiClient",
        return_value=mock_hassette_client,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.168.1.100", CONF_PORT: 8126},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Hassette (192.168.1.100)"
        assert result["data"] == {CONF_HOST: "192.168.1.100", CONF_PORT: 8126}

async def test_user_flow_cannot_connect(hass, mock_hassette_client):
    """Test config flow when connection fails."""
    mock_hassette_client.get_info.side_effect = ConnectionError
    with patch(
        "custom_components.hassette.config_flow.HassetteApiClient",
        return_value=mock_hassette_client,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "192.168.1.100", CONF_PORT: 8126},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}

async def test_user_flow_already_configured(hass, mock_config_entry, mock_hassette_client):
    """Test config flow aborts if already configured."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.hassette.config_flow.HassetteApiClient",
        return_value=mock_hassette_client,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "127.0.0.1", CONF_PORT: 8126},
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
```

### 7.5 Testing Entity Platforms

```python
from homeassistant.helpers import entity_registry as er

async def test_sensor_entity(hass, mock_config_entry, mock_hassette_client):
    """Test sensor entity creation and state."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.hassette.HassetteApiClient",
        return_value=mock_hassette_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Verify entity was created
    state = hass.states.get("sensor.hassette_test_app_temp")
    assert state is not None
    assert state.state == "22.5"
    assert state.attributes["unit_of_measurement"] == "C"
    assert state.attributes["device_class"] == "temperature"

    # Verify entity registry
    ent_reg = er.async_get(hass)
    entity = ent_reg.async_get("sensor.hassette_test_app_temp")
    assert entity is not None
    assert entity.unique_id == "hassette_test_instance_test_app_temp"
```

### 7.6 Testing Dynamic Entity Updates

```python
async def test_entity_state_update_via_push(hass, mock_config_entry, mock_hassette_client):
    """Test that entity state updates when push callback fires."""
    # ... setup ...

    # Simulate a push update from Hassette
    runtime_data = mock_config_entry.runtime_data
    runtime_data.update_entity_state("sensor.test_temp", {"state": "25.0"})
    await hass.async_block_till_done()

    state = hass.states.get("sensor.hassette_test_app_temp")
    assert state.state == "25.0"
```

### 7.7 Mocking the External Connection

The key principle: mock at the boundary (the Hassette API client), not the internals.

```python
@pytest.fixture
def mock_websocket():
    """Mock the WebSocket connection to Hassette."""
    ws = AsyncMock()
    ws.receive_json = AsyncMock(return_value={
        "type": "entity_state_changed",
        "data": {"entity_id": "sensor.test_temp", "state": "23.0"},
    })
    ws.closed = False
    return ws

@pytest.fixture
def mock_hassette_client(mock_websocket):
    client = AsyncMock()
    client.connect_websocket.return_value = mock_websocket
    client.get_info.return_value = {"instance_id": "test", "version": "0.23.0"}
    client.get_entities.return_value = [...]
    return client
```

---

## 8. Dev Workflow

### 8.1 Development Environment Options

**Option A: Devcontainer (recommended)**
- Use the `ludeeus/integration_blueprint` as a starting template
- Clone it, replace the example code with Hassette's integration
- The devcontainer includes a full HA instance that auto-restarts on code changes
- VS Code debugging works out of the box (F5 to launch HA with breakpoints)

**Option B: Manual setup**
- Install HA core in a venv: `pip install homeassistant`
- Create `config/custom_components/hassette/` directory
- Symlink or copy integration code into it
- Run HA: `hass -c config/`
- Edit, restart HA, test

**Option C: Docker with volume mount**
- Run HA in Docker
- Mount the integration directory: `-v ./custom_components/hassette:/config/custom_components/hassette`
- Restart the container to pick up changes

**Recommendation for Hassette:** Option A if working in VS Code, Option B for quick iteration. Option C is closest to production but slowest iteration.

### 8.2 Loading a Custom Component

1. Place integration code in `config/custom_components/hassette/`
2. Ensure `manifest.json` is present and valid
3. Restart HA
4. Go to Settings > Devices & Services > Add Integration > search "Hassette"
5. Complete the config flow

For development, add to `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.hassette: debug
```

### 8.3 Debugging Patterns

**Logging:**
```python
import logging
_LOGGER = logging.getLogger(__name__)

_LOGGER.debug("Entity state update: %s = %s", entity_id, new_state)
_LOGGER.warning("Connection lost to Hassette at %s:%s", host, port)
_LOGGER.error("Failed to parse entity data: %s", data, exc_info=True)
```

Use `_LOGGER.debug()` liberally during development -- HA's logger UI lets you adjust levels at runtime.

**HA Developer Tools:**
- States tab: see all entity states in real-time
- Services tab: test service calls interactively
- Events tab: subscribe to events to see what's firing
- Template tab: test Jinja templates against entity states

**Breakpoint debugging:**
- In devcontainer: set breakpoints in VS Code, F5 to launch
- Manual: `import debugpy; debugpy.listen(("0.0.0.0", 5678))` in `__init__.py`, then attach VS Code

### 8.4 Common Pitfalls for First-Time Developers

1. **Blocking the event loop.** All I/O must be async. Never use `requests` -- use `aiohttp`. Never use `time.sleep()` -- use `asyncio.sleep()`. HA will log warnings for event loop blocking >0.1s.

2. **Forgetting `has_entity_name = True`.** New integrations are required to use the entity naming pattern where `name` is just the data point name, not the full device+entity name. Without this, entity names are duplicated (e.g., "Hassette My App My App Temperature").

3. **Mutable `unique_id`.** If the unique_id changes between restarts, HA creates a NEW entity and the old one becomes orphaned. Use stable identifiers, never IP addresses or ports.

4. **Not handling `ConfigEntryNotReady`.** If Hassette is unreachable during HA startup, raise `ConfigEntryNotReady` from `async_setup_entry()`. HA will automatically retry with exponential backoff. Without this, the integration simply fails and the user must manually reload.

5. **Writing state from wrong thread.** All entity state writes must happen on HA's event loop. Use `@callback` decorator for synchronous callbacks. Since Hassette's integration uses async WebSocket, this shouldn't be an issue, but be aware of it.

6. **Forgetting `should_poll = False`.** HA defaults to polling entities every 30 seconds. Push-based entities MUST set `should_poll = False` or `_attr_should_poll = False`, otherwise HA will call `async_update()` repeatedly.

7. **Not tracking loaded platforms.** If you load platforms dynamically, you must track which ones were loaded so `async_unload_entry()` only unloads what was loaded. Trying to unload a platform that was never loaded causes errors.

8. **services.yaml out of sync.** If `services.yaml` doesn't match registered services, the UI shows broken/missing service descriptions. Keep them in sync.

9. **Translations directory name mismatch.** The directory name `custom_components/hassette/` must exactly match the `domain` in `manifest.json`. If they differ, translations are silently ignored.

10. **HA version deprecations.** HA regularly deprecates patterns. Check the [HA developer blog](https://developers.home-assistant.io/blog/) before major HA releases. Recent breaking changes include: options flow `config_entry` parameter (deprecated 2025.1), color mode properties, and requirement installation changes.

---

## 9. Code Scaffolding Reference

### 9.1 Complete File Listing

```
custom_components/hassette/
    __init__.py              # Entry setup/teardown, service registration
    manifest.json            # Integration metadata
    const.py                 # Domain name, platform list, constants
    config_flow.py           # Config flow, options flow, reconfigure flow
    connection.py            # WebSocket/REST connection to Hassette
    entity.py                # Base entity class (HassetteEntity)
    sensor.py                # SensorEntity platform
    binary_sensor.py         # BinarySensorEntity platform
    switch.py                # SwitchEntity platform
    button.py                # ButtonEntity platform
    number.py                # NumberEntity platform (phase 2)
    select.py                # SelectEntity platform (phase 2)
    text.py                  # TextEntity platform (phase 2)
    services.yaml            # Service descriptions for HA UI
    strings.json             # English translations (source)
    translations/
        en.json              # English translations (copy of strings.json)
    icons.json               # Service and entity icons
    brand/
        icon.png             # 256x256 integration icon
        icon@2x.png          # 512x512 integration icon
        logo.png             # 256x256 integration logo
        logo@2x.png          # 512x512 integration logo
```

### 9.2 File-by-File Breakdown

#### `const.py` -- Constants and shared values

```python
"""Constants for the Hassette integration."""

from homeassistant.const import Platform

DOMAIN = "hassette"

# Platforms loaded on initial setup (minimal set)
# Additional platforms loaded dynamically when entities of that type appear
INITIAL_PLATFORMS: list[Platform] = []

# All supported platforms
SUPPORTED_PLATFORMS: set[Platform] = {
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.TEXT,
}

DEFAULT_PORT = 8126
```

**Why no initial platforms:** Hassette loads platforms dynamically based on what entities exist. If Hassette has no switches, the switch platform is never loaded. This avoids unnecessary platform setup.

#### `manifest.json` -- Integration metadata

```json
{
    "domain": "hassette",
    "name": "Hassette",
    "codeowners": ["@nodejsmith"],
    "config_flow": true,
    "dependencies": [],
    "documentation": "https://github.com/nodejsmith/hassette",
    "iot_class": "local_push",
    "requirements": ["aiohttp>=3.9"],
    "version": "0.1.0"
}
```

Key fields:
- `iot_class: "local_push"` -- tells HA this is a local, push-based integration
- `config_flow: true` -- enables the UI-based setup flow
- `requirements` -- Python packages installed automatically by HA. `aiohttp` is already available in HA, but declaring it pins the minimum version.
- `version` -- HACS requires this; must follow semver

#### `__init__.py` -- Entry point

Responsible for:
1. Creating the API client and connection manager
2. Performing initial connection validation
3. Storing runtime data in the config entry
4. Registering integration-level services
5. Teardown on unload

```python
"""The Hassette integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .connection import HassetteConnection

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

type HassetteConfigEntry = ConfigEntry[HassetteRuntimeData]

@dataclass
class HassetteRuntimeData:
    connection: HassetteConnection
    loaded_platforms: set[Platform] = field(default_factory=set)
    add_entities_callbacks: dict[str, AddEntitiesCallback] = field(default_factory=dict)

async def async_setup_entry(hass: HomeAssistant, entry: HassetteConfigEntry) -> bool:
    connection = HassetteConnection(
        hass, entry.data[CONF_HOST], entry.data[CONF_PORT]
    )

    try:
        info = await connection.async_connect()
    except ConnectionError as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to Hassette at {entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}"
        ) from err

    entry.runtime_data = HassetteRuntimeData(connection=connection)

    # Start WebSocket listener for push updates
    await connection.async_start_listening(hass, entry)

    # Discover initial entities and load required platforms
    entities = await connection.async_get_entities()
    needed_platforms = {e["platform"] for e in entities}
    if needed_platforms:
        await hass.config_entries.async_forward_entry_setups(
            entry, list(needed_platforms)
        )
        entry.runtime_data.loaded_platforms = needed_platforms

    # Register services
    _async_register_services(hass, entry)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: HassetteConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, list(entry.runtime_data.loaded_platforms)
    )
    if unload_ok:
        await entry.runtime_data.connection.async_disconnect()
    return unload_ok
```

#### `connection.py` -- Hassette API client and WebSocket manager

Responsible for:
1. REST calls to Hassette's `/api/integration/` endpoints
2. WebSocket connection for push updates
3. Reconnection with backoff
4. Entity state callback dispatch
5. Availability tracking

This is the largest and most complex file. It mirrors ESPHome's `manager.py` + `entry_data.py` combined.

Key methods:
- `async_connect()` -- initial REST connection, returns instance info
- `async_start_listening()` -- opens WebSocket, starts message loop
- `async_get_entities()` -- REST call to get all declared entities
- `async_send_command()` -- REST call for entity commands (turn_on, set_value, etc.)
- `register_entity_callback(entity_id, callback)` -- per-entity state update registration
- `register_platform_callback(platform, callback)` -- notified when new entities of a type appear
- `_handle_ws_message()` -- dispatches WebSocket messages by type
- `_handle_disconnect()` -- marks unavailable, starts reconnect
- `_handle_reconnect()` -- re-syncs entities, restores callbacks

#### `entity.py` -- Base entity class

All Hassette entities inherit from this. Provides:
- `unique_id` from app_key + declared_id
- `device_info` pointing to the parent app device
- `available` from connection status
- Callback registration/unregistration lifecycle
- `should_poll = False`

```python
"""Base entity for the Hassette integration."""
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

class HassetteEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, connection, entity_info: dict) -> None:
        self._connection = connection
        self._entity_info = entity_info
        self._state_data: dict = {}

        self._attr_unique_id = (
            f"hassette_{connection.instance_id}_{entity_info['app_key']}"
            f"_{entity_info['unique_id']}"
        )
        self._attr_name = entity_info.get("name")

    async def async_added_to_hass(self) -> None:
        self._unsub = self._connection.register_entity_callback(
            self._entity_info["entity_id"],
            self._handle_state_update,
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()

    def _handle_state_update(self, new_state: dict) -> None:
        self._state_data = new_state
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._connection.available

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"hassette_{self._connection.instance_id}_{self._entity_info['app_key']}")},
            name=self._entity_info.get("app_name", self._entity_info["app_key"]),
            manufacturer="Hassette",
            model="Hassette App",
            sw_version=self._connection.hassette_version,
            via_device=(DOMAIN, f"hassette_{self._connection.instance_id}"),
        )
```

#### Platform files (`sensor.py`, `switch.py`, etc.)

Each follows the same structure:

```python
"""Sensor platform for Hassette."""
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HassetteConfigEntry
from .entity import HassetteEntity

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: HassetteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime_data = config_entry.runtime_data
    connection = runtime_data.connection

    # Store callback for dynamic entity addition
    runtime_data.add_entities_callbacks["sensor"] = async_add_entities

    # Add any already-discovered sensor entities
    existing = connection.get_entities_for_platform("sensor")
    if existing:
        async_add_entities([HassetteSensor(connection, info) for info in existing])

    # Register to be notified of new sensor entities
    connection.register_platform_callback("sensor", lambda infos: async_add_entities(
        [HassetteSensor(connection, info) for info in infos]
    ))

class HassetteSensor(HassetteEntity, SensorEntity):
    @property
    def native_value(self):
        return self._state_data.get("state")

    @property
    def native_unit_of_measurement(self):
        return self._entity_info.get("unit_of_measurement")

    @property
    def device_class(self):
        dc = self._entity_info.get("device_class")
        if dc:
            try:
                return SensorDeviceClass(dc)
            except ValueError:
                return None
        return None

    @property
    def state_class(self):
        sc = self._entity_info.get("state_class")
        if sc:
            try:
                return SensorStateClass(sc)
            except ValueError:
                return None
        return None
```

For controllable entities, add command methods:

```python
# switch.py
class HassetteSwitch(HassetteEntity, SwitchEntity):
    @property
    def is_on(self):
        return self._state_data.get("state") in (True, "on", "True", 1)

    async def async_turn_on(self, **kwargs) -> None:
        await self._connection.async_send_command(
            self._entity_info["entity_id"], "turn_on"
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self._connection.async_send_command(
            self._entity_info["entity_id"], "turn_off"
        )
```

#### `config_flow.py`

See Section 6 for the complete implementation.

#### `services.yaml`

See Section 5.3 for the format.

#### `icons.json`

```json
{
    "services": {
        "reload_app": {"service": "mdi:reload"},
        "start_app": {"service": "mdi:play"},
        "stop_app": {"service": "mdi:stop"},
        "fire_event": {"service": "mdi:broadcast"},
        "get_app_status": {"service": "mdi:information-outline"}
    }
}
```

---

## Concerns

### Technical Risks

1. **WebSocket reconnection reliability.** The connection manager is the most complex and error-prone part. A bug in reconnection logic can leave entities permanently unavailable. Must be thoroughly tested with chaos scenarios (Hassette restart, network partition, HA restart while Hassette is down).

2. **Entity state type coercion.** Hassette entities will send state as JSON strings. The integration must correctly coerce these to the right Python types (float for sensors, bool for switches). Type mismatches cause entity state to show as "unavailable" or "unknown" with cryptic log errors.

3. **Platform loading race conditions.** If Hassette pushes an `entity_added` for a new platform type while platforms are still loading, the `async_add_entities` callback might not be registered yet. Need a queue/buffer for entities that arrive before their platform callback is ready.

### Complexity Risks

1. **Two codebases to maintain.** The integration is a separate codebase from Hassette itself. API changes in Hassette require coordinated updates to the integration. Consider versioning the integration API.

2. **Dynamic entity lifecycle.** Adding/removing entities at runtime is more complex than static entity setup. Each platform file needs to handle both initial discovery and subsequent additions.

### Maintenance Risks

1. **HA version compatibility.** HA deprecates patterns regularly. The integration needs to track HA releases and update accordingly. Using `pytest-homeassistant-custom-component` helps catch issues early since it tracks HA releases daily.

2. **HACS distribution.** If distributing via HACS, the integration needs its own GitHub repo with proper releases, changelogs, and HACS metadata. This is additional maintenance overhead.

---

## Open Questions

- [ ] **Hassette instance_id:** Does Hassette currently generate a stable instance identifier? The config flow needs this for unique_id. If not, Hassette needs to generate and persist a UUID on first run.
- [ ] **Entity command protocol:** What should the REST endpoint look like for sending commands back to Hassette entities? Proposed: `POST /api/integration/entities/{entity_id}/command` with body `{"action": "turn_on", "params": {...}}`.
- [ ] **WebSocket authentication:** Should the WebSocket connection from the integration to Hassette require any authentication? Currently Hassette's API is unauthenticated.
- [ ] **Entity ID generation:** Should the Hassette-side entity_id (e.g., `sensor.living_room_temp`) be the same as the HA entity_id, or should they be independent with mapping?
- [ ] **Phase 1 platform scope:** The recommendation is sensor + binary_sensor + switch + button for v1. Are number, select, and text needed for any existing Hassette app use cases?
- [ ] **Separate repo or monorepo?** HACS strongly prefers separate repos for custom integrations. But monorepo makes development easier. Decision needed before implementation starts.

---

## Sources

- [ESPHome Integration Source (entity.py, __init__.py, manager.py, entry_data.py, sensor.py, switch.py)](https://github.com/home-assistant/core/tree/dev/homeassistant/components/esphome)
- [HA Example: detailed_hello_world_push](https://github.com/home-assistant/example-custom-config/tree/master/custom_components/detailed_hello_world_push)
- [HA Developer Docs: Entity Base Class](https://developers.home-assistant.io/docs/core/entity/)
- [HA Developer Docs: Fetching Data (DataUpdateCoordinator)](https://developers.home-assistant.io/docs/integration_fetching_data/)
- [HA Developer Docs: Config Flow](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/)
- [HA Developer Docs: Options Flow](https://developers.home-assistant.io/docs/config_entries_options_flow_handler/)
- [HA Developer Docs: Service Actions](https://developers.home-assistant.io/docs/dev_101_services/)
- [HA Developer Docs: Integration File Structure](https://developers.home-assistant.io/docs/creating_integration_file_structure/)
- [HA Developer Docs: Networking and Discovery](https://developers.home-assistant.io/docs/network_discovery/)
- [HA Developer Docs: Testing](https://developers.home-assistant.io/docs/development_testing/)
- [HA Developer Docs: Backend Localization](https://developers.home-assistant.io/docs/internationalization/core/)
- [HA Developer Docs: Entity Registry](https://developers.home-assistant.io/docs/entity_registry_disabled_by/)
- [HA Developer Docs: Sensor Entity](https://developers.home-assistant.io/docs/core/entity/sensor/)
- [HA Developer Docs: Binary Sensor Entity](https://developers.home-assistant.io/docs/core/entity/binary-sensor/)
- [HA Developer Docs: Switch Entity](https://developers.home-assistant.io/docs/core/entity/switch/)
- [HA Developer Docs: Button Entity](https://developers.home-assistant.io/docs/core/entity/button/)
- [HA Developer Docs: Number Entity](https://developers.home-assistant.io/docs/core/entity/number/)
- [HA Developer Docs: Select Entity](https://developers.home-assistant.io/docs/core/entity/select/)
- [HA Developer Docs: Text Entity](https://developers.home-assistant.io/docs/core/entity/text/)
- [DeepWiki: Entity and Registry Management](https://deepwiki.com/home-assistant/core/2.2-entity-and-registry-management)
- [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
- [HA Community: Push DataUpdateCoordinator](https://community.home-assistant.io/t/push-dataupdatecoordinator/552002)
- [HA Community: Adding entities at runtime](https://community.home-assistant.io/t/adding-entities-at-runtime/200855)
- [HA Community: Integration with both polling and push](https://community.home-assistant.io/t/integration-with-both-polling-and-push/344290)
- [Developing Custom Integrations for HA - Getting Started](https://helgeklein.com/blog/developing-custom-integrations-for-home-assistant-getting-started/)
- [Building a HA Custom Component Series (Aaron Godfrey)](https://aarongodfrey.dev/home%20automation/building_a_home_assistant_custom_component_part_1/)
- [Writing a Home Assistant Core Integration (Jon Seager)](https://jnsgr.uk/2024/10/writing-a-home-assistant-integration/)
- [HA Integration Blueprint (HACS)](https://github.com/jpawlowski/hacs.integration_blueprint)
- [HA Developer Blog (Breaking Changes)](https://developers.home-assistant.io/blog/)
