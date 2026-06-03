# Motion-Activated Lights

A motion sensor in the hallway fires every time someone walks past. The light should turn on immediately and stay on until motion has been clear for a set period. If someone walks past again while the timer is running, the timeout should restart instead of firing at the original time.

## The Code

```python
--8<-- "pages/recipes/snippets/motion_lights.py"
```

## How It Works

`on_state_change` subscribes to every state transition on the motion sensor. [`D.StateNew[states.BinarySensorState]`](../core-concepts/bus/dependency-injection.md) delivers the new state as a typed object from [`hassette.models.states`](../core-concepts/states/index.md) — the handler covers both `True` and `False` transitions in one place rather than two separate subscriptions.

When motion turns on, any pending off job is cancelled before the light turns on. This resets the timer — if motion fires again while the delay is running, the timeout starts over instead of firing at the original time.

When motion clears, `run_in` schedules `turn_off_light` for `off_delay_seconds` seconds later. The returned [`ScheduledJob`][hassette.scheduler.classes.ScheduledJob] is stored on `self.off_job` so the on-handler can cancel it on re-trigger.

`OFF_JOB_NAME` gives the scheduled job a stable name for log readability and deduplication.

`motion_sensor`, `light`, and `off_delay_seconds` all come from config. Nothing in the app is hardcoded to a specific room.

## Verify It's Working

Trigger your motion sensor (or toggle it manually in Home Assistant) and check the handler fired:

```
hassette log --app motion_lights --since 5m
```

Look for `on_motion` entries showing the state transition. To verify the off timer, wait for the delay to elapse and confirm the light turns off:

```
hassette listener --app motion_lights
```

The `motion_sensor` listener should show an increasing invocation count each time motion fires.

## Variations

**Shorter or longer timeout** — change `off_delay_seconds` in `hassette.toml` without touching the code:

```toml
[apps.hallway_motion]
module = "motion_lights"
class = "MotionLights"
off_delay_seconds = 60
```

**Split handlers with `changed_to`** — instead of one handler that branches on the state value, two handlers with `changed_to` predicates each do one thing:

```python
--8<-- "pages/recipes/snippets/motion_lights_split.py:split_handlers"
```

The trade-off: two subscriptions are easier to read individually, but the single-handler version keeps the on/off logic in one place where the relationship between them is visible.

## See Also

- [`Bus`](../core-concepts/bus/index.md) — event subscriptions and rate control
- [`Scheduler`](../core-concepts/scheduler/index.md) — `run_in` and job management
- [Application Configuration](../core-concepts/apps/configuration.md) — per-instance config in `hassette.toml`
