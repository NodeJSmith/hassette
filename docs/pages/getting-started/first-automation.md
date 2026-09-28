# Your First Automation

This page adds two features to the app from the [Quickstart](index.md):

- **A sunset handler** that turns on a light when the sun sets, with typed state data filled in automatically
- **A heartbeat job** that logs every minute

## Subscribe to a State Change

This first snippet shows only the sunset handler, so each piece can be explained on its own. You don't need to run it yet: the [next section](#schedule-a-recurring-job) adds the heartbeat job, and [Run It](#run-it) uses that combined version.

```python hl_lines="1 11 12 13 15 16 17 18 19 20"
--8<-- "pages/getting-started/snippets/first_automation_step3.py"
```

[`self.bus.on_state_change()`](../core-concepts/bus/index.md) registers a *handler* (a method Hassette calls for you when an event arrives, here `on_sun_change`) that fires whenever an entity's state changes, like a light switching on or a sensor reporting a new reading. `"sun.*"` is a glob pattern that matches any entity in the `sun` domain. In practice, that's `sun.sun`. The `name=` parameter labels this handler in logs and the [web UI](../web-ui/index.md) (a monitoring dashboard Hassette includes).

The handler parameter `new_state: D.StateNew[states.SunState]` is a type annotation that tells Hassette: when this handler fires, pass in the new state as a `SunState` object. The bracket syntax works like `list[str]` in standard Python generics. `D.StateNew[T]` means "a new-state value, typed as `T`." Here is what the two imports do:

- **[`D`](../core-concepts/bus/dependency-injection.md)** is `hassette.event_handling.dependencies`, a module of type annotations. `D.StateNew[T]` means "give me the new state, converted to type `T`."
- **[`states`](../core-concepts/states/index.md#built-in-state-types)** is `hassette.models.states`, typed state classes for each HA domain. `states.SunState` has a `.value` attribute holding `"above_horizon"` or `"below_horizon"`.

This is a Hassette feature. Standard Python ignores type annotations at runtime, but Hassette inspects them to know what to pass into each handler. The handler receives the new state as a parameter and Hassette fills it in for you. This is called *dependency injection*. No event dict parsing needed. Your IDE knows the type, and Pyright (a Python type checker, optional but useful in VS Code) catches typos.

[`self.api.turn_on()`](../core-concepts/api/index.md) calls the `light.turn_on` service in Home Assistant, the same action as toggling a light from the HA UI. Hassette derives the service domain (`light`) from the `light.porch` entity ID automatically — no `domain=` parameter is needed. `light.porch` is an example: replace it with the entity ID of a light in your own Home Assistant instance. You can find available services in **Developer Tools → Services** in your Home Assistant instance.

Handlers are `async def` because Hassette runs them all on its event loop. While one handler waits on an `await` (such as `self.api.turn_on()` waiting for Home Assistant to respond), other handlers keep running, so a slow call in one handler doesn't hold up the rest of your app.

## Schedule a Recurring Job

```python hl_lines="14 23 24"
--8<-- "pages/getting-started/snippets/first_automation_step4.py"
```

[`self.scheduler.run_minutely()`](../core-concepts/scheduler/methods.md) runs `log_heartbeat` every minute. `log_heartbeat` is a scheduled *job*: a method the scheduler calls on a timer, rather than a handler the bus calls in response to an event. The first run fires one minute after startup. Hassette tracks the job and cancels it automatically on shutdown.

`log_heartbeat` has no `D.*` annotations in its signature, because there is no event to extract data from. See [`Scheduler` Methods](../core-concepts/scheduler/methods.md) for `run_daily`, `run_cron`, `run_once`, and more.

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
