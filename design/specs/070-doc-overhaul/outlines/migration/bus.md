# Migration — Bus & Events

**Page type:** Migration (feature comparison)
**Reader's job:** Convert their AppDaemon `listen_state` / `listen_event` calls to Hassette bus subscriptions, with correct syntax and without silent breakage.
**Voice mode:** Comparison — tabs for side-by-side, "you" allowed

## What was cut (and where it goes)

- **Overview section** folded into a one-sentence intro. The reader already knows what the bus is from the migration overview; repeating the mapping wastes their time.
- **Common Migration Patterns** section removed. Each pattern (state change with filter, service call subscription) is already shown as a side-by-side example in its respective section above. The "patterns" section was duplicating those examples without adding new information.

## Outline

### H2: The `name=` Requirement
Lead with the most common migration breakage. Every `self.bus.on_*()` call requires `name=`. Omitting it raises `ListenerNameRequiredError`. One sentence explaining why (telemetry tracking, log readability). One snippet showing the fix. This goes first because it blocks every other bus migration step.

### H2: State Change Listeners
Side-by-side tabs: AppDaemon `listen_state` vs Hassette `on_state_change`.

**Sub-sections:**
- AppDaemon pattern (snippet)
- Hassette with DI (recommended) — `D.StateNew[T]` annotation (snippet)
- Hassette with full event object — for readers who want the raw event (snippet)
- Filter argument mapping table: `new=` -> `changed_to=`, `old=` -> `changed_from=`, `attribute=` -> use `on_attribute_change()`. Link to Filtering page for predicates.

### H2: Attribute Change Listeners
AppDaemon's `listen_state(..., attribute="battery")` maps to Hassette's `on_attribute_change(entity_id, "battery", ...)`. Brief, one side-by-side example.

### H2: Service Call Listeners
Side-by-side tabs: AppDaemon `listen_event("call_service")` vs Hassette `on_call_service`.

**Sub-sections:**
- AppDaemon pattern (snippet)
- Hassette with DI (recommended) — `D.Domain`, `D.EntityId`, etc. (snippet)
- Hassette with full event object (snippet)
- Available DI markers for service call handlers (bullet list)

### H2: Canceling Subscriptions
Side-by-side tabs: `self.cancel_listen_state(handle)` vs `subscription.cancel()`. Note that all three registration methods are async and must be awaited.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `bus_appdaemon_state_change.py` | Keep | AppDaemon state listener |
| `bus_hassette_state_change_di.py` | Keep | DI-based handler |
| `bus_hassette_state_change_event.py` | Keep | Full event handler |
| `bus_appdaemon_event.py` | Keep | AppDaemon service call listener |
| `bus_hassette_on_call_service_di.py` | Keep | DI-based service call handler |
| `bus_hassette_on_call_service_event.py` | Keep | Full event service call handler |
| `bus_cancel_subscription.py` | Keep | Subscription cancellation |
| `bus_migration_state_changes.py` | Keep | Used in state change side-by-side |
| `bus_migration_service_calls.py` | Keep | Used in service call side-by-side |

## Cross-Links

- **Links to:** Bus overview, Handlers, Filtering, Dependency Injection
- **Linked from:** Migration overview, Migration checklist
