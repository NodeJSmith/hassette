# Debounce Sensor Changes

Sensors like temperature or humidity often emit bursts of near-identical readings. This recipe waits until a value has been stable for a set period before reacting, and only fires when the temperature has increased and crossed a threshold.

## The Code

```python
--8<-- "pages/recipes/snippets/debounce_sensor.py"
```

## How It Works

- **`debounce=10.0`** — the handler is not called until the sensor has been quiet for 10 seconds. Any new event during that window resets the timer, so rapid fluctuations are silently discarded.
- **`changed=C.Increased()`** — the debounce timer only starts for events where the new value is numerically greater than the old one. Decreases and unchanged readings never queue the handler.
- The handler uses **dependency injection** (`D.StateNew[states.SensorState]`) to receive the new state as a typed object. The value is converted to a float before comparing to `THRESHOLD`.
- When the temperature is at or above the threshold after stabilising, a single log line is emitted.
- Adjust `THRESHOLD`, `DEBOUNCE_SECONDS`, and the entity ID for your sensor.

## Variations

**Use throttle instead of debounce.** If you want to log at most once every 30 seconds regardless of how many events arrive, replace `debounce=10.0` with `throttle=30.0`. Throttle fires on the first event and then suppresses the rest for the window; debounce waits for a quiet period before firing.

**Watch a different sensor.** Swap `"sensor.outdoor_temperature"` for any numeric sensor — humidity (`sensor.living_room_humidity`), CO₂ (`sensor.co2_level`), or power draw (`sensor.solar_inverter_power`). Adjust `THRESHOLD` to match the units.

## See Also

- [Bus Overview](../core-concepts/bus/index.md) — how subscriptions work and what methods are available.
- [Filtering & Advanced Subscriptions](../core-concepts/bus/filtering.md) — full reference for `changed`, `C.Increased`, and other conditions.
