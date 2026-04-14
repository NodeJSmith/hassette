# App Lifecycle

Every app follows a structured lifecycle with clear startup and shutdown phases. Hassette ensures that all resources are managed automatically, so you can focus on your automation logic.

## Initialization

During startup, Hassette transitions the app through `STARTING → RUNNING`.

Hassette ensures that all core services (API, Bus, Scheduler) are fully ready before calling your initialization hooks.

The initialization hooks are called in this order:

1. `before_initialize`
2. `on_initialize`
3. `after_initialize`

Use these to register event handlers, schedule jobs, or perform any startup logic.

```python
--8<-- "pages/core-concepts/apps/snippets/lifecycle_hooks.py"
```

!!! note
    You do not need to call `super()` in these hooks as the base implementations are empty.

## Shutdown

When shutting down or reloading, Hassette transitions the app through `STOPPING → STOPPED`.

The shutdown hooks are called in this order:

1. `before_shutdown`
2. `on_shutdown`
3. `after_shutdown`

## Automatic Cleanup

After the shutdown hooks run, Hassette automatically performs cleanup:

- Cancels all active subscriptions created by `self.bus`.
- Cancels all scheduled jobs created by `self.scheduler`.
- Cancels any background tasks tracked by the app.

This means you generally do **not** need to manually unsubscribe or cancel jobs in `on_shutdown`. Only implement shutdown logic if you have allocated external resources (like opening a file or a raw socket).

!!! warning
    **Do not override** `initialize`, `shutdown`, or `cleanup` methods directly. These are internal methods that manage resource setup, lifecycle ordering, and teardown — they are marked final to prevent accidental overrides that could break the resource contract.

    Use the `on_initialize` and `on_shutdown` hooks instead — they are called at the correct point within these methods. Attempting to override a final method will raise a [`CannotOverrideFinalError`][hassette.exceptions.CannotOverrideFinalError] when your app class is loaded.

## AppSync Lifecycle Hooks

If you use `AppSync` instead of `App`, use the `_sync` variants of each lifecycle hook:

| `App` (async) | `AppSync` (sync) |
|---|---|
| `on_initialize` | `on_initialize_sync` |
| `on_shutdown` | `on_shutdown_sync` |
| `before_initialize` | `before_initialize_sync` |
| `before_shutdown` | `before_shutdown_sync` |
| `after_initialize` | `after_initialize_sync` |
| `after_shutdown` | `after_shutdown_sync` |

`AppSync` runs each lifecycle hook in a thread pool via `run_in_thread`, so the hooks must be synchronous — they cannot use `await`. The async hooks (`on_initialize`, `on_shutdown`, etc.) are marked `@final` on `AppSync` and will raise `NotImplementedError` if you try to override them directly.

!!! warning "Use `on_initialize_sync`, not `on_initialize`, in AppSync"
    In `AppSync`, overriding `on_initialize` will raise `NotImplementedError` at startup. Override `on_initialize_sync` instead:

    ```python
    class MyApp(AppSync):
        def on_initialize_sync(self) -> None:
            self.bus.on_state_change("light.kitchen", handler=self.on_light_change)

        def on_light_change(self):
            # synchronous handler — safe for blocking IO
            pass
    ```
