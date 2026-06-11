# Monitor Sensor Thresholds

Temperature spikes, humidity creeps, CO2 builds up. Numeric sensors in Home Assistant report values continuously. You want a notification when a value crosses a limit, but only once per crossing. Not a flood while the value stays high.

## The Code

```python
--8<-- "pages/recipes/snippets/sensor_threshold.py"
```

## Run It

Save the code as `sensor_threshold.py` in your apps directory and register it in `hassette.toml`, overriding any config defaults in the `.config` block:

```toml
[hassette.apps.sensor_threshold]
filename = "sensor_threshold.py"
class_name = "SensorThresholdApp"

[hassette.apps.sensor_threshold.config]
entity_id = "sensor.living_room_temperature"
threshold = 28.0
```

The section name (`sensor_threshold`) is the app key the `hassette` CLI commands below take via `--app`. [App Configuration](../core-concepts/apps/configuration.md) covers registration in full.

## How It Works

Every `App` instance carries `self.bus` (delivers HA events to handlers), `self.api` (calls HA services), and `self.app_config` (the validated config) — Hassette provides them at startup. Handlers are `async def`; Hassette runs the event loop.

`ThresholdConfig` exposes `entity_id`, `threshold`, and `notify_target` as settings. Each instance reads its own values from `hassette.toml`. The same app class watches different sensors in different rooms without code changes.

`C.Comparison("gt", threshold)` passed to `changed_to` and `C.Comparison("le", threshold)` passed to `changed_from` form a gate pair. `C` is an alias for [`hassette.event_handling.conditions`](../core-concepts/bus/filtering.md), a module of value-comparison functions. The bus evaluates both conditions before invoking the handler. HA delivers state values as strings, so numeric comparisons coerce the value to a float first; values that can't convert (like `"unavailable"`) evaluate to `False` and are dropped. The pair makes the handler fire only on the crossing itself — the old value at or below the threshold, the new value above it — not on every subsequent reading above the limit.

`D` is an alias for [`hassette.event_handling.dependencies`](../core-concepts/bus/dependency-injection.md) — Hassette inspects handler parameter types at registration and passes the extracted values in automatically. `D.StateNew[states.SensorState]` delivers the new state as a typed object. `SensorState.value` is `str | None` — `None` when the entity is unavailable or unknown, though those events never pass the comparison gate; the typed model provides `.attributes` with fields like `unit_of_measurement` and `friendly_name`. `D.EntityId` delivers the entity ID as a plain string. The handler declares what it needs, and the framework fills it in.

`name=` on `on_state_change` is required — it labels the listener in logs and in `hassette listener` output. Omitting it raises `ListenerNameRequiredError` at registration time.

`self.api.call_service("notify", ...)` sends the alert. `new_state.attributes.unit_of_measurement` and `new_state.attributes.friendly_name` come directly from the typed model, so the message reads naturally without manual attribute dict lookups.

## Verify It's Working

Run these from your project directory while Hassette is running. Check that the handler registered with the threshold condition:

```
hassette listener --app sensor_threshold
```

Expected output shows one listener named `threshold_monitor` with the `> 28.0` condition.

To force a crossing without waiting for the real sensor, set the value by hand in HA under **Developer Tools → States**. Then confirm the handler fired:

```
hassette log --app sensor_threshold --since 1h
```

The log shows the warning line with the sensor name, value, and unit.

## Variations

**Below-limit alert.** Change `"gt"` to `"lt"` to alert when a value drops below the threshold. Battery level and water pressure are natural fits. Alert when either falls too low.

**Alert once until recovery (hysteresis).** A second listener with `changed_to=C.Comparison("le", threshold)` fires when the sensor recovers back to or below the limit. Store a flag on `self` when recovery fires, and check it in `on_threshold_exceeded` before sending. The notification skips if the sensor has not yet cleared since the last alert.

**Multiple sensors.** Pass a glob pattern like `"sensor.temp_*"` to `on_state_change` to cover a group of sensors with one registration. Alternatively, loop over a `list[str]` config field and call `on_state_change` once per entity. `D.EntityId` in the handler identifies which sensor triggered each alert.

## See Also

- [Filtering](../core-concepts/bus/filtering.md). Full reference for `C.Comparison` and all other conditions.
- [Dependency Injection](../core-concepts/bus/dependency-injection.md). How `D.StateNew` and `D.EntityId` work.
- [States](../core-concepts/states/index.md). Typed state models and the [`SensorState`][hassette.models.states.sensor.SensorState] attributes.
