# States — DomainStates Reference

**Status:** ABSORBED into `states/overview.md` "Built-in State Types" section. This page will be removed from nav.
**Voice mode:** Reference — tabular, terse, system-as-subject

## Outline

### H2: (Opening)
Brief explanation of auto-generated domain state classes. Each HA entity domain has a corresponding Python class with typed attributes.

### H2: Reference Table
Large reference table of all domain state classes. For each:
- Domain name (e.g., `light`)
- State class (e.g., `LightState`)
- `value` type (bool, str, float, etc.)
- Key attributes (e.g., `brightness`, `color_temp`, `rgb_color`)

### H2: Accessing Domain States
How to use these classes: `self.states.light.get("light.kitchen")` returns a `LightState`. Show the pattern once.

### H2: Attribute Access
Common attribute patterns across domains. Attributes are Python-typed (not raw HA dicts).

### H2: Generated vs Custom
These classes are auto-generated from HA core source. For domains not covered or for custom attributes, use Custom States.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| New: domain state access example | New | Accessing typed attributes from a LightState |
| New: sensor state example | New | SensorState with numeric value and unit |

## Cross-Links

- **Links to:** Custom States, State Registry, States overview
- **Linked from:** States overview, DI page (annotation types reference T)
