# Migration Checklist

Use this checklist when migrating each app from AppDaemon to Hassette. Work through one app at a time — verify it works before moving to the next.

## Before You Start

- [ ] Follow the [Local Setup guide](../getting-started/index.md) to install Hassette and verify the connection to Home Assistant
- [ ] Confirm your `hassette.toml` has `base_url` and token configured
- [ ] Read the [Mental Model](concepts.md) page to understand the key design differences
- [ ] Choose one small, simple app as your first migration target

## Step 1: Configuration

- [ ] Convert `appdaemon.yaml` connection settings to `hassette.toml` `[hassette]` section
- [ ] Convert each app entry in `apps.yaml` to an `[apps.your_app]` table in `hassette.toml`
- [ ] Create a typed `AppConfig` subclass for each app — move all `self.args["args"]["key"]` accesses to `self.app_config.key`
- [ ] Verify required fields raise a clear error if missing (run the app without a required config key)

See [Configuration](configuration.md) for the full conversion guide.

## Step 2: App Structure

- [ ] Change base class from `Hass` (or `ADAPI`) to `App` (async) or `AppSync` (sync)
- [ ] Rename `initialize()` to `on_initialize()` — add `async def` if using `App`
- [ ] If you have `terminate()`, rename it to `on_shutdown()` and add `async def`
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
- [ ] Convert each `self.run_once(cb, time)` to `self.scheduler.run_once(cb, start=time)`
- [ ] Convert each `self.run_every(cb, "now", interval)` to `self.scheduler.run_every(cb, start=self.now(), interval=interval)`
- [ ] Convert each `self.run_daily(cb, time)` to `self.scheduler.run_daily(cb, start=time)`
- [ ] Replace `self.cancel_timer(handle)` with `job.cancel()` on the returned `ScheduledJob`
- [ ] Check any blocking work inside callbacks — either use `AppSync` or offload with `task_bucket.run_in_thread()`

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
    - Hassette: `self.states.light.get()` returns a typed cached state (no `await` needed)
    - Use `self.api.get_state()` only when you need to force a fresh read from Home Assistant.

## Next Steps

After migrating all your apps:

- Review the [Core Concepts](../core-concepts/index.md) to learn the full Hassette feature set
- Explore the [Advanced](../advanced/index.md) section for dependency injection, custom states, and type registries
- Set up the [Web UI](../web-ui/index.md) for live monitoring of your automations
