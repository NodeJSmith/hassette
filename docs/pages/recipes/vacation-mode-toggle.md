# Vacation Mode Toggle

You're heading out for a week. You want lights to flicker on and off at odd hours so the house looks occupied. When you get back, flip a switch in Home Assistant and it stops. No code changes, no restart.

## The Code

```python
--8<-- "pages/recipes/snippets/vacation_mode.py"
```

## How It Works

Two `on_state_change` subscriptions watch the same `input_boolean`. The first fires when it turns `on`; the second fires when it turns `off`. Each handler does exactly one thing, so the two paths stay independent and easy to trace.

When vacation mode activates, `run_every` schedules `simulate_presence` to run on a fixed interval. The returned [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob] is stored on the instance so the stop handler can cancel it later.

Each tick, `simulate_presence` picks a random light from the configured list and reads its current state. If the light is on, it turns it off. If it is off, it turns it on. The random selection is what creates the irregular pattern. Toggling the same light at a fixed interval would look mechanical. Cycling through a random pick each time does not.

When vacation mode deactivates, the stored job is cancelled and all configured lights are turned off. Turning off the lights explicitly restores a known state. Without that step, whatever lights happened to be on at cancellation time would stay on.

Entity IDs and the interval come from `VacationModeConfig`. Adjusting the light list or simulation frequency is a config change in `hassette.toml`, not a code change.

## Verify It's Working

Toggle `input_boolean.vacation_mode` to on in the Home Assistant UI, then check the log:

```
hassette log --app <key> --since 5m
```

The app logs when vacation mode enables and each time a light toggles. To confirm the subscriptions registered:

```
hassette listener --app <key>
```

Both `vacation_start` and `vacation_end` listeners should appear with a non-zero invocation count after each toggle.

## Variations

**Provision the helper from code.** Instead of creating `input_boolean.vacation_mode` manually in the HA UI, call `api.create_input_boolean` in `on_initialize`. The helper is created on first run and left alone on subsequent starts. See [Managing Helpers](../core-concepts/api/managing-helpers.md) for the idempotent-bootstrap pattern.

**Schedule vacation windows.** Replace the manual toggle with `run_cron` entries that start and stop presence simulation at fixed times each day. Evening-only windows are one common pattern. See [`Scheduler` Methods](../core-concepts/scheduler/methods.md) for cron syntax.

## See Also

- [Managing Helpers](../core-concepts/api/managing-helpers.md). Create and manage `input_boolean` and other helper types from an app.
- [`Bus`](../core-concepts/bus/index.md). `on_state_change` filtering, debounce, and throttle options.
- [States](../core-concepts/states/index.md). Read entity state from the local cache without an API call.
