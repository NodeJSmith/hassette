# Migration — API Calls

**Status:** Exists (130 lines), comparison-driven, voice polish needed
**Voice mode:** Comparison — "you" allowed

## Outline

### H2: Overview
What changes: `self.get_state()` → `self.states.get()` or `self.api.get_state()`.

### H2: Getting Entity State
#### H3: AppDaemon
#### H3: Hassette: State Cache (recommended)
#### H3: Hassette: Direct API Call

### H2: Calling Services
AppDaemon `call_service` vs Hassette `api.call_service`.

### H2: Setting States
AppDaemon `set_state` vs Hassette `api.set_state`.

### H2: Logging
AppDaemon `self.log` vs Hassette `self.logger`.

### H2: Full State Migration Example
Complete before/after.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| ~6 migration/api snippets | Keep | Comparison pairs |

## Cross-Links

- **Links to:** API overview, States overview, API/Entities
- **Linked from:** Migration overview
