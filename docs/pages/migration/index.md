# Migration Guide

This guide covers migrating AppDaemon automations to Hassette.

## Quick Reference

Four areas change: configuration, app structure, event handlers, and API calls. Hassette splits AppDaemon's flat `self.*` surface into typed handles — `self.bus` (event subscriptions), `self.scheduler` (timed jobs), `self.api` (HA service calls), and `self.states` (entity state cache).

| Action | AppDaemon | Hassette | Guide |
|--------|-----------|----------|-------|
| Define an app | `class MyApp(Hass)` | `class MyApp(App[MyConfig])` | [Configuration](configuration.md) |
| Lifecycle hook | `def initialize(self):` | `async def on_initialize(self):` | [Mental Model](concepts.md) |
| Listen for state changes | `self.listen_state(self.cb, "light.x", new="on")` | `await self.bus.on_state_change("light.x", handler=self.cb, changed_to="on", name="...")` | [Bus & Events](bus.md) |
| Listen for service calls | `self.listen_event(self.cb, "call_service", domain="light")` | `await self.bus.on_call_service(domain="light", handler=self.cb, name="...")` | [Bus & Events](bus.md) |
| Cancel a listener | `self.cancel_listen_state(handle)` | `subscription.cancel()` | [Bus & Events](bus.md) |
| Schedule a timer | `self.run_in(self.cb, 60)` | `await self.scheduler.run_in(self.cb, delay=60)` | [Scheduler](scheduler.md) |
| Cancel a timer | `self.cancel_timer(handle)` | `job.cancel()` | [Scheduler](scheduler.md) |
| Run daily at 07:30 | `self.run_daily(self.cb, time(7, 30, 0))` | `await self.scheduler.run_daily(self.cb, at="07:30")` | [Scheduler](scheduler.md) |
| Call a HA service | `self.call_service("light/turn_on", entity_id="light.x")` | `await self.api.call_service("light", "turn_on", target={"entity_id": "light.x"})` | [API Calls](api.md) |
| Get entity state | `self.get_state("light.x")` | `self.states.light.get("light.x")` or `await self.api.get_state("light.x")` | [API Calls](api.md) |
| Access app config | `self.args["entity"]` | `self.app_config.entity` | [Configuration](configuration.md) |
| Logging | `self.log("message")` | `self.logger.info("message")` | [Mental Model](concepts.md) |

## Is Migration Worth It?

| Migrate if... | Stay with AppDaemon if... |
|---------------|--------------------------|
| You want IDE autocomplete and type errors at write time | Your apps work and you don't need type safety |
| You want to unit-test automations with a real test harness | You prefer synchronous code without `async`/`await` |
| You want Pydantic-validated config with clear error messages | Your team already knows AppDaemon well |
| You want dependency injection in event handlers | You rely on AppDaemon features not yet in Hassette |
| You want structured per-app logs with method and line context | |

## Known Gaps

| AppDaemon feature | Status in Hassette |
|-------------------|--------------------|
| `listen_log` / log event subscriptions | Not planned |
| HADashboard | Not planned |
| Notification helpers (`notify`, `call_action`) | Use `await self.api.call_service("notify", ...)` directly |
| MQTT plugin | Not yet supported. No workaround available. |
| Global variables / inter-app communication | Use `await self.bus.emit(topic, data)` for in-process broadcast |

If a feature you depend on is missing, [open an issue](https://github.com/NodeJSmith/hassette/issues) or check [GitHub discussions](https://github.com/NodeJSmith/hassette/discussions).

## Common Pitfalls

**`name=` is required on all bus subscriptions.** Omitting it raises [`ListenerNameRequiredError`][hassette.exceptions.ListenerNameRequiredError] at runtime. Every `on_state_change`, `on_call_service`, and `on` call needs a stable string name.

**`self.api.*`, `self.bus.on_*`, and `self.scheduler.*` are async and must be awaited.** Forgetting `await` returns a coroutine object. Nothing is registered or called.

**[`AppSync`][hassette.app.app.AppSync] apps use `.sync` facades.** If you subclass `AppSync` for synchronous handlers, use `self.bus.sync.on_state_change(...)` and `self.scheduler.sync.run_in(...)`. The async methods are not available in sync hooks.

## Per-App Migration Checklist

The [Migration Checklist](checklist.md) walks through converting a single app from AppDaemon to Hassette. Work through it once for your first app, then use it as a reference for the rest.
