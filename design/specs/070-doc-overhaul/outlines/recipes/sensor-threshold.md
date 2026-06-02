# Recipes — Monitor Sensor Thresholds

**Status:** Exists (31 lines), follows recipe template, voice polish needed
**Voice mode:** Recipe — problem statement, code, How It Works, variations

## Outline

### H2: (Problem Statement)
Take action when a sensor crosses a threshold (temperature above 80°F, humidity below 30%).

### H2: The Code
App with `on_state_change` + numeric condition or predicate.

### H2: How It Works
How `C.Increased`/`C.Decreased` or threshold predicates work in this context.

### H2: Verify It's Working
`hassette listener --app <key>` to confirm the handler is registered with the threshold predicate. `hassette log --app <key> --since 1h` to see handler invocations. Expected: handler fires only when the sensor crosses the threshold, not on every reading.

### H2: Variations
Hysteresis (don't re-trigger until value drops back), multiple thresholds, combining sensors.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `sensor_threshold.py` (in `recipes/snippets/`) | Keep | Review for voice |

## Cross-Links

- **Links to:** States/Subscribing (numeric conditions), Bus/Filtering (C.Increased, C.Decreased), Testing overview (write a test for this pattern)
- **Linked from:** Recipes overview
