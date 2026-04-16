# Migration Checklist

Use this checklist when migrating each app from AppDaemon to Hassette. Work through one app at a time — verify it works before moving to the next.

Complete the pre-migration steps in the [Migration Guide overview](index.md) before starting this checklist.

## Before You Start

- [ ] **Requires Python 3.11 or later** — check with `python --version` or `python3 --version`. Hassette will not install on Python 3.10 or earlier. See [python.org/downloads](https://www.python.org/downloads/) to upgrade.

## Step 1: Configuration

- [ ] Convert `appdaemon.yaml` connection settings to `hassette.toml` `[hassette]` section
- [ ] Convert each app entry in `apps.yaml` to an `[apps.your_app]` table in `hassette.toml`
- [ ] Create a typed `AppConfig` subclass for each app — move all `self.args["args"]["key"]` accesses to `self.app_config.key`
- [ ] Verify required fields raise a clear error if missing (run the app without a required config key)

See [Configuration](configuration.md) for the full conversion guide.

## Step 2: App Structure

- [ ] Change base class from `Hass` (or `ADAPI`) to `App` (async) or `AppSync` (sync)
- [ ] Rename `initialize()` to the correct hook for your base class:
    - `App`: `async def on_initialize(self)` — must be `async def`
    - `AppSync`: `def on_initialize_sync(self)` — must be a plain synchronous method; do **not** override `on_initialize` on `AppSync` (it is `@final` and raises `NotImplementedError`)
- [ ] If you have `terminate()`, rename it:
    - `App`: `async def on_shutdown(self)`
    - `AppSync`: `def on_shutdown_sync(self)`
- [ ] Confirm the app starts without errors (`uv run hassette` or your start command)

See [Mental Model](concepts.md) for the lifecycle differences.

## Step 3: Event Listeners

- [ ] Convert each `self.listen_state(...)` to `self.bus.on_state_change(...)`
  - [ ] Move filter arguments: `new=` → `changed_to=`, `old=` → `changed_from=`
  - [ ] Update callback signatures to use dependency injection or accept an event object
  - [ ] Replace `self.cancel_listen_state(handle)` with `subscription.cancel()`
- [ ] Convert each `self.listen_event("call_service", ...)` to `self.bus.on_call_service(...)`
  - [ ] Update callback signatures
  - [ ] Replace `self.cancel_listen_event(handle)` with `subscription.cancel()`
- [ ] For attribute-level subscriptions, switch to `self.bus.on_attribute_change(...)`

See [Bus & Events](bus.md) for side-by-side examples.

## Step 4: Scheduler

- [ ] Convert each `self.run_in(cb, seconds)` to `self.scheduler.run_in(cb, delay=seconds)`
- [ ] Convert each `self.run_once(cb, time(H, M))` to `self.scheduler.run_once(cb, at="HH:MM")`
- [ ] Convert each `self.run_every(cb, "now", interval)` to `self.scheduler.run_every(cb, seconds=interval)`
- [ ] Convert each `self.run_daily(cb, time(H, M))` to `self.scheduler.run_daily(cb, at="HH:MM")`
- [ ] Replace `self.cancel_timer(handle)` with `job.cancel()` on the returned `ScheduledJob`
- [ ] Check any blocking work inside callbacks — for apps with heavy sync logic, switch to `AppSync`; for isolated blocking calls inside an `App` handler, use `await self.task_bucket.run_in_thread(...)`

See [Scheduler](scheduler.md) for method equivalents.

## Step 5: API Calls

- [ ] Convert `self.get_state(entity_id)` to `self.states.domain.get(entity_id)` for cached reads
- [ ] Replace `self.call_service("domain/service", ...)` with `await self.api.call_service("domain", "service", ...)`
- [ ] Add `await` to all `self.api.*` calls — forgetting `await` returns a coroutine without executing the call
- [ ] Replace `self.set_state(...)` with `await self.api.set_state(...)`
- [ ] Replace `self.log(...)` with `self.logger.info(...)` (and `.warning()`, `.error()` as needed)

See [API Calls](api.md) for the full guide.

## Step 6: Test

- [ ] Write at least one test using `AppTestHarness`
- [ ] Seed entity state before simulating events
- [ ] Simulate the key events your app responds to
- [ ] Assert the expected API calls were made via `harness.api_recorder`
- [ ] Run the test suite: `pytest`

See [Testing](testing.md) for the test harness guide.

## Step 7: Verify Live

- [ ] Deploy the migrated app alongside (or instead of) the AppDaemon version
- [ ] Confirm all automations fire as expected in live operation
- [ ] Check logs for any runtime errors or unexpected behavior

## Common Pitfalls

!!! warning "Async gotchas"
    - Forgetting `await` on `self.api.*` calls is the most common migration mistake. The call returns a coroutine object and silently does nothing.
    - Do not use `self.api.sync` inside `App` lifecycle methods — use the async API instead, or switch to `AppSync`.

!!! tip "Configuration access"
    - AppDaemon: `self.args["args"]["key"]`
    - Hassette: `self.app_config.key`
    - Define all config keys in your `AppConfig` model for validation and autocomplete.

!!! tip "State access"
    - AppDaemon: `self.get_state()` returns a cached state (string or dict)
    - Hassette: `self.states.light.get("light.kitchen")` returns a typed cached state (no `await` needed) (the domain prefix is optional).
    - Use `self.api.get_state()` only when you need to force a fresh read from Home Assistant.

## Next Steps

After migrating all your apps:

- Review the [Core Concepts](../core-concepts/index.md) to learn the full Hassette feature set
- Explore [Dependency Injection](../core-concepts/bus/dependency-injection.md), [Custom States](../advanced/custom-states.md), and [Type Registries](../advanced/type-registry.md)
- Set up the [Web UI](../web-ui/index.md) for live monitoring of your automations
