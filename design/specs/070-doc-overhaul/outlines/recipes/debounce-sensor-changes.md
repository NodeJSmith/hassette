# Recipes — Debounce Sensor Changes

**Status:** Exists (28 lines), follows recipe template, voice polish needed
**Voice mode:** Recipe — problem statement, code, How It Works, variations

## Outline

### H2: (Problem Statement)
Sensors emit bursts of near-identical readings. React only after the value stabilizes.

### H2: The Code
App with `on_state_change(debounce=10.0)`.

### H2: How It Works
What debounce does: resets timer on each new event, fires only after quiet period.

### H2: Verify It's Working
`hassette listener --app <key>` to confirm the handler is registered. `hassette log --app <key> --since 5m` to see handler invocations. Expected: handler fires only after the debounce quiet period, not on every sensor reading.

### H2: Variations
Different debounce values, switching to throttle instead (debounce and throttle are mutually exclusive — `ValueError` if both set), sensor-specific patterns.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `debounce_sensor.py` (in `recipes/snippets/`) | Keep | Review for voice |

## Cross-Links

- **Links to:** Bus overview (rate control section), States/Subscribing, Testing overview (write a test for this pattern)
- **Linked from:** Recipes overview
