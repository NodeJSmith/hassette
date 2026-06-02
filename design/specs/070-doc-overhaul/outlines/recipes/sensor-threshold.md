# Recipes — Monitor Sensor Thresholds

**Status:** Exists (31 lines), needs JTBD redesign — "How It Works" uses bullet lists with bold lead-ins (anti-pattern)
**Voice mode:** Recipe — problem statement uses "you", "How It Works" uses system-as-subject prose paragraphs
**Page type:** Recipe
**Reader's job:** Get a notification when a sensor value crosses a configured limit, without alert spam when the value hovers near the boundary.

## What was cut

The existing "How It Works" uses bold-label bullet lists. The content is good
but the format must change to flowing prose paragraphs with system-as-subject
voice.

The existing page does not have a "Verify It's Working" section. Adding one.

## Outline

### H2: (Problem statement)
You want a notification when temperature rises above a limit — or when any
numeric sensor crosses a threshold. One alert per crossing, not a flood while
the value stays high.

### H2: The Code
Full app via `--8<--` include of `sensor_threshold.py`.

### H2: How It Works
Flowing prose paragraphs, one decision each:

1. Config — `ThresholdConfig` exposes `entity_id`, `threshold`, and
   `notify_target` as environment-backed settings. Override per-instance
   without touching code.
2. Threshold filter — `C.Comparison("gt", threshold)` passed to `changed_to`
   drops events below the limit before the handler runs. The handler fires only
   on crossings, not every reading.
3. DI extraction — `D.StateNew[states.SensorState]` gives a typed state object.
   `D.EntityId` provides the entity ID as a plain string for the notification.
4. Notification — `api.call_service("notify", ...)` sends the alert via any
   HA notify target. Attributes like `unit_of_measurement` and `friendly_name`
   come from the typed model.

### H2: Verify It's Working
`hassette listener --app <key>` to confirm the handler is registered with the
threshold condition. `hassette log --app <key> --since 1h` after a threshold
crossing to see the notification fire. Expected: one log entry per crossing.

### H2: Variations
- Below-limit alert: change `"gt"` to `"lt"` for battery or pressure sensors.
- Hysteresis: second listener with `C.Comparison("le", threshold)` that sets a
  recovery flag, preventing repeated alerts while hovering.
- Multiple sensors: glob pattern (`"sensor.temp_*"`) or loop over a config list.

### H2: See Also
Links to Filtering (conditions), DI, States (typed models).

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `sensor_threshold.py` | Keep | Review for voice alignment |

## Cross-Links

- **Links to:** Bus/Filtering (C.Comparison, conditions), Bus/DI (D.StateNew, D.EntityId), States overview
- **Linked from:** Recipes overview
