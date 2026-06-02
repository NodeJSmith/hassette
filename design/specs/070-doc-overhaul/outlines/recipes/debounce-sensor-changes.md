# Recipes — Debounce Sensor Changes

**Status:** Exists (28 lines), needs JTBD redesign — "How It Works" uses bullet lists with bold lead-ins (anti-pattern)
**Voice mode:** Recipe — problem statement uses "you", "How It Works" uses system-as-subject prose paragraphs
**Page type:** Recipe
**Reader's job:** Stop their automation from reacting to every sensor blip and instead respond only after readings stabilize.

## What was cut

The existing "How It Works" section uses bold-label bullet lists — the recipe
template requires flowing prose paragraphs with system-as-subject voice. The
content stays; the format changes.

The existing page combines debounce with `C.Increased()` filtering. That is a
good realistic example but the prose should walk through debounce first (the
title concept), then the condition filter as a second decision, so the reader
learns the primary concept before the composition.

## Outline

### H2: (Problem statement)
Sensors emit bursts of near-identical readings. You want to react only after a
value stabilizes — and only when it crosses a threshold going up.

### H2: The Code
Full app via `--8<--` include of `debounce_sensor.py`.

### H2: How It Works
Flowing prose paragraphs, one decision each:

1. `debounce=10.0` on the subscription — the handler does not fire until the
   sensor has been quiet for 10 seconds. Each new event resets the timer, so
   rapid fluctuations never reach the handler.
2. `changed=C.Increased()` — the debounce timer only starts when the new value
   is numerically greater than the old. Decreases and unchanged readings are
   dropped before queuing.
3. DI extraction — `D.StateNew[states.SensorState]` delivers a typed state
   object. The handler converts the value to float for threshold comparison.
4. Threshold check and action — when the stabilized temperature exceeds the
   limit, a single log line fires.
5. Config — threshold, debounce duration, and entity ID are all configurable
   without code changes.

### H2: Verify It's Working
`hassette listener --app <key>` to confirm the handler is registered.
`hassette log --app <key> --since 5m` to see invocations. Expected: the handler
fires only after the debounce quiet period, not on every sensor reading.

### H2: Variations
- Throttle instead of debounce: `throttle=30.0` fires on the first event then
  suppresses for the window. Debounce and throttle are mutually exclusive
  (`ValueError` if both set).
- Different sensor types: swap the entity ID and adjust the threshold.

### H2: See Also
Links to Bus overview (rate control), Filtering (conditions reference).

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `debounce_sensor.py` | Keep | Review for voice alignment |

## Cross-Links

- **Links to:** Bus overview (rate control section), Bus/Filtering (conditions), Testing overview
- **Linked from:** Recipes overview
