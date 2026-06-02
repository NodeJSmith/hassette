# API — Entities & States

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Retrieve the current state of an entity from Home Assistant, at the right level of detail for their use case.

## What was cut (and where it goes)

- **API vs StateManager** — removed from this page. The overview page already covers this decision, and repeating it here splits the reader's attention. A one-line callout linking back to the overview is enough.
- **Terminology as a standalone section** — dissolved. The three levels (value, state, entity) are introduced inline as each method is shown, not front-loaded as abstract definitions before the reader has seen any code.
- **Generic type parameters** (`BaseEntity[StateT, StateValueT]`) — cut from the main flow. This is implementation detail relevant to framework contributors or advanced users extending entity types. Mention in a collapsible section under Entities if needed.
- **Synchronous entity access** (`entity.sync`) — belongs in a collapsible note, not a full section. Sync usage is rare and covered at the overview level.

## Outline

### H2: (Opening — no heading)
One sentence: the API retrieves entity state directly from Home Assistant over the network. Three methods cover three levels of detail — pick the one that matches what the code needs.

### H2: Get the Value
`get_state_value(entity_id)` returns the raw state string (`"on"`, `"23.5"`, `"above_horizon"`). The cheapest call when attributes and timestamps are not needed.

Snippet: one-liner showing `get_state_value`.

### H2: Get the Full State
`get_state(entity_id)` returns a typed `BaseState` subclass (e.g., `LightState`) with `.value`, `.attributes`, `.last_changed`, `.last_updated`, `.context`. The `.value` field is coerced to the domain's Python type (e.g., `bool` for lights, `float` for sensors).

Snippet: `get_state` with attribute access.

#### H3: Optional Lookup
`get_state_or_none(entity_id)` returns `None` instead of raising when the entity does not exist. `entity_exists(entity_id)` for a boolean check.

#### H3: Raw Dict
`get_state_raw(entity_id)` returns the untyped `HassStateDict` — useful when working outside the type registry or debugging.

### H2: Get an Entity
`get_entity(entity_id, model)` wraps the state in a `BaseEntity` subclass that adds domain-specific action methods (`turn_on()`, `turn_off()`, `toggle()`, `refresh()`). Requires passing the entity model class explicitly.

Snippet: `get_entity` with a `LightEntity` showing `.turn_on(brightness=255)`.

#### H3: Refreshing State
`entity.refresh()` re-fetches from HA and updates the entity's state in place.

### H2: Fetching Multiple States
`get_states()` retrieves all entities in one call. `get_states_raw()` for raw dicts. No filtering parameter — filter in Python after fetching.

### H2: Which Method to Use
Short decision table (3 rows):
- Need just the value string -> `get_state_value`
- Need attributes, timestamps, or typed value -> `get_state` (most common)
- Need to call services on the entity -> `get_entity`

### H2: See Also
Links to States overview (local cache), API overview, Services.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `api_get_state.py` | Keep | Full state example |
| `api_get_state_raw.py` | Keep | Raw dict example |
| `api_check_existence.py` | Keep | Optional lookup |
| `api_get_entity.py` | Keep | Entity with actions |
| `api_get_states.py` | Keep | Bulk fetch |
| New: `api_get_state_value.py` | Create | Simple value retrieval — currently missing |

## Cross-Links

- **Links to:** States overview (local cache), API overview, Services
- **Linked from:** API overview, Apps overview
