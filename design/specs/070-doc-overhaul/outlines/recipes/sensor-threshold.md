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
**New section needed.**

### H2: Variations
Hysteresis (don't re-trigger until value drops back), multiple thresholds, combining sensors.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `sensor_threshold.py` (in `recipes/snippets/`) | Keep | Review for voice |

## Cross-Links

- **Links to:** States/Subscribing (numeric conditions), Bus/Filtering (C.Increased, C.Decreased)
- **Linked from:** Recipes overview
