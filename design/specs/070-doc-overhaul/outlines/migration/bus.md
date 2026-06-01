# Migration — Bus & Events

**Status:** Exists (151 lines), comparison-driven, voice polish needed
**Voice mode:** Comparison — tabs for side-by-side, "you" allowed

## Outline

### H2: Overview
What changes: `listen_state` → `on_state_change`, `listen_event` → `on`.

### H2: State Change Listeners
#### H3: AppDaemon — `listen_state` pattern
#### H3: Hassette: with DI (recommended) — `on_state_change` + `D.StateNew[T]`
#### H3: Hassette: with full event object
#### H3: Filter options — `changed_to`, `changed_from`, predicates

### H2: Service Call Listeners
#### H3: AppDaemon — `listen_event("call_service")`
#### H3: Hassette: with DI (recommended)
#### H3: Hassette: with full event object

### H2: Attribute Change Listeners
AppDaemon `listen_state(..., attribute=...)` → Hassette `on_attribute_change(entity_id, attribute, ...)`.

### H2: The `name=` Requirement
All bus subscription methods require `name=`. Omitting it raises `ListenerNameRequiredError`. Most common migration breakage point.

### H2: Canceling Subscriptions
Handle patterns comparison.

### H2: Common Migration Patterns
State changes with filter, service call subscriptions.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| ~8 migration/bus snippets | Keep | Side-by-side comparison pairs |

## Cross-Links

- **Links to:** Bus overview, DI page, States/Subscribing, Bus/Filtering
- **Linked from:** Migration overview
