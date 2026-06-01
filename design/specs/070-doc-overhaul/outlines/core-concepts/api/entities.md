# API — Entities & States

**Status:** Exists (72 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Terminology
Entity, state, attributes — HA concepts mapped to Hassette types.

### H2: Retrieving States
`get_state(entity_id)` — single entity.
#### H3: Raw vs Typed
Raw string state vs typed state model conversion.
#### H3: Checking Existence
What happens when an entity doesn't exist.

### H2: Retrieving Multiple States
`get_states()` — all entities or filtered.

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
