# API — Entities & States

**Status:** Exists (72 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Terminology
Entity, state, attributes — HA concepts mapped to Hassette types.

### H2: Retrieving States
`get_state(entity_id)` — single entity. Also: `get_state_or_none()`, `get_state_value()`, `get_state_value_typed()`, `get_attribute(entity_id, attribute)`.
#### H3: Raw vs Typed
`get_state_raw()` returns raw `HassStateDict`; `get_state()` returns typed model.
#### H3: Checking Existence
`entity_exists(entity_id)` for boolean check; `get_state_or_none()` for optional return.

### H2: Retrieving Multiple States
`get_states()` — returns all entities (no filtering parameter). `get_states_raw()` for raw dicts.

### H2: Entities
Entity registry access.

### H2: API vs StateManager
Expanded comparison: when to hit HA directly vs use the local cache.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Relevant files from `api/snippets/` | Review | Entity access examples |

## Cross-Links

- **Links to:** States overview, State Registry, API overview
- **Linked from:** API overview
