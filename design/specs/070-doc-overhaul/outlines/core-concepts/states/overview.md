# States — Overview

**Status:** Exists (179 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Diagram
Mermaid diagram showing StateManager → StateProxy → DomainStates flow.

### H2: Using the StateManager
#### H3: Domain Access — `self.states.light`, `self.states.sensor`
#### H3: Direct Entity Access — `self.states.get("light.kitchen")`
#### H3: Generic Access — `self.states[CustomState]`
#### H3: Iteration

### H2: DomainStates Collection Interface
Methods: `get()`, `items()`, `keys()`, `values()`, `to_dict()`, `__iter__`, `__len__`, `__contains__`, `__getitem__`, `__bool__`.

### H2: Built-in State Types
Reference table of all auto-generated domain state classes. For each: domain name, state class (e.g., `LightState`), `value` type (bool, str, float, etc.), key attributes (e.g., `brightness`, `color_temp`). These classes are auto-generated from HA core source. Common attribute patterns across domains. Attributes are Python-typed, not raw HA dicts. For domains not covered or custom attributes, link to Custom States.

*Absorbs content from the former `domain-states.md` standalone page.*

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
