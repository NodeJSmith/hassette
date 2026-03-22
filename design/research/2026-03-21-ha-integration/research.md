# Research Brief: Home Assistant Custom Integration for Hassette

**Date**: 2026-03-21
**Status**: Ready for Decision
**Proposal**: Build a Home Assistant custom integration that lets Hassette apps create native HA entities and expose operations as HA services, while Hassette continues running as a separate process.
**Initiated by**: User request to investigate technical requirements for a custom integration.

## 1. Executive Summary

Building a custom HA integration for Hassette is feasible and well-supported by HA's architecture. The core design challenge is the communication bridge: Hassette already connects to HA via WebSocket as a client, but the integration (running inside HA) needs to talk back to Hassette to discover what entities/services to create. The most natural pattern is for the integration to connect to Hassette's existing FastAPI web API (`http://<host>:8126`) plus a WebSocket channel for push updates. This mirrors how ESPHome's integration works -- HA's integration maintains a persistent connection to the external process and entities update via push callbacks. The integration itself is a moderate effort -- the HA-side code is straightforward (config flow, coordinator, entity platforms), but Hassette needs a new "entity declaration" API that apps can use to register entities and a corresponding wire protocol for the integration to consume.

## 2. HA Integration Architecture

### Required Files

A custom integration lives in `custom_components/hassette/` with this structure:

```
custom_components/hassette/
  __init__.py          # async_setup_entry / async_unload_entry
  manifest.json        # metadata, domain, version, dependencies
  config_flow.py       # UI flow for adding the integration
  coordinator.py       # DataUpdateCoordinator subclass (push-based)
  const.py             # DOMAIN, PLATFORMS, etc.
  entity.py            # Base entity class for all Hassette entities
  sensor.py            # Platform: SensorEntity subclasses
  binary_sensor.py     # Platform: BinarySensorEntity subclasses
  switch.py            # Platform: SwitchEntity subclasses
  button.py            # Platform: ButtonEntity subclasses
  (other platforms)     # One file per supported HA platform
  services.yaml        # Service descriptions for UI
  strings.json         # Localization strings
  translations/
    en.json            # English translations
```

### manifest.json

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
- `iot_class: "local_push"` -- Hassette pushes state changes over WebSocket rather than HA polling
- `config_flow: true` -- required for UI-based setup
- `requirements` -- Python packages the integration needs (installed by HA automatically)

### __init__.py Pattern

```python
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.BUTTON]

type HassetteConfigEntry = ConfigEntry[HassetteRuntimeData]

@dataclass
class HassetteRuntimeData:
    coordinator: HassetteCoordinator
    client: HassetteApiClient

async def async_setup_entry(hass: HomeAssistant, entry: HassetteConfigEntry) -> bool:
    client = HassetteApiClient(entry.data["host"], entry.data["port"])
    coordinator = HassetteCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = HassetteRuntimeData(coordinator=coordinator, client=client)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: HassetteConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

## 3. Communication Design

This is the core architectural decision. Three viable options, in order of recommendation:

### Option A: Integration connects to Hassette's API (Recommended)

**How it works**: The HA integration acts as a client to Hassette's existing FastAPI server (`http://<host>:8126`). It connects via both REST (for initial entity discovery) and WebSocket (`ws://<host>:8126/api/ws`) for real-time push updates.

**Data flow**:
1. User adds integration, provides Hassette host:port
2. Integration calls `GET /api/integration/entities` to discover all declared entities
3. Integration opens WebSocket to `ws://<host>:8126/api/ws` and subscribes to entity state changes
4. When a Hassette app updates an entity, Hassette pushes the change over WebSocket
5. Integration's coordinator receives the push and calls `async_set_updated_data()`
6. HA entities call `self.async_write_ha_state()` to update

**Why this is best**:
- Hassette already has a FastAPI server with WebSocket support (`src/hassette/web/routes/ws.py`)
- The existing WebSocket protocol already broadcasts events to connected clients
- Hassette's `RuntimeQueryService` already tracks app status, entity counts, etc.
- Matches ESPHome's pattern: HA integration connects to external process
- No circular dependency: Hassette does NOT need to know the integration exists

**New Hassette endpoints needed**:
- `GET /api/integration/entities` -- returns list of declared entities with platform type, unique_id, name, state, attributes, device info
- `POST /api/integration/services/{service_name}` -- receives service calls from HA
- WebSocket message types: `entity_state_changed`, `entity_added`, `entity_removed`

### Option B: Hassette pushes via HA's WebSocket API

**How it works**: Hassette (which already connects to HA's WebSocket) directly creates entities by calling `api.set_state()` -- which it already can do. No custom integration needed for basic entity creation, but entities won't have proper device registry entries, won't support commands, and won't have config flow.

**Why it's insufficient**: `api.set_state()` creates entities but they are "orphan" entities -- no device, no integration attribution, no service support, no entity registry entry. They disappear on HA restart. This is what Hassette can already do today via `self.api.set_state("sensor.my_sensor", "42", {"unit": "C"})`.

### Option C: Shared state via file/database

Not recommended. Adds complexity without benefits over Option A.

### Communication Protocol Detail (Option A)

The integration would use a simple REST + WebSocket protocol:

**REST endpoints** (added to Hassette's FastAPI app):

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/integration/entities` | GET | List all declared entities |
| `/api/integration/entities/{entity_id}` | GET | Get single entity state |
| `/api/integration/services` | GET | List registered services |
| `/api/integration/services/{name}` | POST | Invoke a Hassette service |
| `/api/integration/info` | GET | Hassette version, app count, status |

**WebSocket messages** (pushed from Hassette to integration):

```json
{"type": "entity_state_changed", "data": {"entity_id": "sensor.my_temp", "state": "22.5", "attributes": {...}}}
{"type": "entity_added", "data": {"entity_id": "sensor.my_temp", "platform": "sensor", ...}}
{"type": "entity_removed", "data": {"entity_id": "sensor.my_temp"}}
{"type": "service_registered", "data": {"name": "reload_app", "schema": {...}}}
{"type": "hassette_status", "data": {"connected": true, "app_count": 5}}
```

## 4. Entity System

### How HA Entity Platforms Work

Each HA platform (sensor, switch, etc.) has its own entity base class that provides standard properties. The integration creates entities by:

1. Defining entity classes that inherit from both `CoordinatorEntity` and the platform class (e.g., `SensorEntity`)
2. Implementing `async_setup_entry(hass, config_entry, async_add_entities)` in each platform file
3. Using `async_add_entities()` to register entity instances with HA

### How Hassette Apps Would Declare Entities

Apps need a new API for declaring entities. This would live on the `App` base class:

```python
class MyApp(App[MyConfig]):
    async def on_initialize(self):
        # Declare a sensor entity
        self.declare_entity(
            platform="sensor",
            unique_id="living_room_temp",
            name="Living Room Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            unit_of_measurement="C",
            state_class=SensorStateClass.MEASUREMENT,
        )

    async def on_ready(self):
        # Update the entity state
        self.update_entity("living_room_temp", state=22.5)
```

### Entity Properties Map

| HA Property | Source |
|-------------|--------|
| `unique_id` | App-provided, prefixed with app name for uniqueness |
| `name` | App-provided |
| `device_class` | App-provided (maps to HA's device classes per platform) |
| `native_value` / `is_on` / etc. | Pushed from Hassette via entity state |
| `extra_state_attributes` | App-provided attributes dict |
| `available` | Derived from Hassette connection status + app status |

### Dynamic Entity Creation/Removal

HA supports adding entities at runtime. The integration would:
1. On initial setup: query `/api/integration/entities`, create all entities
2. On WebSocket `entity_added`: call `async_add_entities([new_entity])`
3. On WebSocket `entity_removed`: call `entity.async_remove()` on the entity, which removes it from HA's entity registry

When HA restarts, the integration re-queries Hassette for the current entity list. HA's entity registry remembers entities between restarts (stores unique_ids), so entities reappear with their customizations (names, areas, etc.) intact.

## 5. Services

### Registering Custom Services

Services are registered in `async_setup` (not `async_setup_entry`) using `hass.services.async_register()`:

```python
async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def handle_reload_app(call: ServiceCall) -> None:
        app_key = call.data["app_key"]
        # Forward to Hassette API
        await client.post(f"/api/apps/{app_key}/reload")

    hass.services.async_register(
        DOMAIN, "reload_app",
        handle_reload_app,
        schema=vol.Schema({vol.Required("app_key"): cv.string}),
    )
```

### Service Types to Expose

| Service | Target | Description |
|---------|--------|-------------|
| `hassette.reload_app` | config_entry | Reload a specific Hassette app |
| `hassette.start_app` | config_entry | Start a stopped app |
| `hassette.stop_app` | config_entry | Stop a running app |
| `hassette.fire_event` | config_entry | Fire a custom event in Hassette's bus |
| App-defined services | entity | Dynamic services declared by individual apps |

Services need a `services.yaml` for UI descriptions and a `strings.json` / `translations/en.json` for localized names.

### Dynamic Services from Apps

Apps could declare services similarly to entities:

```python
self.declare_service(
    name="set_target_temp",
    schema={"target": {"type": "float", "min": 15, "max": 30}},
    handler=self.handle_set_target,
)
```

The integration would register these as HA services when they appear in the entity list response or via WebSocket `service_registered` messages.

## 6. Device Registry Mapping

### Recommended: One Device Per App

Each Hassette app maps to one HA device. This provides:
- Grouping of related entities (a thermostat app owns temp sensor + target temp + mode switch)
- Device info page in HA showing app name, version, status
- Logical organization in HA's device registry

```python
@property
def device_info(self) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"hassette_{self._app_key}")},
        name=self._app_name,
        manufacturer="Hassette",
        model="Hassette App",
        sw_version=self._hassette_version,
        via_device=(DOMAIN, "hassette_instance"),
    )
```

### Hub Device

The Hassette instance itself should be a "hub" device (`via_device`). All app devices are children of this hub. This matches HA's device hierarchy pattern (like a Zigbee coordinator with child devices).

```python
# Hub device (the Hassette instance)
DeviceInfo(
    identifiers={(DOMAIN, f"hassette_{entry.entry_id}")},
    name="Hassette",
    manufacturer="Hassette",
    model="Automation Framework",
    sw_version="0.23.0",
)
```

### Area Assignment

HA lets users assign devices to areas. Since Hassette apps are logical (not physical), apps would not auto-assign to areas -- users can assign them manually in HA's UI.

## 7. Config Flow

### Minimum Viable Config Flow

The config flow needs one step: the user provides the Hassette instance's host and port.

```python
class HassetteConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Validate connection
            try:
                client = HassetteApiClient(user_input["host"], user_input["port"])
                info = await client.get_info()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"hassette_{user_input['host']}_{user_input['port']}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Hassette ({user_input['host']})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("host", default="127.0.0.1"): str,
                vol.Required("port", default=8126): int,
            }),
            errors=errors,
        )
```

The flow validates the connection by hitting Hassette's health endpoint before creating the entry. No authentication needed since Hassette's API is unauthenticated (it runs on the same host or local network).

### Options Flow (Future)

An options flow could allow configuring:
- Which apps to expose to HA (if not all)
- Polling interval for fallback (if WebSocket disconnects)
- Entity naming prefix

## 8. Technical Constraints and Gotchas

### Async Requirements

HA integrations run on HA's event loop. All code must be async-compatible:
- Use `aiohttp` for HTTP/WebSocket connections (Hassette's existing dep)
- Never block the event loop -- no synchronous I/O
- Use `hass.async_create_task()` for background tasks
- HA uses Python 3.12+ (Hassette supports 3.11+, so no conflict)

### Reconnection

The integration must handle Hassette going offline:
- Mark all entities as `unavailable` when connection drops
- Implement exponential backoff reconnection (HA's `DataUpdateCoordinator` handles this)
- On reconnect, re-sync entity list (entities may have changed while disconnected)
- HA's `ConfigEntryNotReady` exception triggers automatic retry if setup fails

### HA Restart

When HA restarts:
1. `async_setup_entry` is called
2. Integration connects to Hassette, queries entities
3. Entities are recreated and matched to registry entries by `unique_id`
4. Customizations (names, areas, icons) persist because they're stored in HA's entity registry, not in the integration

### Hassette Restart

When Hassette restarts:
1. Integration's WebSocket connection drops
2. All entities go `unavailable`
3. Integration reconnects (backoff)
4. On reconnect, re-syncs entities
5. New/removed entities are handled; existing entities regain `available` status

### Thread Safety

HA's entity state updates must happen on the HA event loop. Use `@callback` decorator for synchronous callbacks and `hass.loop.call_soon_threadsafe()` if bridging from another thread. Since the integration uses async WebSocket, this is straightforward.

### HA APIs Available Inside an Integration

Inside an integration, you have full access to:
- `hass.states` -- state machine (read/write any entity state)
- `hass.services` -- register/call services
- `hass.bus` -- fire/listen to events
- `hass.config_entries` -- manage config entries
- `hass.helpers.entity_registry` -- entity registry
- `hass.helpers.device_registry` -- device registry
- `hass.helpers.area_registry` -- area registry

This is a superset of what's available externally via WebSocket/REST.

## 9. Hassette-Side Changes

### New: Entity Declaration API

Apps need a way to declare entities. This is the biggest Hassette-side change.

| Component | Change Type | Description |
|-----------|------------|-------------|
| `App` base class | New methods | `declare_entity()`, `update_entity()`, `remove_entity()`, `declare_service()` |
| Entity registry | New module | Tracks declared entities across all apps, with state |
| Integration API routes | New endpoints | `/api/integration/entities`, `/api/integration/services`, `/api/integration/info` |
| WebSocket protocol | Extension | New message types for entity/service lifecycle events |
| RuntimeQueryService | Extension | Include entity declarations in status queries |

### Estimated Scope

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Entity declaration API (App) | 2-3 new files | Medium | Low -- additive, doesn't change existing App behavior |
| Entity registry module | 1 new file | Medium | Low -- new standalone module |
| Integration API routes | 1-2 new files in `web/routes/` | Low | Low -- follows existing route patterns |
| WebSocket protocol extensions | Modify `ws.py` + `RuntimeQueryService` | Low | Medium -- touches existing broadcast logic |
| HA integration (separate repo) | 8-10 new files | Medium | Medium -- unfamiliar territory |

### What Already Supports This

- **FastAPI web server** (`src/hassette/web/`) is mature and already serves REST + WebSocket endpoints
- **RuntimeQueryService** already tracks app status, entity counts, and broadcasts events
- **App lifecycle hooks** (`on_initialize`, `on_ready`, `on_shutdown`) provide natural places to declare/cleanup entities
- **Event bus** already supports custom event types
- **WebSocket route** (`src/hassette/web/routes/ws.py`) already broadcasts structured JSON messages with type-based routing

### What Works Against This

- **No entity abstraction exists today** -- Hassette apps interact with HA entities via `api.set_state()` / `api.call_service()` but don't "own" entities in any structured way
- **No service declaration concept** -- apps call HA services but don't expose their own operations as services
- **Web API has no authentication** -- the integration would connect unauthenticated (fine for local, but may matter for remote setups)

## 10. Reference Integrations

Study these existing HA integrations as architectural models:

### ESPHome (`homeassistant/components/esphome/`)
**Best reference.** Most similar architecture: separate process, persistent connection, push-based, dynamic entity discovery. Key files:
- `__init__.py` -- setup/teardown pattern with reconnection
- `entity.py` -- base entity class with callback registration
- Platform files (sensor.py, switch.py) -- entity creation from discovery data
- Uses `aioesphomeapi` library for communication

### Node-RED Companion (`custom_components/nodered/`)
Relevant because Node-RED is also a separate automation process. Shows how to bridge an external automation engine's concepts into HA entities/services.

### Home Assistant Core Example (`example-custom-config/detailed_hello_world_push/`)
Official example showing the push-based pattern with callbacks:
- `hub.py` -- external connection model with callback registration
- `cover.py` -- entity using `async_added_to_hass()` / `async_will_remove_from_hass()` for push
- `config_flow.py` -- minimal config flow
- `__init__.py` -- runtime_data pattern

### AppDaemon (`appdaemon`)
Conceptually similar to Hassette (Python app framework for HA). However, AppDaemon does NOT have a custom integration -- it only uses the WebSocket API as a client. Understanding why it chose not to build one (it creates entities via `set_state`) is useful context for what Hassette would gain by going further.

## 11. Open Questions

- [ ] **Should the HA integration live in the Hassette repo or a separate repo?** Separate repo is conventional for custom integrations (easier HACS distribution), but monorepo simplifies development. This research excludes distribution concerns, but repo structure affects development workflow.

- [ ] **What entity platforms to support initially?** Starting with `sensor`, `binary_sensor`, `switch`, and `button` covers most use cases. Adding `number`, `select`, `text`, `light`, `climate`, etc. can come later. Each platform is a separate file but follows the same pattern.

- [ ] **Should the entity declaration API be imperative or declarative?** Imperative (`self.declare_entity(...)` in `on_initialize`) is simpler. Declarative (class-level annotations or a manifest) enables static analysis but is more complex. Recommend starting imperative.

- [ ] **Does the integration need authentication?** Hassette's web API is currently unauthenticated. For local-only setups this is fine. For remote Hassette instances, an API key or token would be needed. Could be deferred.

- [ ] **How should entity unique_ids be structured?** Needs to be globally unique within HA and stable across restarts. Recommendation: `hassette_{app_key}_{app_declared_id}`. The app_key comes from hassette.toml, the declared_id comes from the app's `declare_entity()` call.

- [ ] **Should the integration support multiple Hassette instances?** The config flow pattern naturally supports this (each instance is a separate config entry), but the entity unique_id scheme needs to account for it.

- [ ] **What happens to entities when an app is stopped/reloaded?** Options: mark unavailable, remove entirely, or keep last known state. HA convention is to mark unavailable -- the entity remains in the registry but shows as unavailable.

- [ ] **Should the integration create a Lovelace panel?** HA supports custom panels via integrations. Could embed Hassette's existing web UI in an iframe. Low priority but worth noting.

## Recommendation

This is a solid project with clear HA precedent (ESPHome pattern). The integration side is moderate effort -- the HA custom component framework is well-documented and the push-based coordinator pattern is standard.

The larger effort is on the Hassette side: building the entity declaration API and the integration-facing endpoints. This is net-new functionality that doesn't exist today.

**Suggested approach**: Build in two phases.

### Phase 1: Hassette-side entity declaration API
1. Design the entity declaration data model (Pydantic models for entity declarations)
2. Add `declare_entity()` / `update_entity()` / `remove_entity()` to the `App` base class
3. Build an entity registry service that tracks declarations across apps
4. Add REST endpoints for entity discovery
5. Extend WebSocket protocol with entity lifecycle messages

### Phase 2: HA custom integration
1. Scaffold the integration (manifest, config flow, const)
2. Build the Hassette API client (aiohttp-based)
3. Implement the push-based coordinator
4. Add entity platforms one at a time (sensor first, then expand)
5. Add service registration

### Suggested next steps
1. Write a design doc via `/mine.design` for the entity declaration API
2. Study the ESPHome integration source code in detail (`homeassistant/components/esphome/`)
3. Build a minimal proof-of-concept: one sensor entity, pushed from a Hassette app to HA via the integration

## Sources

- [Home Assistant Integration Service Actions](https://developers.home-assistant.io/docs/dev_101_services/)
- [Home Assistant Fetching Data (DataUpdateCoordinator)](https://developers.home-assistant.io/docs/integration_fetching_data/)
- [Home Assistant Config Entries](https://developers.home-assistant.io/docs/config_entries_index/)
- [Store Runtime Data Inside Config Entry](https://developers.home-assistant.io/blog/2024/04/30/store-runtime-data-inside-config-entry/)
- [Home Assistant Config Flow](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/)
- [HA Example Custom Config - Push Integration](https://github.com/home-assistant/example-custom-config/tree/master/custom_components/detailed_hello_world_push)
- [ESPHome Native API Architecture](https://developers.esphome.io/architecture/api/)
- [ESPHome Integration Source](https://github.com/home-assistant/core/tree/dev/homeassistant/components/esphome)
- [Building a HA Custom Component Series](https://aarongodfrey.dev/home%20automation/building_a_home_assistant_custom_component_part_1/)
- [Writing HA Core Integration](https://jnsgr.uk/2024/10/writing-a-home-assistant-integration/)
- [HA Entity and Registry Management (DeepWiki)](https://deepwiki.com/home-assistant/core/2.2-entity-and-registry-management)
