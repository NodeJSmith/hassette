# Vacation Mode Toggle

You're heading out for a week. You want lights to flicker on and off at odd hours so the house looks occupied. When you get back, flip a switch in Home Assistant and it stops. No code changes, no restart.

## The Code

```python
--8<-- "pages/recipes/snippets/vacation_mode.py"
```

## Run It

This recipe needs an `input_boolean` helper named `vacation_mode` — create one in HA under **Settings → Devices & Services → Helpers → Create Helper → Toggle**. Then save the code as `vacation_mode.py` in your apps directory and register it in `hassette.toml`:

```toml
[hassette.apps.vacation_mode]
filename = "vacation_mode.py"
class_name = "VacationMode"
```

The section name (`vacation_mode`) is the app key the `hassette` CLI commands below take via `--app`. [App Configuration](../core-concepts/apps/configuration.md) covers registration in full.

## How It Works

Every `App` instance carries `self.bus` (delivers HA events to handlers), `self.scheduler` (runs functions on a schedule), `self.api` (calls HA services), and `self.app_config` (the validated config) — Hassette provides them at startup. Handlers are `async def`; Hassette runs the event loop.

Two `on_state_change` subscriptions watch the same `input_boolean`. `changed_to` filters each subscription to one transition: `"on"` or `"off"`. Each handler does exactly one thing, so the two paths stay independent and easy to trace. `name=` on each subscription is required — it labels the listener in logs and in `hassette listener` output; omitting it raises `ListenerNameRequiredError` at registration time.

When vacation mode activates, `run_every` schedules `simulate_presence` to run on a fixed interval. `run_every` returns a [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob] — a handle for the running job. It is stored on the instance so `on_vacation_end` can cancel it later. The class-level `presence_job: ScheduledJob | None = None` line declares and defaults that attribute; it is a type annotation, not framework boilerplate.

Each tick, `simulate_presence` picks a random light from the configured list and reads its current state via `self.api.get_state`. Hassette converts light state to a `bool`: `.value` is `True` for on and `False` for off — not the raw HA strings `"on"` and `"off"`, so `state.value == "on"` never matches. If the light is on, it turns it off. If it is off, it turns it on. The random selection is what creates the irregular pattern. Toggling the same light at a fixed interval would look mechanical. Cycling through a random pick each time does not.

When vacation mode deactivates, the stored job is cancelled and all configured lights are turned off. Turning off the lights explicitly restores a known state. Without that step, whatever lights happened to be on at cancellation time would stay on.

Entity IDs and the interval come from `VacationModeConfig`. Adjusting the light list or simulation frequency is a config change in `hassette.toml`, not a code change.

## Verify It's Working

Run these from your project directory while Hassette is running. Toggle `input_boolean.vacation_mode` to on in the Home Assistant UI, then check the log:

```
hassette log --app vacation_mode --since 5m
```

The app logs when vacation mode enables and each time a light toggles. To confirm the subscriptions registered, toggle the boolean on and then off again, then run:

```
hassette listener --app vacation_mode
```

Both `vacation_start` and `vacation_end` listeners should appear with an invocation count of 1 or higher.

## Variations

**Provision the helper from code.** Instead of creating `input_boolean.vacation_mode` manually in the HA UI, call `self.api.create_input_boolean` in `on_initialize`. The helper is created on first run and left alone on subsequent starts — see [Managing Helpers](../core-concepts/api/managing-helpers.md) for the pattern.

**Schedule vacation windows.** Replace the manual toggle with `run_cron` entries that start and stop presence simulation at fixed times each day. Evening-only windows are one common pattern. See [`Scheduler` Methods](../core-concepts/scheduler/methods.md) for cron syntax.

## See Also

- [Managing Helpers](../core-concepts/api/managing-helpers.md). Create and manage `input_boolean` and other helper types from an app.
- [`Bus`](../core-concepts/bus/index.md). `on_state_change` filtering, debounce, and throttle options.
- [States](../core-concepts/states/index.md). Read entity state from the local cache without an API call.
