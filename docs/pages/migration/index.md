# Migration Guide

This guide helps AppDaemon developers migrate their automations to Hassette. You will find concept-by-concept comparisons, side-by-side code examples, and a final checklist to track your progress.

!!! note "Coming from Node-RED or pyscript?"
    This guide focuses on AppDaemon because the mental model is the closest match to Hassette — both are Python-based, event-driven, and connect to Home Assistant via WebSocket. If you're coming from **Node-RED**, the visual flow model is very different from writing Python classes, so the [Getting Started guide](../getting-started/index.md) is a better starting point than this migration guide. If you're coming from **pyscript**, the transition is closer: you already write Python, but Hassette replaces the decorator-based, script-level approach with a structured class and dependency injection model — skimming this guide alongside Getting Started should orient you.

## Is Migration Worth It?

Both AppDaemon and Hassette connect to Home Assistant via WebSocket and let you write Python automations. The decision to migrate comes down to what you value:

| You should migrate if... | You might stay with AppDaemon if... |
|--------------------------|--------------------------------------|
| You want IDE autocomplete and type errors at development time, not runtime | Your existing apps work and you don't need type safety |
| You want to unit-test your automations with a proper test harness | You prefer synchronous code without `async`/`await` |
| You want Pydantic-validated configuration with defaults and clear error messages | Your team already knows AppDaemon well |
| You want structured logs that include the calling method and line number | You rely on AppDaemon-specific features not yet in Hassette |
| You want a dependency injection model for event handlers | — |

## Known Gaps

The following AppDaemon features are not currently in Hassette. If your apps rely on any of these, migration is not yet recommended:

| AppDaemon feature | Status in Hassette |
|-------------------|--------------------|
| `listen_log` / log event subscriptions | Out of scope — not planned |
| HADashboard | Out of scope — Hassette has its own web UI for monitoring, not display panels |
| Notification app helpers (`notify`, `call_action`) | Out of scope — call `self.api.call_service("notify", ...)` directly |
| MQTT plugin | Roadmap — not yet supported; use `self.api.call_service` workarounds |
| Global variables / inter-app communication via `AD` | Not supported — use shared state in the HA state store or a persistent cache |

If a feature you depend on is missing, open an issue or check the [GitHub discussions](https://github.com/NodeJSmith/hassette/discussions).

## What Changes

When you migrate from AppDaemon, you change four areas:

1. **Configuration** — `appdaemon.yaml` + `apps.yaml` become a single `hassette.toml`. App arguments become typed Pydantic models instead of raw dictionaries.
2. **App structure** — `Hass` subclass with `initialize()` becomes an `App` subclass with `async def on_initialize()`.
3. **Event handlers** — `self.listen_state(...)` and `self.listen_event(...)` become `self.bus.on_state_change(...)` and `self.bus.on_call_service(...)`.
4. **API calls** — synchronous `self.call_service(...)` becomes `await self.api.call_service(...)`.

The scheduler API is similar to AppDaemon's, with named parameters and richer job objects.

## Quick Start Checklist

Before you start migrating app by app, complete this setup:

- [ ] Follow the [Quickstart guide](../getting-started/index.md) to install Hassette and confirm `hassette.toml` connects to Home Assistant
- [ ] Read [Mental Model](concepts.md) to understand the key design differences
- [ ] Pick one small, simple app as your first migration target
- [ ] Follow the [Migration Checklist](checklist.md) for that app
- [ ] Run the [test harness](testing.md) to verify behavior before going live

## Guide Structure

| Page | What it covers |
|------|----------------|
| [Mental Model](concepts.md) | How AppDaemon and Hassette differ in design philosophy |
| [Bus & Events](bus.md) | `listen_state` / `listen_event` → `bus.on_state_change` / `bus.on_call_service` |
| [Scheduler](scheduler.md) | `run_in`, `run_daily`, and other scheduler equivalents |
| [API Calls](api.md) | Getting states, calling services, setting states |
| [Configuration](configuration.md) | `appdaemon.yaml` + `apps.yaml` → `hassette.toml` + `AppConfig` |
| [Testing](testing.md) | How to test Hassette apps with `AppTestHarness` |
| [Migration Checklist](checklist.md) | Step-by-step migration checklist |

## Quick Reference Table

The table below maps the most common AppDaemon operations to their Hassette equivalents.

| Action | AppDaemon | Hassette |
|--------|-----------|----------|
| Listen for a state change | `self.listen_state(self.cb, "binary_sensor.door", new="on")` | `self.bus.on_state_change("binary_sensor.door", handler=self.cb, changed_to="on")` |
| React on attribute threshold | `self.listen_state(self.cb, "sensor.x", attribute="battery", below=20)` | `self.bus.on_attribute_change("sensor.x", "battery", handler=self.cb, changed_to=lambda v: v < 20)` |
| Monitor service calls | `self.listen_event(self.on_service, "call_service", domain="light")` | `self.bus.on_call_service(domain="light", handler=self.on_service)` |
| Schedule something in 60 seconds | `self.run_in(self.turn_off, 60)` | `self.scheduler.run_in(self.turn_off, delay=60)` |
| Run every morning at 07:30 | `self.run_daily(self.morning, time(7, 30, 0))` | `self.scheduler.run_daily(self.morning, at="07:30")` |
| Get entity state (cached) | `self.get_state("light.kitchen")` | `self.states.light.get("light.kitchen")` |
| Call a HA service | `self.call_service("light/turn_on", entity_id="light.x", brightness=200)` | `await self.api.call_service("light", "turn_on", target={"entity_id": "light.x"}, brightness=200)` |
| Access app configuration | `self.args["args"]["entity"]` | `self.app_config.entity` |
| Stop a listener | `self.cancel_listen_state(handle)` | `subscription.cancel()` |
| Stop a scheduled job | `self.cancel_timer(handle)` | `job.cancel()` |

## Next Steps

- [Mental Model](concepts.md) — how AppDaemon and Hassette differ in design philosophy
- [Bus & Events](bus.md) — `listen_state` / `listen_event` → `bus.on_state_change` / `bus.on_call_service`
- [Scheduler](scheduler.md) — `run_in`, `run_daily`, and other scheduler equivalents
- [API Calls](api.md) — getting states, calling services, setting states
- [Configuration](configuration.md) — `appdaemon.yaml` + `apps.yaml` → `hassette.toml` + `AppConfig`
- [Testing](testing.md) — how to test Hassette apps with `AppTestHarness`
- [Migration Checklist](checklist.md) — step-by-step migration checklist
