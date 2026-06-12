# Motion-Activated Lights

A motion sensor in the hallway fires every time someone walks past. The light should turn on immediately and stay on until motion has been clear for a set period. If someone walks past again while the timer is running, the timeout should restart instead of firing at the original time.

## The Code

```python
--8<-- "pages/recipes/snippets/motion_lights.py"
```

## Run It

Save the code as `motion_lights.py` in your apps directory and register it in `hassette.toml`:

```toml
[hassette.apps.motion_lights]
filename = "motion_lights.py"
class_name = "MotionLights"
```

The section name (`motion_lights`) is the app key the `hassette` CLI commands below take via `--app`. [App Configuration](../core-concepts/apps/configuration.md) covers registration in full.

## How It Works

`self.bus.on_state_change` subscribes to every state transition on the motion sensor. The `name=` parameter is required on all bus registrations — it identifies the listener in the database and in CLI output.

[`D.StateNew[states.BinarySensorState]`](../core-concepts/bus/dependency-injection.md) is a [dependency injection](../core-concepts/bus/dependency-injection.md) annotation — Hassette inspects the handler's parameter types at registration and passes the extracted value in automatically. `D.StateNew` delivers the new state, already converted to a [`BinarySensorState`](../core-concepts/states/index.md) object. `BinarySensorState.value` is `bool | None`: `True` when the sensor is on (motion detected), `False` when off (motion cleared), `None` when the state is unknown or unavailable — not the raw HA strings `"on"` and `"off"`. The handler covers both transitions in one place rather than two separate subscriptions.

When motion turns on, any pending off job is cancelled before the light turns on. This resets the timer. If motion fires again while the delay is running, the timeout starts over instead of firing at the original time.

When motion clears, `self.scheduler.run_in` schedules `turn_off_light` for `off_delay_seconds` seconds later. The returned [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob] handle exposes a `.cancel()` method — storing it on `self.off_job` lets the on-handler cancel the pending job on re-trigger.

`OFF_JOB_NAME` gives the scheduled job a stable name for log readability.

`motion_sensor`, `light`, and `off_delay_seconds` all come from config via [`hassette.toml`](../core-concepts/configuration/index.md). Nothing in the app is hardcoded to a specific room.

## Verify It's Working

Trigger your motion sensor (or toggle it manually in Home Assistant) and check the handler fired:

```
hassette log --app motion_lights --since 5m
```

Look for `on_motion` entries showing the state transition:

```
INFO  [motion_lights] on_motion triggered — new state: True
```

To verify the off timer, wait for the delay to elapse and confirm the light turns off:

```
hassette listener --app motion_lights
```

The `motion_sensor` listener should show an increasing invocation count each time motion fires.

## Variations

**Shorter or longer timeout.** Change `off_delay_seconds` in `hassette.toml` without touching the code:

```toml
[hassette.apps.hallway_motion]
filename = "motion_lights.py"
class_name = "MotionLights"

[hassette.apps.hallway_motion.config]
off_delay_seconds = 60
```

**Split handlers with `changed_to`.** `changed_to` is a filter on `on_state_change` — the handler fires only when the state becomes the specified value. When using `changed_to`, the handler does not need a state parameter since the filter already ensures which transition occurred:

```python
--8<-- "pages/recipes/snippets/motion_lights_split.py:split_handlers"
```

The trade-off: two subscriptions are easier to read individually, but the single-handler version keeps the on/off logic in one place where the relationship between them is visible.

## See Also

- [`Bus`](../core-concepts/bus/index.md): event subscriptions and rate control
- [`Scheduler`](../core-concepts/scheduler/index.md): `run_in` and job management
- [Application Configuration](../core-concepts/apps/configuration.md): per-instance config in `hassette.toml`
