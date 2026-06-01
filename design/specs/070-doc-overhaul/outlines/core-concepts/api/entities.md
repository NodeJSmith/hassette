# API — Entities & States

**Status:** Exists (72 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Terminology
Entity, state, attributes — HA concepts mapped to Hassette types.

### H2: Retrieving States
Three levels of state access — clarify the distinction:
#### H3: Full State Object
`get_state(entity_id)` → typed state model (e.g., `LightState`) with `.value`, `.attributes`, `.last_changed`, etc. `get_state_or_none()` → same but returns `None` instead of raising. `get_state_raw()` → raw `HassStateDict` without type conversion.
#### H3: Just the Value
`get_state_value(entity_id)` → the state string only (e.g., `"on"`, `"23.5"`). `get_state_value_typed(entity_id)` → value run through the type registry (e.g., `True`, `23.5`).
#### H3: Single Attribute
`get_attribute(entity_id, attribute)` → one attribute value, supports dot-path for nested attributes.
#### H3: Checking Existence
`entity_exists(entity_id)` for boolean check; `get_state_or_none()` for optional return.

### H2: Retrieving Multiple States
`get_states()` — returns all entities (no filtering parameter). `get_states_raw()` for raw dicts.

### H2: Entities vs States
Entity = the registry record (device info, area, capabilities). State = the current value and attributes.
#### H3: Entity Access
`get_entity(entity_id, model)` → typed `BaseEntity` subclass with registry metadata. Requires an explicit model type argument. `get_entity_or_none(entity_id, model)` → same but returns `None`.
#### H3: When to Use Which
- **`get_state`** — "what is this entity doing right now?" (value, attributes, last_changed)
- **`get_entity`** — "what IS this entity?" (device, area, capabilities, registry metadata)
- **`get_state_value`** — "just give me the value string, nothing else"

### H2: API vs StateManager
Expanded comparison: when to hit HA directly vs use the local cache.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Relevant files from `api/snippets/` | Review | Entity access examples |

## Cross-Links

- **Links to:** States overview, State Registry, API overview
- **Linked from:** API overview
