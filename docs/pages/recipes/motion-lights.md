# Motion-Activated Lights

Turns a light on when a motion sensor detects movement, then turns it off automatically after a configurable delay once motion clears.

## The Code

```python
--8<-- "pages/recipes/snippets/motion_lights.py"
```

## How It Works

- **`on_state_change`** subscribes to every state transition on the motion sensor. The handler receives the raw event so both `"on"` and `"off"` states are handled in one place.
- When state is `"on"`, any pending off job is cancelled before turning the light on — this resets the timeout if motion is detected again while the timer is running.
- When state is `"off"`, `run_in` schedules `turn_off_light` to fire 5 minutes later. The job is stored on `self._off_job` so it can be cancelled on re-trigger.
- **Named job** (`OFF_JOB_NAME`) keeps logs readable. Only one off job per app instance can exist with a given name — if you need multiple sensors driving the same light, give each instance a different name via config.
- Config fields (`motion_sensor`, `light`, `off_delay`) let you run the same app class for multiple rooms with different values in `hassette.toml`.

## Variations

**Shorter or longer timeout** — Change `off_delay` in `hassette.toml` without touching the code:

```toml
[apps.hallway_motion]
module = "motion_lights"
class = "MotionLights"
off_delay = 60  # 1 minute
```

**Multiple sensors, one light** — Deploy the app twice under different names, each pointing to its own sensor. The shared `light` entity is fine; whichever sensor detects motion last wins.

## See Also

- [Bus: State Change Subscriptions](../core-concepts/bus/index.md)
- [Scheduler: `run_in` and Job Management](../core-concepts/scheduler/management.md)
- [Application Configuration](../core-concepts/configuration/applications.md)
