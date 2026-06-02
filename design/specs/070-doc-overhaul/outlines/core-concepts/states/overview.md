# States — Overview

**Status:** Exists (179 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### (Opening)
Functional definition of the StateManager: what it does, `self.states` access. Match the Bus exemplar pattern — prose first.

### Mermaid Diagram
StateManager → StateProxy → DomainStates flow. Comes after the opening prose, not before it.

### H2: Using the StateManager
#### H3: Domain Access — `self.states.light`, `self.states.sensor`
#### H3: Direct Entity Access — `self.states.get("light.kitchen")`
#### H3: Generic Access — `self.states[CustomState]`
#### H3: Iteration

### H2: DomainStates Collection Interface
Methods: `get()`, `items()`, `keys()`, `values()`, `to_dict()`, `__iter__`, `__len__`, `__contains__`, `__getitem__`, `__bool__`.

### H2: Built-in State Types
Brief introduction: Hassette auto-generates typed state classes for 47 HA domains from HA core source. Show 2-3 examples inline (LightState with brightness, SensorState with numeric value, BinarySensorState with device_class). Explain the pattern: domain → state class → typed `value` + typed attributes. Link to auto-generated API reference (`hassette.models.states`) for the full inventory. For domains not covered or custom attributes, link to Custom States.

*No hand-written reference table — the API reference auto-generates from source and never rots.*

### H2: State Model Properties
Properties available on all `BaseState` subclasses beyond `value` and `attributes`:
- `is_unknown` / `is_unavailable` — boolean flags. When HA reports `"unknown"` or `"unavailable"`, the state string is not stored in `value` (which would break strong typing — e.g., `bool` for switches, `float` for sensors). Instead, `value` is set to `None` and the corresponding flag is set to `True`. Check these flags before using `value`.
- `is_group` — whether the entity is a group entity
- `extras` dict and `extra(key)` method — access to untyped attributes not declared on the typed attributes class

Properties on `AttributesBase`:
- `has_feature(flag)` — bitfield check against `supported_features` for domain-specific capability detection (e.g., `SUPPORT_BRIGHTNESS`)

### H2: Good to Know
Edge cases, caching behavior, state freshness.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| 4 files in `states/snippets/` | Keep | Basic state access examples |
| Additional snippets from `core-concepts/snippets/` | Review | 3 files — check if states-related |

## Cross-Links

- **Links to:** Subscribing, Custom States, State Registry, Type Registry
- **Linked from:** Architecture, Apps overview, API/Entities
