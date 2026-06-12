# Troubleshooting

This page organizes common problems by symptom. Click through to the relevant section for detailed guidance.

## Can't connect to Home Assistant

- **Token issues**: Verify `HASSETTE__TOKEN` is set correctly in your `.env` file. See [Authentication](core-concepts/configuration/auth.md).
- **Connection refused / timeout**: Check `base_url` in `hassette.toml`. If running in Docker, ensure Hassette can reach Home Assistant's network. See [Docker Troubleshooting](getting-started/docker/troubleshooting.md#cant-reach-home-assistant).

## Apps not loading

- **App not discovered**: Verify `apps.directory` points to the correct directory and your app file is registered in `hassette.toml`. See [Application Configuration](core-concepts/configuration/applications.md). Success: you'll see `INFO hassette.<AppName>.0 ... ─ App initialized` in the logs.
- **Import errors**: Check for missing dependencies or syntax errors in logs. See [Docker Troubleshooting](getting-started/docker/troubleshooting.md#apps-not-loading).
- **App precheck fails**: If an app fails to load, Hassette won't start by default. The precheck runs each app's module through import before starting the WebSocket connection, so any problem is reported immediately. Common causes and their log signatures:

    - **Syntax error or bad import** — a `SyntaxError` or `ModuleNotFoundError` at the top of your app file. Look for: `ERROR hassette.utils.app_utils — Failed to load app 'MyApp': SyntaxError: invalid syntax (at /apps/my_app.py:12)`
    - **Class not found** — the `class_name` in `hassette.toml` doesn't match the actual class name in the file. Look for: `AttributeError: Class MyApp not found in module apps.my_app`
    - **Invalid configuration** — a required `AppConfig` field has no value and no default. Look for: `ERROR ... Failed to load app 'MyApp' due to bad configuration`

    To diagnose without blocking startup, set `allow_startup_if_app_precheck_fails = true` in `hassette.toml` temporarily. This logs the same errors but lets other apps run. Remove it once the problem is fixed — a failing precheck means the broken app won't be loaded either way.

## Forgotten `await` {#forgotten-await}

### Handler or job never runs; `HassetteForgottenAwaitWarning` in logs

**Symptom:** A handler never fires, or a scheduled job never runs, even though the registration call looks correct. Shortly after the call, a warning appears:

```
Coroutine from 'on_state_change' was never awaited (app: Hassette.LightingApp.0, call site: /apps/lighting.py:42). Did you forget 'await'?
```

**Cause:** The registration call was made without `await`. The following methods all return a coroutine — without `await`, the coroutine is created and immediately dropped, so the listener never registers, the job never schedules, and the service call never fires:

- **Bus:** `on_*` methods (`on_state_change`, `on_attribute_change`, `on_call_service`, `on`, `on_service_registered`, `on_component_loaded`, `on_hassette_service_status`, `on_app_state_changed`, and all event-specific convenience methods like `on_homeassistant_start`, `on_websocket_connected`, etc.), `add_listener`
- **Scheduler:** `schedule()`, `add_job()`, `run_in()`, `run_once()`, `run_every()`, `run_minutely()`, `run_hourly()`, `run_daily()`, `run_cron()`
- **Api:** `call_service()`, `fire_event()`, `set_state()`, `turn_on()`, `turn_off()`, `toggle_service()`
- **Entity methods:** `entity.turn_on()`, `entity.turn_off()`, and other entity service methods

**Fix:** Add `await` to the call:

```python
# wrong — handler never registers
self.bus.on_state_change("light.kitchen", handler=self.on_change, name="kitchen")

# correct
await self.bus.on_state_change("light.kitchen", handler=self.on_change, name="kitchen")
```

**The assignment blind spot:** If you store the result in a variable (`sub = self.bus.on_state_change(...)`) without awaiting it, Pyright does not flag the call as unused. The warning will still fire when the variable goes out of scope — but that may be much later. The fix is the same: `sub = await self.bus.on_state_change(...)`.

**Stored-on-self limitation:** When the un-awaited handle is stored on `self` (e.g. `self.sub = self.bus.on_state_change(...)`), it lives for the app's lifetime. The warning fires at app *shutdown*, not at registration. This is a weaker guarantee than the bare-drop case. [Enable Pyright](#enabling-pyright) for the earliest possible signal.

**`ERROR` mode cannot crash the process:** Setting `forgotten_await_behavior = "ERROR"` makes the warning escalate to a raised exception — but because detection happens in Python's garbage collector finalizer (`__del__`), the exception is swallowed by the runtime and printed as `Exception ignored in: ...`. The traceback is visible; the process does not stop. Use [Pyright](#enabling-pyright) if you need a hard build-time failure.

**Importing the warning class:** To use `HassetteForgottenAwaitWarning` in `pytest.warns` or `warnings.filterwarnings`, import it from:

```python
from hassette.exceptions import HassetteForgottenAwaitWarning
```

---

### Enabling Pyright {#enabling-pyright}

Pyright's `reportUnusedCoroutine` catches forgotten `await` calls at edit or CI time, before the app runs. It fires on bare calls, `if coroutine:` conditionals, and `None`-returning methods. It does **not** catch the `_ = coro()` / `self.sub = coro()` assignment pattern — the runtime warning closes that gap.

The Hassette project's own `pyrightconfig.json` already sets `reportUnusedCoroutine: error`. For your app project, add a `pyrightconfig.json` alongside your app files:

```json
{
    "include": ["."],
    "venvPath": ".",
    "venv": ".venv",
    "typeCheckingMode": "basic",
    "reportUnusedCoroutine": "error"
}
```

`basic` mode already enables `reportUnusedCoroutine`, so the last line is redundant if you use `basic` mode — but making it explicit ensures the rule stays active even if the mode changes later.

Run Pyright with:

```bash
uv run pyright
# or, if installed globally:
pyright
```

## Event handler never runs

- **Entity ID typo**: Double-check the entity ID string — `"binary_sensor.motion"` vs `"binary_sensor.motoin"`. Hassette won't error on a non-existent entity; the handler simply never fires.
- **`changed_to` type mismatch**: Home Assistant state values are strings. `changed_to="on"` works; `changed_to=True` does not — it compares against the Python `bool`, not the HA string `"on"`.
- **Domain excluded**: Check `bus_excluded_domains` and `bus_excluded_entities` in your `hassette.toml` — events from excluded domains are silently dropped before reaching your handlers.
- **App not enabled**: Verify the app's config block has `enabled = true` (the default). A disabled app's handlers are never registered.
- **Attribute-only change**: By default, `on_state_change` only fires when the main state value changes. If only an attribute changed (e.g., brightness), pass `changed=False`. See [Filtering — The `changed` Parameter](core-concepts/bus/filtering.md#the-changed-parameter).

## Home Assistant goes offline

When Home Assistant becomes unreachable or disconnects mid-session, Hassette handles recovery automatically without restarting the process.

**What happens immediately:**

1. The WebSocket receive loop detects the disconnect (closed frame, connection reset, or server disconnect) and raises internally.
2. Hassette fires a `hassette.event.websocket_disconnected` event on the bus — your apps can subscribe to it via `await self.bus.on_websocket_disconnected(handler=..., name="ws_disconnect")` to react (for example, to pause outgoing calls).
3. The `WebsocketService` is marked not-ready and the framework begins reconnecting.

**Reconnection sequence:**

The initial connection itself retries up to 5 times with exponential backoff (starting at 1 second, capping at 32 seconds) before the service is considered failed. If the service fails, the `ServiceWatcher` takes over:

- It restarts `WebsocketService` using its `RestartSpec`: up to **5 restarts** within a **300-second sliding window** (TRANSIENT type).
- Each restart waits an exponentially increasing delay starting at **2 seconds**, doubling each attempt, capped at **60 seconds**.
- When Home Assistant comes back and the service recovers to RUNNING and becomes ready, Hassette fires `hassette.event.websocket_connected` and the restart budget resets automatically.

**If the restart budget is exhausted**, `WebsocketService` enters `EXHAUSTED_COOLING` for a 300-second cooldown, then resets its budget and retries. The TRANSIENT restart type means it keeps trying rather than shutting down immediately.

**What to look for in logs:**

```
WARNING  hassette.WebsocketService -- Retrying _inner_connect in Xs as it raised CouldNotFindHomeAssistantError: ...
ERROR    hassette.WebsocketService -- Serve() task failed: CouldNotFindHomeAssistantError ...
INFO     hassette.ServiceWatcher   -- Service 'WebsocketService' restarting (attempt N, waiting Xs)
DEBUG    hassette.WebsocketService -- Connected to WebSocket at ws://...
INFO     hassette.ServiceWatcher   -- Service 'WebsocketService' in cooldown for 300.0s (cycle 1)
```

**During reconnection**, your app code keeps running — the bus, scheduler, and state manager remain active. `.call_service()` will raise `ResourceNotReadyError` while the WebSocket is down because it depends on an active connection. `.get_state()` returns the last-known cached value — the data may be stale, but reads do not fail. Call `is_ready()` on the state proxy to check whether data is fresh. The cache is replaced with live data once the WebSocket reconnects. Your handlers registered via the bus will resume receiving events as soon as the WebSocket reconnects; no re-registration is needed.

## Event handler exceptions

Exceptions raised inside a bus handler are caught by the framework, logged, and swallowed — they do not propagate to the caller, do not crash the app, and do not affect other handlers.

The specific behavior:

- The exception is logged at `ERROR` level with the full traceback: `Handler error (topic=..., handler=...) \n<traceback>`
- Hassette records the invocation in the telemetry database with `status='error'` and the error type and message.
- The app continues running normally; subsequent events are dispatched as usual.

This matches the scheduler's behavior for jobs — exceptions fail silently (logged to error).

**What to look for in logs:**

```
ERROR hassette.CommandExecutor -- Handler error (topic=hass.event.state_changed.light.kitchen, handler=Listener<Hassette.MyApp.0 - on_light_change>)
Traceback (most recent call last):
  ...
AttributeError: 'NoneType' object has no attribute 'brightness'
```

See also: [Writing Handlers](core-concepts/bus/handlers.md) for how to use dependency injection to avoid common handler errors.

## Scheduler not firing

- **Job scheduled for the past**: `run_once(at="07:00")` called after 7 AM defers the job to tomorrow (with a WARNING log). `run_daily(at="07:00")` fires at the next 7 AM occurrence (today if before 7 AM, tomorrow otherwise).
- **Runs too often or too rarely**: `run_every(seconds=5)` is 5 *seconds*, not minutes — use `run_every(minutes=5)` for a 5-minute interval. For `run_cron`, the expression `"5 * * * *"` means "at minute 5 of every hour", not "every 5 minutes" — use `"*/5 * * * *"` for intervals.
- **Exception in task**: Unhandled exceptions in scheduled tasks are logged at ERROR level but don't crash the scheduler. Check your logs.
- See [Job Management — Troubleshooting](core-concepts/scheduler/management.md#troubleshooting) for more.

## Database degraded / telemetry missing

- **Stats strip shows zeroed-out metrics**: The telemetry database may be unavailable. Check for disk space issues or file permission problems.
- **Docker**: Check the data volume has space: `docker compose exec hassette df -h /data`. The database file is at `/data/hassette.db` by default.
- **Safe to delete**: Deleting `hassette.db` only loses telemetry history — your automations continue to run. Restart Hassette to recreate the database.
- See [Database & Telemetry — Degraded Mode](core-concepts/database-telemetry.md#degraded-mode) for details.

## Cache not persisting

- **Data lost after restart**: Verify the `data_dir` is correctly configured and writable. In Docker, ensure the `/data` volume is mounted.
- **Cache shared between instances**: All instances of the same app class share one cache directory. Use `self.app_config.instance_name` as a key prefix to avoid collisions.
- See [App Cache — Troubleshooting](core-concepts/cache/patterns.md#troubleshooting) for more.

## Custom state class not registering

- Ensure the class has `domain: Literal["your_domain"]` as a field.
- If overriding `__init_subclass__`, call `super().__init_subclass__()`.
- See [Custom States — Troubleshooting](advanced/custom-states.md#troubleshooting).

## Upgrading Hassette

**Check your current version:**

```bash
hassette --version          # if installed as a CLI tool
uv pip show hassette        # shows installed version in your project
```

**Upgrade to the latest release:**

```bash
uv add hassette@latest
```

**Release notes:** See the [Changelog](../CHANGELOG.md) for what changed in each version. Breaking changes are flagged with a `BREAKING CHANGE` footer in commit messages and are called out explicitly in the changelog under a "Breaking Changes" heading.

**Major version upgrades — data directory:** On bare-metal installs (not Docker), Hassette's default `data_dir` and `config_dir` include the major version number (e.g., `~/.local/share/hassette/v0/`). If a future major release changes this to `v1/`, Hassette will start with a fresh data directory. To keep your existing telemetry and cache, set `data_dir` and `config_dir` explicitly in `hassette.toml` or via the `HASSETTE__DATA_DIR` / `HASSETTE__CONFIG_DIR` environment variables. Docker users are unaffected — the `/data` and `/config` paths are version-independent.

## Docker-specific issues

For container startup failures, dependency installation problems, health check failures, hot reload issues, and performance tuning, see the dedicated [Docker Troubleshooting](getting-started/docker/troubleshooting.md) guide.

## Web UI not accessible

- **Running locally**: Open `http://localhost:8126/ui/` after starting Hassette.
- **Running in Docker**: Ensure your `docker-compose.yml` includes `ports: ["8126:8126"]`.
- **Disabled**: Check that `run` and `run_ui` are both `true` under `[hassette.web_api]` in `hassette.toml`.
- See [Web UI](web-ui/index.md) for configuration options.
