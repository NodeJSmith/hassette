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
Table of all auto-generated domain state classes (SensorState, LightState, etc.) with key attributes.

### H2: Good to Know
Edge cases, caching behavior, state freshness.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| 4 files in `states/snippets/` | Keep | Basic state access examples |
| Additional snippets from `core-concepts/snippets/` | Review | 3 files — check if states-related |

## Cross-Links

- **Links to:** Subscribing, DomainStates Reference, Custom States, State Registry, Type Registry
- **Linked from:** Architecture, Apps overview, API/Entities
