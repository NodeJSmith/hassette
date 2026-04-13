# Monitor Sensor Thresholds

Send a notification whenever a sensor value rises above a configured limit — useful for temperature, humidity, CO2, or any numeric sensor in Home Assistant.

## The code

```python
--8<-- "pages/recipes/snippets/sensor_threshold.py"
```

## How it works

- **Typed config** — `ThresholdConfig` exposes `entity_id`, `threshold`, and `notify_target` as environment-backed settings. Override any of them per-instance without touching the code.
- **Threshold filter** — `C.Comparison("gt", threshold)` is passed to `changed_to`, so the handler only fires when the new state value is greater than the configured limit. Events below the threshold are dropped before the handler runs.
- **DI extraction** — `D.StateNew[states.SensorState]` gives a typed state object. `D.EntityId` provides the entity ID as a plain string for logging.
- **Attributes** — `new_state.attributes.unit_of_measurement` and `friendly_name` are read directly from the typed model, keeping the notification message readable without manual string parsing.
- **Notification** — `api.call_service("notify", ...)` sends the alert via any Home Assistant notify target (mobile app, persistent notification, etc.).

## Variations

**Lower threshold (below-limit alert):** Change `"gt"` to `"lt"` to alert when the value drops below the limit — for example, alerting when battery level or water pressure falls too low.

**Hysteresis to prevent alert storms:** Subscribe to a second listener with `changed_to=C.Comparison("le", threshold)` that sets a flag when the sensor recovers. Check the flag in `on_threshold_exceeded` and skip the notification if the sensor has not yet recovered, preventing repeated alerts while the value hovers near the threshold.

**Multiple sensors:** Register the same handler for several entities using a glob pattern (`"sensor.temp_*"`) or call `on_state_change` once per entity inside a loop over a `list[str]` config field.

## See also

- [Filtering](../core-concepts/bus/filtering.md) — full reference for `C.Comparison` and all other conditions
- [Dependency Injection](../core-concepts/bus/dependency-injection.md) — how `D.StateNew` and `D.EntityId` work
- [States](../core-concepts/states/index.md) — typed state models and the `SensorState` attributes
