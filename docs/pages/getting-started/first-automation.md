# Your First Automation

**What you'll build**: An automation that logs a heartbeat every minute and turns on a light at sunset.

**What you'll learn**:

- How an `App` class is structured
- Why config is declared as a typed `AppConfig` subclass
- How to subscribe to events with `self.bus`
- How to schedule recurring tasks with `self.scheduler`
- How to call a Home Assistant service with `self.api`

**Prerequisites**: You've completed the [Quickstart guide](index.md) and have Hassette running.

---

## Step 1: Understand the App class

Every Hassette automation is a Python class that extends `App`. Hassette calls `on_initialize()` when the app starts — this is where you register event handlers and schedule jobs. You don't call any setup yourself; you declare what you want, and Hassette wires it up.

```python
--8<-- "pages/getting-started/snippets/first_automation_step1.py"
```

`on_initialize` is `async` because Hassette is built on `asyncio`. Your handlers can `await` API calls or other coroutines.

## Step 2: Add typed configuration

Rather than reading config from a dict (like `self.args["key"]`), Hassette uses a Pydantic model. Declare a class that extends `AppConfig` with the fields you want:

```python
--8<-- "pages/getting-started/snippets/first_automation_step2.py"
```

`App[MyAppConfig]` is a generic that tells Hassette which config class to use. Hassette validates the config at startup — a missing required field raises a clear error before any of your code runs.

`self.app_config.greeting` is typed: your IDE knows it's a `str`, and Pyright will catch typos.

## Step 3: Subscribe to a state change

Use `self.bus.on_state_change()` to react to HA state changes. The `"sun.*"` pattern matches any entity in the `sun` domain (typically `sun.sun`).

The Quickstart used a raw event handler — that works, but Hassette can do better. With **dependency injection** (DI), you annotate handler parameters with types like `D.StateNew[T]`, and Hassette extracts and converts the data automatically — no event payload parsing required:

```python
--8<-- "pages/getting-started/snippets/first_automation_step3.py"
```

Two names appear here that aren't obvious at first glance:

- **`D`** is a short alias for `hassette.dependencies` — a module containing type annotations that tell Hassette what to extract from each event and inject into your handler parameters.
- **`states`** is the `hassette.models.states` module — it contains typed state classes for each Home Assistant domain (`SunState`, `LightState`, `BinarySensorState`, and [many others](../core-concepts/states/index.md#built-in-state-types)).

So `D.StateNew[states.SunState]` means: *extract the new state from this event and give it to me already converted to a `SunState` object*. The `.value` attribute holds the state string (`"above_horizon"` or `"below_horizon"`). Your IDE knows the type; Pyright will catch typos.

`self.api.turn_on()` calls the HA service. The `domain="light"` argument routes it to `light.turn_on` instead of the generic `homeassistant.turn_on`. Use the entity's domain as the `domain=` value — e.g., `domain="switch"` for switch entities, `domain="input_boolean"` for input booleans.

??? note "Raw event form (verbose alternative)"
    You can also receive the full untyped event object. Use this form when you need access to additional event data beyond the new state value:

    ```python
    --8<-- "pages/getting-started/snippets/first_automation_step3_raw.py:raw_handler"
    ```

    Note that raw state dicts use `new_state["state"]` (the key Home Assistant uses in its event payload), while typed state objects use `.value`.

## Step 4: Schedule a recurring job

Use `self.scheduler.run_minutely()` to run a handler every minute:

```python
--8<-- "pages/getting-started/snippets/first_automation_step4.py"
```

The first run fires one minute after Hassette starts (the default interval for `run_minutely`).

## Step 5: Run it

With this code in place as `hassette_apps/main.py`, start Hassette:

```bash
uv run hassette
```

You should see output like:

```
INFO hassette ... — Connected to Home Assistant
INFO hassette.MyApp.0 ... — This is from the config file!
INFO hassette.MyApp.0 ... — Heartbeat
```

Lines for `Sun changed` and `Porch light turned on` appear only at sunset.

!!! tip "Testing the sunset handler"
    The `on_sun_change` handler reacts to state transitions — it won't fire just because the sun is already below the horizon when Hassette starts. To test it without waiting for actual sunset, temporarily use `self.bus.on_state_change("sun.sun", ...)` and manually call `hass.states.set("sun.sun", "below_horizon")` from the Developer Tools in Home Assistant.

## What you just built

- **Typed config**: `MyAppConfig` declares the `greeting` field with a default. Hassette validates it at startup.
- **Event subscription**: `on_sun_change` fires every time the `sun.*` state changes. Dependency injection (`D.StateNew[states.SunState]`) delivers a typed state object — no event payload parsing. You didn't write any polling loop. See the [built-in state types](../core-concepts/states/index.md#built-in-state-types) for all available classes.
- **Scheduled job**: `log_heartbeat` runs every 60 seconds. Hassette tracks the job and cancels it automatically when the app shuts down.
- **API call**: `self.api.turn_on()` calls a HA service without you managing HTTP sessions or WebSocket framing.

## Next steps

- **[Bus & Handlers](../core-concepts/bus/index.md)** — learn the full range of subscription options (attribute changes, service calls, glob patterns, predicates)
- **[Dependency Injection](../core-concepts/bus/dependency-injection.md)** — extract typed state objects directly into handler parameters instead of parsing event dicts
- **[Testing Your Apps](../testing/index.md)** — write unit tests for this automation using `AppTestHarness`
- **[Scheduler Methods](../core-concepts/scheduler/methods.md)** — `run_daily`, `run_cron`, `run_once`, and more
- **[Application Configuration](../core-concepts/configuration/applications.md)** — load multiple apps, run the same app with different config, or disable apps without deleting code

---

You now have the essentials: a typed app class, config, event subscriptions, and scheduled jobs. Everything beyond this point adds depth — stronger filtering, richer injection types, testing, advanced scheduling — but you can build real automations with what you've just learned.
