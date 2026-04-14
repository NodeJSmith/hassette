# Vacation Mode Toggle

Watch an `input_boolean` helper in Home Assistant and use its state to start and stop a presence-simulation loop — no redeployment needed to toggle the behavior.

## The Code

```python
--8<-- "pages/recipes/snippets/vacation_mode.py"
```

## How It Works

- Two `on_state_change` subscriptions watch `input_boolean.vacation_mode` — one fires when it turns `on`, the other when it turns `off`.
- When vacation mode turns on, `run_every` schedules `simulate_presence` to run on a fixed interval, and the returned `ScheduledJob` is stored on the instance.
- Each tick, `simulate_presence` picks a random light and toggles it — on if currently off, off if currently on — to create irregular activity.
- When vacation mode turns off, the stored job is cancelled and all lights are turned off to restore a clean state.
- The entity IDs and interval are configurable through `VacationModeConfig`, so you can adjust the light list and simulation frequency without touching the code.

## Variations

**Provision the helper from code** — instead of creating `input_boolean.vacation_mode` manually in the HA UI, use `api.create_input_boolean` in `on_initialize` to provision it automatically on first run. See [Managing Helpers](../advanced/managing-helpers.md) for the idempotent-bootstrap pattern.

**Schedule vacation windows** — replace the manual toggle with `run_cron` entries that enable and disable presence simulation at fixed times each day (e.g., evening hours only). See [Scheduler Methods](../core-concepts/scheduler/methods.md) for cron syntax.

## See Also

- [Managing Helpers](../advanced/managing-helpers.md) — create and manage `input_boolean` and other helper types from your app
- [Bus](../core-concepts/bus/index.md) — `on_state_change` filtering, debounce, and throttle options
- [States](../core-concepts/states/index.md) — read entity state from the local cache without an API call
