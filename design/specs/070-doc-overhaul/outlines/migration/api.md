# Migration — API Calls

**Page type:** Migration (feature comparison)
**Reader's job:** Convert their AppDaemon state reads, service calls, and logging to Hassette's `self.states`, `self.api`, and `self.logger`.
**Voice mode:** Comparison — "you" allowed

## What was cut (and where it goes)

- **Overview section** reduced to a one-sentence intro. The existing overview spent 6 lines restating what the sub-sections demonstrate. The reader learns faster from the first example.
- **Full State Migration Example** section removed. The Getting Entity State section already shows a complete before/after. A standalone "full example" at the end duplicated it.

## Outline

### H2: Getting Entity State
The most common API operation comes first. Three sub-sections, each with a snippet:

- **AppDaemon** — `self.get_state()` returns strings/dicts
- **Hassette: State Cache (recommended)** — `self.states.light.get("light.kitchen")` returns `LightState | None`. Access pattern table: domain-typed, generic, iteration. No `await` needed.
- **Hassette: Direct API Call** — `await self.api.get_state()` for fresh reads from HA (rare).

One-paragraph guidance: use `self.states` for reads in handlers and scheduled tasks; use `self.api.get_state()` only when you need to bypass the cache.

### H2: Calling Services
Side-by-side tabs: AppDaemon's `self.call_service("domain/service", ...)` (synchronous, slash-separated) vs Hassette's `await self.api.call_service("domain", "service", ...)` (async, separate arguments). Warning: forgetting `await` silently does nothing.

### H2: Setting States
Side-by-side tabs: `self.set_state(...)` vs `await self.api.set_state(...)`. Brief.

### H2: Logging
Side-by-side tabs: AppDaemon's `self.log()` / `self.error()` vs Hassette's `self.logger.info()` / `.warning()` / `.error()`. Note: Hassette logger includes instance name, method, and line number automatically. Use `%s`-style formatting.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `api_appdaemon_get_state.py` | Keep | AppDaemon state access |
| `api_hassette_states_cache.py` | Keep | State cache access |
| `api_hassette_get_state_api.py` | Keep | Direct API call |
| `api_hassette_call_service.py` | Keep | Service call |
| `api_hassette_set_state.py` | Keep | Set state |
| `api_logging.py` | Keep | Logging comparison |
| `api_migration_getting_states.py` | Remove | Duplicates the state cache section |

## Cross-Links

- **Links to:** API overview, States overview, Entities & States, Services
- **Linked from:** Migration overview, Migration checklist
