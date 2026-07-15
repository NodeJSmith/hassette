# Your First Automation

This page adds two features to the app from the [Quickstart](index.md):

- **A sunset handler** that turns on a light when the sun sets, with typed state data filled in automatically
- **A heartbeat job** that logs every minute

## Subscribe to a State Change

```python hl_lines="1 11 12 13 15 16 17 18 19 20"
--8<-- "pages/getting-started/snippets/first_automation_step3.py"
```

[`self.bus.on_state_change()`](../core-concepts/bus/index.md) registers a handler that fires whenever an entity's state changes, like a light switching on or a sensor reporting a new reading. `"sun.*"` is a glob pattern that matches any entity in the `sun` domain. In practice, that's `sun.sun`. The `name=` parameter labels this handler in logs and the [web UI](../web-ui/index.md) (a monitoring dashboard Hassette includes).

The handler parameter `new_state: D.StateNew[states.SunState]` is a type annotation that tells Hassette: when this handler fires, pass in the new state as a `SunState` object. The bracket syntax works like `list[str]` in standard Python generics. `D.StateNew[T]` means "a new-state value, typed as `T`." Here is what the two imports do:

- **[`D`](../core-concepts/bus/dependency-injection.md)** is `hassette.event_handling.dependencies`, a module of type annotations. `D.StateNew[T]` means "give me the new state, converted to type `T`."
- **[`states`](../core-concepts/states/index.md#built-in-state-types)** is `hassette.models.states`, typed state classes for each HA domain. `states.SunState` has a `.value` attribute holding `"above_horizon"` or `"below_horizon"`.

This is a Hassette feature. Standard Python ignores type annotations at runtime, but Hassette inspects them to know what to pass into each handler. No event dict parsing needed. Your IDE knows the type, and Pyright (a Python type checker, optional but useful in VS Code) catches typos.

[`self.api.turn_on()`](../core-concepts/api/index.md) calls the `light.turn_on` service in Home Assistant, the same action as toggling a light from the HA UI. Hassette derives the service domain (`light`) from the `light.porch` entity ID automatically — no `domain=` parameter is needed. You can find available services in **Developer Tools → Services** in your Home Assistant instance.

## Schedule a Recurring Job

```python hl_lines="14 23 24"
--8<-- "pages/getting-started/snippets/first_automation_step4.py"
```

[`self.scheduler.run_minutely()`](../core-concepts/scheduler/methods.md) runs `log_heartbeat` every minute. The first run fires one minute after startup. Hassette tracks the job and cancels it automatically on shutdown.

`log_heartbeat` has no `D.*` annotations in its signature. Not every handler needs them. See [`Scheduler` Methods](../core-concepts/scheduler/methods.md) for `run_daily`, `run_cron`, `run_once`, and more.

## Run It

Replace your `apps/main.py` with the complete app from the previous snippet. Stop Hassette with `Ctrl+C` and run `hassette run -e .env` again. You see new log lines:

```
INFO hassette.MyApp.0 — Hello from Hassette!
INFO hassette.MyApp.0 — Heartbeat
```

The `Sun changed` and `Porch light turned on` lines appear at the next sunset. To test the handler now without waiting, trigger a state change manually:

1. In Home Assistant, go to **Settings → Developer Tools**.
2. Go to the **States** tab and find `sun.sun`.
3. Change the state value to `below_horizon` and click **Set State**.

The handler fires within milliseconds. You see `Sun changed: below_horizon` and `Porch light turned on` in the logs.

## Next Steps

- [`Bus` & Handlers](../core-concepts/bus/index.md): attribute changes, service calls, glob patterns, predicates, and conditions
- [Dependency Injection](../core-concepts/bus/dependency-injection.md): all the types you can extract into handler parameters
- [`Scheduler` Methods](../core-concepts/scheduler/methods.md): `run_daily`, `run_cron`, `run_once`, and jitter
- [Testing Your Apps](../testing/index.md): unit tests using `AppTestHarness`
- [Recipes](../recipes/index.md): complete worked examples for motion lights, presence detection, and more
- [Docker](docker/index.md): run Hassette in production as a container
