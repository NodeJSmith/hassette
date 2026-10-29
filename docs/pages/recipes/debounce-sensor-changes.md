# Debounce Sensor Changes

An outdoor temperature sensor reports a reading every few seconds. On a warm afternoon, it may emit a dozen near-identical values before settling. Reacting to each one produces redundant log entries and wasted service calls. This recipe acts on rising temperatures only, and waits until the rises stop for a set period before acting.

## The Code

```python
--8<-- "pages/recipes/snippets/debounce_sensor.py"
```

## Run It

Save the code as `debounce_sensor.py` in your apps directory and register it in `hassette.toml`:

```toml
[hassette.apps.debounce_sensor]
filename = "debounce_sensor.py"
class_name = "DebounceSensorApp"
config = { instance_name = "debounce_sensor" }
```

The section name (`debounce_sensor`) is the app key the `hassette` CLI commands below take via `--app`. [App Configuration](../core-concepts/apps/configuration.md) covers registration in full.

## How It Works

The bus (`self.bus`) delivers Home Assistant events to subscribed handlers — every `App` gets one, alongside `self.api` and `self.logger`. Handlers are `async def`; Hassette runs the event loop.

`debounce=10.0` tells the bus to hold the handler until 10 seconds pass with no new rising reading. Each rising reading during that window resets the timer. The handler fires once, with the last rising reading, when the rises stop.

`changed=C.Increased()` gates which events start the debounce timer in the first place. `C` is an alias for [`hassette.event_handling.conditions`](../core-concepts/bus/filtering.md), a module of ready-made value checks. `C.Increased()` passes only when the new state value is numerically greater than the old one. Drops and unchanged readings never reach the debounce timer, so they neither start nor reset it. A drop during the window doesn't cancel the pending call: the handler still fires with the last rising reading, even if the sensor has since fallen. To act only on a value that has held steady, use `duration=` on `on_state_change` together with a condition the new state must keep satisfying, such as `changed_to=` or a `where=` predicate. Comparison conditions like `C.Increased()` only gate the event that starts the wait, so a drop doesn't cancel it.

`D.StateNew[states.SensorState]` is a [dependency injection](../core-concepts/bus/dependency-injection.md) annotation. `D` is an alias for `hassette.event_handling.dependencies` — Hassette inspects the handler's parameter types at registration and passes the extracted value in automatically. `D.StateNew` delivers the new state, already converted to a [`SensorState`][hassette.models.states.sensor.SensorState] object. `SensorState.value` is `str | None` — the framework sets it to `None` when the entity is `"unavailable"` or `"unknown"` — so the handler converts it to a `float` before comparing against `THRESHOLD`. The `try`/`except` guards against the `None` and non-numeric values that HA sensors report during startup.

`name=` on `on_state_change` is required — it labels the listener in logs and in `hassette listener` output. Omitting it raises `TypeError` at registration time.

When that last rising reading meets or exceeds `THRESHOLD`, a log line records the new value, the previous value, and the debounce duration.

`THRESHOLD`, `DEBOUNCE_SECONDS`, and the entity ID are module-level constants. Promoting them to typed fields on an [`AppConfig`][hassette.app.app_config.AppConfig] subclass — set per instance in `hassette.toml` — covers multiple sensors with a single class.

## Verify It's Working

Run these from your project directory while Hassette is running. Confirm the handler registered after startup:

```
hassette listener --app debounce_sensor
```

Expected output shows one listener named `outdoor_temp_debounced` with `debounce=10.0` and `changed=Increased`.

After a burst of rising readings ends at or above `THRESHOLD` and 10 seconds of quiet pass, check invocations:

```
hassette log --app debounce_sensor --since 5m
```

The log shows one entry per burst of rising readings, not one per raw sensor event. If the sensor rose three times in quick succession, only the last of those rising values appears. A burst that tops out below 25°C logs nothing, even though the debounce fired. If your sensor won't reach 25°C while you test, lower `THRESHOLD` temporarily.

## Variations

**Throttle instead of debounce.** Pass `throttle=30.0` to `on_state_change` in place of `debounce=` — it fires on the first matching event and suppresses the rest for 30 seconds. Debounce waits for quiet; throttle fires immediately then goes silent. The two parameters are mutually exclusive: passing both raises a `ValueError` at registration time.

**Different sensor types.** Swap `sensor.outdoor_temperature` for any numeric sensor and adjust `THRESHOLD` to match the units. Humidity (`sensor.living_room_humidity`), CO₂ (`sensor.co2_level`), and power draw (`sensor.solar_inverter_power`) all work the same way.

## See Also

- [`Bus` Overview](../core-concepts/bus/index.md). `Subscription` model and available methods.
- [Filtering](../core-concepts/bus/filtering.md). Full reference for `changed`, `C.Increased`, debounce, and throttle.
