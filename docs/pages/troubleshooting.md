# Troubleshooting

This page organizes common problems by symptom. Click through to the relevant section for detailed guidance.

## Can't connect to Home Assistant

- **Token issues**: Verify `HASSETTE__TOKEN` is set correctly in your `.env` file. See [Authentication](core-concepts/configuration/auth.md).
- **Connection refused / timeout**: Check `base_url` in `hassette.toml`. If running in Docker, ensure Hassette can reach Home Assistant's network. See [Docker Troubleshooting](getting-started/docker/troubleshooting.md#cant-reach-home-assistant).

## Apps not loading

- **App not discovered**: Verify `app_dir` points to the correct directory and your app file is registered in `hassette.toml`. See [Application Configuration](core-concepts/configuration/applications.md). Success: you'll see `INFO hassette.<AppName>.0 ... ─ App initialized` in the logs.
- **Import errors**: Check for missing dependencies or syntax errors in logs. See [Docker Troubleshooting](getting-started/docker/troubleshooting.md#apps-not-loading).
- **App precheck fails**: If an app fails to load, Hassette won't start by default. The precheck runs each app's module through import before starting the WebSocket connection, so any problem is reported immediately. Common causes and their log signatures:

    - **Syntax error or bad import** — a `SyntaxError` or `ModuleNotFoundError` at the top of your app file. Look for: `ERROR hassette.utils.app_utils — Failed to load app 'MyApp': SyntaxError: invalid syntax (at /apps/my_app.py:12)`
    - **Class not found** — the `class_name` in `hassette.toml` doesn't match the actual class name in the file. Look for: `AttributeError: Class MyApp not found in module apps.my_app`
    - **Invalid configuration** — a required `AppConfig` field has no value and no default. Look for: `ERROR ... Failed to load app 'MyApp' due to bad configuration`

    To diagnose without blocking startup, set `allow_startup_if_app_precheck_fails = true` in `hassette.toml` temporarily. This logs the same errors but lets other apps run. Remove it once the problem is fixed — a failing precheck means the broken app won't be loaded either way.

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
2. Hassette fires a `hassette.event.websocket_disconnected` event on the bus — your apps can subscribe to it via `self.bus.on_websocket_disconnected(handler=...)` to react (for example, to pause outgoing calls).
3. The `WebsocketService` is marked not-ready and the framework begins reconnecting.

**Reconnection sequence:**

The initial connection itself retries up to 5 times with exponential backoff (starting at 1 second, capping at 32 seconds) before the service is considered failed. If the service fails, the `ServiceWatcher` takes over:

- It restarts `WebsocketService` up to **5 more times** (configurable via `service_restart_max_attempts`).
- Each restart waits an exponentially increasing delay starting at **2 seconds**, doubling each attempt, capped at **60 seconds** (`service_restart_backoff_seconds`, `service_restart_backoff_multiplier`, `service_restart_max_backoff_seconds`).
- When Home Assistant comes back and the connection is re-established, Hassette fires `hassette.event.websocket_connected` and resets the restart counter.

**If all restarts are exhausted**, Hassette emits a `CRASHED` status event and shuts itself down cleanly.

**What to look for in logs:**

```
WARNING  hassette.WebsocketService -- Retrying _inner_connect in Xs as it raised CouldNotFindHomeAssistantError: ...
ERROR    hassette.WebsocketService -- Serve() task failed: CouldNotFindHomeAssistantError ...
INFO     hassette.ServiceWatcher   -- Service 'WebsocketService' restart attempt N/5, waiting Xs
INFO     hassette.WebsocketService -- Websocket connected to ws://...
ERROR    hassette.ServiceWatcher   -- WebsocketService has failed 5 times (max 5), shutting down Hassette
```

**During reconnection**, your app code keeps running — the bus, scheduler, and state manager remain active. API calls (`.call_service()`, `.get_state()`) will raise `ResourceNotReadyError` while the WebSocket is down because they depend on an active connection. Your handlers registered via the bus will resume receiving events as soon as the WebSocket reconnects; no re-registration is needed.

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

- **Job scheduled for the past**: A time-of-day `start` value like `(7, 0)` is converted to *today* at that time. If it's already past 7:00 AM, `run_once` fires immediately as an overdue job; repeating methods (`run_daily`, `run_hourly`, etc.) advance to the next interval. Use a future `ZonedDateTime` or a seconds offset for guaranteed future scheduling.
- **Runs too often or too rarely**: `run_every(interval=5)` is 5 *seconds*, not minutes. For `run_cron`, `minute=5` means "at minute 5 of every hour", not "every 5 minutes" — use `minute="*/5"` for intervals.
- **Exception in task**: Unhandled exceptions in scheduled tasks are logged at ERROR level but don't crash the scheduler. Check your logs.
- See [Job Management — Troubleshooting](core-concepts/scheduler/management.md#troubleshooting) for more.

## Database degraded / telemetry missing

- **Dashboard shows zeroed-out metrics**: The telemetry database may be unavailable. Check for disk space issues or file permission problems.
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
- **Disabled**: Check that `run_web_api` and `run_web_ui` are both `true` (the default) in `hassette.toml`.
- See [Web UI](web-ui/index.md) for configuration options.
