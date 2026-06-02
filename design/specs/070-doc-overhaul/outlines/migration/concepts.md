# Migration — Mental Model

**Page type:** Migration (concept comparison)
**Reader's job:** Understand the structural differences between AppDaemon and Hassette so they can write idiomatic Hassette code instead of translating AppDaemon patterns one-for-one.
**Voice mode:** Concept — comparison-driven, "you" allowed

## What was cut (and where it goes)

- Nothing cut. The existing page is well-structured. The rewrite reorders sections by what hits the reader first during migration (class shape, then async, then types) rather than by abstraction level (execution model first).

## Outline

### H2: App Structure — Inheritance vs Composition
Lead with the most visible change: the class definition. AppDaemon's `Hass` base class with `initialize()` vs Hassette's `App[Config]` with `async def on_initialize()`. Side-by-side tab snippets. Key differences list: base class, lifecycle hook name, `async` keyword. This is the first thing a migrator edits, so it comes first.

### H2: Access Model — `self.method()` vs `self.component.method()`
AppDaemon's flat `self.listen_state()` / `self.call_service()` surface vs Hassette's composition: `self.bus`, `self.scheduler`, `self.api`, `self.states`, `self.cache`, `self.logger`. Table mapping each attribute to what it does.

### H2: Async vs Sync
Single-threaded async (Hassette) vs multi-threaded (AppDaemon). What this means in practice: `await` on API calls and bus registrations. Mention `AppSync` as the escape hatch for existing sync codebases — one paragraph, link to the full `AppSync` section below.

### H2: Typed vs Untyped
String-based AppDaemon returns vs typed Pydantic models in Hassette. Three areas: entity states (`LightState` vs raw dict), app configuration (`AppConfig` vs `self.args`), API responses (structured models vs dicts).

### H2: Callback Signatures — Fixed vs Flexible
AppDaemon's rigid `(self, entity, attribute, old, new, **kwargs)` vs Hassette's DI-based signatures. Three options: full event object, DI annotations for specific fields, or no arguments. Link to Bus & Events for the full DI reference.

### H2: Synchronous API (`AppSync`)
For codebases with heavy sync logic. `AppSync` runs lifecycle hooks in a managed thread. Bus, scheduler, and API accessed through `.sync` facades. One snippet. Position this as an intermediate step, not the target.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `concepts_sync_async.py` | Keep | Async vs sync comparison |
| `concepts_appdaemon_app.py` | Keep | AppDaemon app structure |
| `concepts_hassette_app.py` | Keep | Hassette app structure |
| `concepts_appsync.py` | Keep | AppSync example |

## Cross-Links

- **Links to:** Migration overview, Bus & Events (DI), Apps overview, AppSync reference
- **Linked from:** Migration overview
