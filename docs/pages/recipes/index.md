# Recipes

Recipes are complete, working automations that solve common Home Assistant tasks. Each one is a self-contained app you can copy, update the entity IDs for your setup, and run. They are not step-by-step tutorials — they are starting points.

## Recipes

**[Motion-Activated Lights](motion-lights.md)** — Turn lights on when a motion sensor triggers and off again after a configurable delay.

**[Daily Notification](daily-notification.md)** — Send a push notification to a mobile device at a specific time each day.

**[Debounce Sensor Changes](debounce-sensor-changes.md)** — Avoid reacting to rapid sensor fluctuations by waiting until a value has been stable for a set period.

**[React to a Service Call](service-call-reaction.md)** — Intercept a Home Assistant service call and run custom logic in response.

**[Monitor Sensor Thresholds](sensor-threshold.md)** — Alert when a sensor value crosses a configured limit, with hysteresis to prevent alert storms.

**[Vacation Mode Toggle](vacation-mode-toggle.md)** — Use a Home Assistant input boolean helper to switch app behavior on and off without redeploying.

Each recipe is a complete, working app. Copy the code, update the entity IDs for your setup, and run it.

## See Also

- [Core Concepts](../core-concepts/index.md) — the building blocks all recipes use: Bus, Scheduler, API, and States.
- [Getting Started](../getting-started/index.md) — if you have not yet run your first app.
