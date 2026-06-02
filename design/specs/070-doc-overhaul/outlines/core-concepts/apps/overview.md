# Apps Overview

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Understand what an app is, write a minimal one, and discover the handles available for building automations.

## What was cut (and where it goes)

- **Configuration absorbed into overview** — the old outline absorbed the configuration page (34 lines) as an H2. Keeping it. The content (AppConfig subclass, env_prefix, base fields, secrets) is small enough that a separate page creates navigation overhead for no benefit. It fits naturally after "Defining an App."
- **"Core Capabilities" as a bulleted link list** — restructured. The existing page has a list of 8 handles with one-line descriptions, then a "Common Use Cases" section with code snippets. The problem: the link list is pure navigation (belongs in Next Steps), and the use-case snippets duplicate content from the Bus, Scheduler, API, and Cache pages. The rewrite keeps 3-4 short snippets that show the handles working together in one app, not isolated patterns that each subpage covers better.
- **Synchronous Apps** — kept as a collapsible section. Most readers use async `App`. The existing page already uses `??? note` for this, which is right.

## Outline

### H2: (Opening — no heading)
One sentence: an app is a Python class that reacts to events and controls devices. Each app has its own config, state, and a set of handles for interacting with HA.

Mermaid diagram: App -> [Api, Bus, Scheduler, States, Cache] (keep existing).

### H2: Defining an App
Minimal app example: subclass `App[MyConfig]`, override `on_initialize`, register a handler, call a service. This is the anchor example — the reader sees the full shape before any explanation.

Snippet: `example_app.py`.

Brief DI callout (keep existing `!!! info` about `D.StateNew`).

### H2: Configuration
AppConfig subclass with `SettingsConfigDict` and `env_prefix`. Base fields: `instance_name`, `log_level`. Secrets via env vars. `extra="allow"` for arbitrary config.

Snippet: `app_config_definition.py` and `app_config_env_prefix.py`.

Link to Configuration/Applications for the TOML registration side.

### H2: Dates and Times
`self.now()` returns a `ZonedDateTime` (from the `whenever` library). All scheduler parameters, persistent storage, and state definitions use `whenever` types.

Brief explanation of why `whenever` over stdlib `datetime` (immutable, always timezone-aware).

Snippet: `apps_whenever_dates.py`.

### H2: What an App Can Do
3-4 short snippets showing the most common patterns, each with a one-line intro and a link to the full page. Ordered by what a new user needs first:

#### H3: React to Events
`self.bus.on_state_change(...)` -> Bus page.

#### H3: Schedule Jobs
`self.scheduler.run_every(...)` -> Scheduler page.

#### H3: Read Entity States
`self.states.light["kitchen"]` -> States page.

#### H3: Call Services
`self.api.call_service(...)` -> API page.

`await` warning callout (keep existing — forgetting `await` is a real trap).

#### H3: Persist Data
`self.cache.get(...)` / `self.cache.set(...)` -> Cache page.

#### H3: Run Background Work
`self.task_bucket.spawn(...)` -> Task Bucket page.

### H2: Restricting to a Single App
`@only_app` decorator for development isolation. Remove before deploying.

### H2: Broadcasting Between Apps
`Bus.emit(topic, data)` for in-process inter-app events. `self.bus.on(topic=...)` to subscribe. Events stay local, are not persisted.

Snippet: sender and receiver apps.

Self-delivery note (app receives its own events — filter with a `source` field).

### H2: Synchronous Apps
??? collapsible. `AppSync` for blocking libraries. `_sync` lifecycle hooks. `.sync` facades for bus, scheduler, API. Prefer async `App` whenever possible.

### H2: Next Steps
- Lifecycle — `on_initialize`, `on_shutdown`, automatic cleanup
- Task Bucket — background tasks, thread offloading

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `example_app.py` | Keep | Primary defining example |
| `app_config_definition.py` | Keep | Config class definition |
| `app_config_env_prefix.py` | Keep | Env var injection |
| `app_config.toml` | Keep | TOML registration |
| `apps_whenever_dates.py` | Keep | Date/time usage |
| `apps_subscribe_state_change.py` | Keep | Bus snippet for "What an App Can Do" |
| `apps_run_hourly.py` | Keep | Scheduler snippet |
| `apps_check_state.py` | Keep | States snippet |
| `apps_call_service.py` | Keep | API snippet |
| `apps_cache_counter.py` | Keep | Cache snippet |
| `apps_task_bucket.py` | Keep | Task bucket snippet |
| `apps_bus_emit.py` | Keep | Inter-app broadcast |
| `apps_only_app.py` | Keep | Development isolation |

## Cross-Links

- **Links to:** Lifecycle, Task Bucket, Bus overview, Scheduler overview, States overview, API overview, Cache overview, Configuration/Applications (TOML side)
- **Linked from:** Architecture, First Automation, Recipes
