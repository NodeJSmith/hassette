# Troubleshooting

This page organizes common problems by symptom. Click through to the relevant section for detailed guidance.

## Can't connect to Home Assistant

- **Token issues**: Verify `HASSETTE__TOKEN` is set correctly in your `.env` file. See [Authentication](core-concepts/configuration/auth.md).
- **Connection refused / timeout**: Check `base_url` in `hassette.toml`. If running in Docker, ensure Hassette can reach Home Assistant's network. See [Docker Troubleshooting](getting-started/docker/troubleshooting.md#cant-reach-home-assistant).

## Apps not loading

- **App not discovered**: Verify `app_dir` points to the correct directory and your app file is registered in `hassette.toml`. See [Application Configuration](core-concepts/configuration/applications.md). Success: you'll see `INFO hassette.<AppName>.0 ... ─ App initialized` in the logs.
- **Import errors**: Check for missing dependencies or syntax errors in logs. See [Docker Troubleshooting](getting-started/docker/troubleshooting.md#apps-not-loading).
- **App precheck fails**: If an app fails to load, Hassette won't start by default. Check logs for the specific error, or set `allow_startup_if_app_precheck_fails = true` temporarily for debugging.

## Event handler never runs

- **Entity ID typo**: Double-check the entity ID string — `"binary_sensor.motion"` vs `"binary_sensor.motoin"`. Hassette won't error on a non-existent entity; the handler simply never fires.
- **`changed_to` type mismatch**: Home Assistant state values are strings. `changed_to="on"` works; `changed_to=True` does not — it compares against the Python `bool`, not the HA string `"on"`.
- **Domain excluded**: Check `bus_excluded_domains` and `bus_excluded_entities` in your `hassette.toml` — events from excluded domains are silently dropped before reaching your handlers.
- **App not enabled**: Verify the app's config block has `enabled = true` (the default). A disabled app's handlers are never registered.
- **Attribute-only change**: By default, `on_state_change` only fires when the main state value changes. If only an attribute changed (e.g., brightness), pass `changed=False`. See [Filtering — The `changed` Parameter](core-concepts/bus/filtering.md#the-changed-parameter).

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

## Docker-specific issues

For container startup failures, dependency installation problems, health check failures, hot reload issues, and performance tuning, see the dedicated [Docker Troubleshooting](getting-started/docker/troubleshooting.md) guide.

## Web UI not accessible

- **Running locally**: Open `http://localhost:8126/ui/` after starting Hassette.
- **Running in Docker**: Ensure your `docker-compose.yml` includes `ports: ["8126:8126"]`.
- **Disabled**: Check that `run_web_api` and `run_web_ui` are both `true` (the default) in `hassette.toml`.
- See [Web UI](web-ui/index.md) for configuration options.
