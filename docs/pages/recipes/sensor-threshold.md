# Monitor Sensor Thresholds

Temperature spikes, humidity creeps, CO2 builds up. Numeric sensors in Home Assistant report values continuously. You want a notification when a value crosses a limit, but only once per crossing. Not a flood while the value stays high.

## The Code

```python
--8<-- "pages/recipes/snippets/sensor_threshold.py"
```

## How It Works

`ThresholdConfig` exposes `entity_id`, `threshold`, and `notify_target` as settings. Each instance reads its own values from `hassette.toml`. The same app class watches different sensors in different rooms without code changes.

`C.Comparison("gt", threshold)` passed to `changed_to` acts as a gate. `C` is an alias for [`hassette.event_handling.conditions`](../core-concepts/bus/filtering.md), a module of value-comparison functions. The bus evaluates the condition before invoking the handler. Events where the new state value is not greater than the threshold are dropped. The handler fires only on the crossing itself, not on every subsequent reading above the limit.

`D` is an alias for [`hassette.event_handling.dependencies`](../core-concepts/bus/dependency-injection.md), a module of type annotations that tell Hassette what to extract from each event. `D.StateNew[states.`SensorState`]` delivers the new state as a typed object. `D.EntityId` delivers the entity ID as a plain string. Hassette resolves both from the event automatically. The handler declares what it needs, and the framework fills it in.

`api.call_service("notify", ...)` sends the alert. `new_state.attributes.unit_of_measurement` and `new_state.attributes.friendly_name` come directly from the typed model, so the message reads naturally without manual attribute dict lookups.

## Verify It's Working

Check that the handler registered with the threshold condition:

```
hassette listener --app <key>
```

After a threshold crossing, confirm the handler fired:

```
hassette log --app <key> --since 1h
```

The log shows the warning line with the sensor name, value, and unit.

## Variations

**Below-limit alert.** Change `"gt"` to `"lt"` to alert when a value drops below the threshold. Battery level and water pressure are natural fits. Alert when either falls too low.

**Hysteresis.** A second listener with `changed_to=C.Comparison("le", threshold)` fires when the sensor recovers back to or below the limit. Store a flag on `self` when recovery fires, and check it in `on_threshold_exceeded` before sending. The notification skips if the sensor has not yet cleared since the last alert.

**Multiple sensors.** Pass a glob pattern like `"sensor.temp_*"` to `on_state_change` to cover a group of sensors with one registration. Alternatively, loop over a `list[str]` config field and call `on_state_change` once per entity. `D.EntityId` in the handler identifies which sensor triggered each alert.

## See Also

- [Filtering](../core-concepts/bus/filtering.md). Full reference for `C.Comparison` and all other conditions.
- [Dependency Injection](../core-concepts/bus/dependency-injection.md). How `D.StateNew` and `D.EntityId` work.
- [States](../core-concepts/states/index.md). Typed state models and the [`SensorState`][hassette.models.states.sensor.`SensorState`] attributes.
