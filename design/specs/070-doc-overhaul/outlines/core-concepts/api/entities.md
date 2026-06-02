# API — Entities & States

**Status:** Exists (72 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Terminology
Three levels of abstraction — match the existing docs terminology section:
- **State Value** (`get_state_value`) — the raw value string, what HA calls `state.state` (e.g., `"on"`, `"23.5"`). Cheapest call when attributes/timestamps aren't needed.
- **State** (`get_state`) — full snapshot: value + typed attributes + timestamps + context. A `BaseState` subclass (e.g., `LightState`). The `.value` field holds the state value, coerced to the domain's type (e.g., `bool` for lights).
- **Entity** (`get_entity`) — wraps a state + adds action methods (`turn_on()`, `turn_off()`, `toggle()`, `refresh()`). A `BaseEntity` subclass (e.g., `LightEntity`). Requires an explicit model type argument.

### H2: Retrieving States
#### H3: Full State Object
`get_state(entity_id)` → typed `BaseState` subclass with `.value`, `.attributes`, `.last_changed`, etc. `get_state_or_none()` → returns `None` instead of raising. `get_state_raw()` → raw `HassStateDict` without type conversion.
#### H3: Just the Value
`get_state_value(entity_id)` → the raw state string only (what HA calls `state.state`). Skips model conversion — use when attributes and timestamps aren't needed.
#### H3: Single Attribute
`get_attribute(entity_id, attribute)` → one attribute value, supports dot-path for nested attributes.
#### H3: Checking Existence
`entity_exists(entity_id)` for boolean check; `get_state_or_none()` for optional return.

### H2: Retrieving Multiple States
`get_states()` — returns all entities (no filtering parameter). `get_states_raw()` for raw dicts.

### H2: Retrieving Entities
`get_entity(entity_id, model)` → typed `BaseEntity` subclass. Wraps the state object and adds domain-specific service methods (e.g., `LightEntity.turn_on(brightness=255)`). `get_entity_or_none(entity_id, model)` → returns `None` instead of raising. Requires passing the entity model class explicitly — the API does not auto-resolve entity types.

#### H3: Entity Properties
`.state` — the underlying typed state object. `.value` — shortcut to `state.value`. `.entity_id`, `.domain` — identity fields. `.api` — direct access to the `Api` instance. `.hassette` — access to the `Hassette` coordinator instance.

#### H3: Refreshing Entity State
`entity.refresh()` — re-fetches state from HA and updates the entity's state object in place.

#### H3: Synchronous Entity Access
`entity.sync` (`BaseEntitySyncFacade`) — mirrors action methods as blocking calls. Available for sync contexts.

#### H3: Generic Type Parameters
`BaseEntity[StateT, StateValueT]` — entities are generic over their state type and value type. Domain entity subclasses (e.g., `LightEntity`) bind these parameters to the corresponding state class.

### H2: When to Use Which
- **`get_state_value`** — just need the value, nothing else
- **`get_state`** — need attributes, timestamps, or the typed value (most common)
- **`get_entity`** — need to call services on the entity (turn_on, turn_off, etc.)

### H2: API vs StateManager
Expanded comparison: when to hit HA directly vs use the local cache.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Relevant files from `api/snippets/` | Review | Entity access examples |

## Cross-Links

- **Links to:** States overview, State Registry, API overview
- **Linked from:** API overview
