# Apps — Lifecycle

Hassette manages app initialization and shutdown. The app declares what to do at each stage through lifecycle hooks.

## Initialization

Hassette transitions the app through `STARTING` to `RUNNING` at startup. All core services (API, `Bus`, `Scheduler`, and database) are ready before any hook runs.

Three hooks fire in order:

1. `before_initialize`
2. `on_initialize`, the primary hook for handler registration, job scheduling, and startup logic
3. `after_initialize`

```python
--8<-- "pages/core-concepts/apps/snippets/lifecycle_hooks.py"
```

`on_initialize` is where most apps do their setup. `self.bus.on_state_change` registers a handler that fires on entity state changes. `self.scheduler.run_in` schedules a one-shot job after a fixed delay. Both calls are `async` and must be awaited. By the time `on_initialize` runs, the bus, scheduler, API, and database are all ready.

`before_initialize` and `after_initialize` exist for setup that must happen strictly before or after the main registration. Most apps only need `on_initialize`.

!!! note
    The base implementations of these hooks are empty. No `super()` call is necessary.

## Shutdown

Hassette transitions the app through `STOPPING` to `STOPPED` during shutdown or reload.

Three hooks fire in order:

1. `before_shutdown`
2. `on_shutdown`
3. `after_shutdown`

`on_shutdown` is for releasing external resources the app allocated directly: open files, raw sockets, or third-party connections. `Bus` subscriptions, scheduled jobs, and [`task_bucket`](task-bucket.md) tasks are cleaned up automatically.

## Automatic Cleanup

After the shutdown hooks complete, Hassette cancels all bus subscriptions created via `self.bus`, all scheduled jobs created via `self.scheduler`, and all background tasks tracked by `self.task_bucket`. Manual unsubscription or job cancellation in `on_shutdown` is unnecessary.

!!! warning
    `initialize`, `shutdown`, and `cleanup` are marked `@final` — attempting to override any of them raises [`CannotOverrideFinalError`][hassette.exceptions.CannotOverrideFinalError] at class load time. The `before_*`, `on_*`, and `after_*` hooks are the extension points.

## Synchronous Lifecycle

??? note "`AppSync` lifecycle hooks"

    [`AppSync`][hassette.app.app.AppSync] is for apps that wrap blocking (non-async) third-party libraries. It provides `_sync`-suffixed variants of each hook. Hassette runs each variant in a thread pool via `task_bucket.run_in_thread`, so blocking calls do not stall the event loop. The `_sync` hooks are synchronous and cannot use `await`.

    | `App` (async) | `AppSync` (sync) |
    |---|---|
    | `before_initialize` | `before_initialize_sync` |
    | `on_initialize` | `on_initialize_sync` |
    | `after_initialize` | `after_initialize_sync` |
    | `before_shutdown` | `before_shutdown_sync` |
    | `on_shutdown` | `on_shutdown_sync` |
    | `after_shutdown` | `after_shutdown_sync` |

    The async hooks (`on_initialize`, `on_shutdown`, etc.) are marked `@final` on `AppSync` and delegate to the `_sync` variants via the thread pool. Overriding them raises [`CannotOverrideFinalError`][hassette.exceptions.CannotOverrideFinalError] at class load time.

    The bus, scheduler, and API are async. The `.sync` facades provide synchronous access from `_sync` hooks: `self.bus.sync`, `self.scheduler.sync`, and `self.api.sync`.

    ```python
    --8<-- "pages/core-concepts/apps/snippets/lifecycle_sync.py"
    ```

## See Also

- [Apps overview](index.md): app structure and configuration
- [Task Bucket](task-bucket.md): background task lifecycle and shutdown behavior
- [`Bus`](../bus/index.md): handler registration in `on_initialize`
