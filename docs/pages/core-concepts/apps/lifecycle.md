# App Lifecycle

Every app follows a structured lifecycle with clear startup and shutdown phases. Hassette ensures that all resources are managed automatically, so you can focus on your automation logic.

## Initialization

During startup, Hassette transitions the app through `STARTING → RUNNING`.

Hassette ensures that all core services (API, Bus, Scheduler) are fully ready before calling your initialization hooks.

The initialization hooks are called in this order:

1. [`before_initialize`][hassette.resources.base.Resource.before_initialize]
2. [`on_initialize`][hassette.resources.base.Resource.on_initialize]
3. [`after_initialize`][hassette.resources.base.Resource.after_initialize]

Use these to register event handlers, schedule jobs, or perform any startup logic.

```python
--8<-- "pages/core-concepts/apps/snippets/lifecycle_hooks.py"
```

!!! note
    You do not need to call `super()` in these hooks as the base implementations are empty.

## Shutdown

When shutting down or reloading, Hassette transitions the app through `STOPPING → STOPPED`.

The shutdown hooks are called in this order:

1. [`before_shutdown`][hassette.resources.base.Resource.before_shutdown]
2. [`on_shutdown`][hassette.resources.base.Resource.on_shutdown]
3. [`after_shutdown`][hassette.resources.base.Resource.after_shutdown]

## Automatic Cleanup

After the shutdown hooks run, Hassette automatically performs cleanup:

- Cancels all active subscriptions created by `self.bus`.
- Cancels all scheduled jobs created by `self.scheduler`.
- Cancels any background tasks tracked by the app.

This means you generally do **not** need to manually unsubscribe or cancel jobs in `on_shutdown`. Only implement shutdown logic if you have allocated external resources (like opening a file or a raw socket).

!!! warning
    **Do not override** `initialize`, `shutdown`, or `cleanup` methods directly. Check `on_initialize` and `on_shutdown` instead.

    Attempting to override these methods will raise a [`CannotOverrideFinalError`][hassette.exceptions.CannotOverrideFinalError] when your app class is loaded.
