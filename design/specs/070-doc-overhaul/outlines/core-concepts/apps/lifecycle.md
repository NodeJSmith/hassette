# Apps — Lifecycle

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Know which hooks to override for startup and shutdown logic, and understand what Hassette cleans up automatically so they do not duplicate that work.

## What was cut (and where it goes)

- **AppSync lifecycle table** — demoted to a collapsible section at the bottom. Most readers use async `App`. The sync variant is a lookup reference for the few who need it, not a primary learning path.
- **The "do not override `initialize`/`shutdown`/`cleanup`" warning** — kept and promoted slightly. This is a real trap (raises `CannotOverrideFinalError`) that readers hit when they guess at method names.

## Outline

### H2: (Opening — no heading)
One sentence: every app goes through initialization and shutdown. Hassette manages the resource lifecycle; the app declares what to do at each stage.

### H2: Initialization
During startup, Hassette transitions the app through `STARTING -> RUNNING`. All core services (API, Bus, Scheduler, database) are ready before any hook runs.

Three hooks fire in order:
1. `before_initialize`
2. `on_initialize` — the main hook. Register handlers, schedule jobs, provision helpers here.
3. `after_initialize`

Snippet: `on_initialize` with handler registration and scheduler setup.

Note: no `super()` call needed — base implementations are empty.

### H2: Shutdown
During shutdown or reload, Hassette transitions through `STOPPING -> STOPPED`.

Three hooks fire in order:
1. `before_shutdown`
2. `on_shutdown`
3. `after_shutdown`

Implement `on_shutdown` only when the app has external resources to release (open files, raw sockets, external connections). For bus subscriptions, scheduler jobs, and task bucket tasks, Hassette handles cleanup automatically.

### H2: Automatic Cleanup
After the shutdown hooks complete, Hassette:
- Cancels all bus subscriptions created by `self.bus`
- Cancels all scheduled jobs created by `self.scheduler`
- Cancels all background tasks tracked by `self.task_bucket`

This means `on_shutdown` does not need to manually unsubscribe or cancel jobs.

Warning: do not override `initialize`, `shutdown`, or `cleanup` directly. These are internal methods marked `@final`. Attempting to override them raises `CannotOverrideFinalError` at class load time. Use the `on_*` hooks instead.

### H2: Synchronous Lifecycle
??? collapsible. `AppSync` uses `_sync` suffixed hooks. Table mapping async to sync variants. The bus, scheduler, and API are async — reach them via `.sync` facades from sync hooks.

Snippet: `AppSync.on_initialize_sync` with `.sync` facade calls.

Warning: overriding `on_initialize` (async) in an `AppSync` raises `NotImplementedError`. Override `on_initialize_sync` instead.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `lifecycle_hooks.py` | Keep | Main initialization example |
| New: `lifecycle_sync.py` | Create | AppSync lifecycle (currently inline in existing page) |

## Cross-Links

- **Links to:** Apps overview, Task Bucket (shutdown behavior), Bus overview (registration in on_initialize)
- **Linked from:** Apps overview (Next Steps)
