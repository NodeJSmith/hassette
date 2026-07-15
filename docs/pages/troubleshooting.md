# Troubleshooting

## Can't Connect to Home Assistant

**Token not accepted.** Set `HASSETTE__TOKEN` in your `.env` file or environment. The value must be a long-lived access token from Home Assistant's profile page. See [Authentication](getting-started/ha_token.md).

**Connection refused or timeout.** Check `base_url` in `hassette.toml`. The default is `http://127.0.0.1:8123`. Include the scheme (`http://`) and port explicitly — `homeassistant.local` without the scheme raises [`SchemeRequiredInBaseUrlError`][hassette.exceptions.SchemeRequiredInBaseUrlError] at startup. Use `http://homeassistant.local:8123` instead.

**Running in Docker.** Hassette must reach Home Assistant's network. If Home Assistant runs in a separate container or on a different host, `base_url` must point to its actual address, not `127.0.0.1`. See [Docker Troubleshooting](getting-started/docker/troubleshooting.md#cant-access-the-web-ui).

**Invalid token at startup.** Look for [`InvalidAuthError`][hassette.exceptions.InvalidAuthError] in the startup log. This is fatal. Hassette will not retry. Generate a new long-lived token and update `HASSETTE__TOKEN`.

**During reconnection**, your app code keeps running — the bus, scheduler, and state manager remain active. `.call_service()` will raise `ConnectionClosedError` while the WebSocket is down because it depends on an active connection. `.get_state()` returns the last-known cached value — the data may be stale, but reads do not fail. To react to connection loss, subscribe to `on_websocket_disconnected` / `on_websocket_connected` on the bus. The cache is replaced with live data once the WebSocket reconnects. Your handlers registered via the bus will resume receiving events as soon as the WebSocket reconnects; no re-registration is needed.

## Apps Not Loading

The app precheck runs before the WebSocket connection opens. It imports each app module, resolves the class, and validates config. Any failure blocks startup by default.

**Syntax error or bad import.** Look for this pattern in the log:

```
ERROR hassette.utils.app_utils — Failed to load app 'MyApp': SyntaxError: invalid syntax (at /apps/my_app.py:12)
```

Fix the syntax error or install the missing dependency.

**Class not found.** The `class_name` in `hassette.toml` doesn't match the actual class name in the file:

```
AttributeError: Class MyApp not found in module apps.my_app
```

Check for typos in `class_name` in `hassette.toml` and confirm the class is defined at module level.

**Invalid config.** A required [`AppConfig`][hassette.app.app_config.AppConfig] field has no value and no default:

```
ERROR hassette — Failed to load app 'MyApp' due to bad configuration
```

Set the missing field in `hassette.toml` or via an environment variable.

**Diagnosing without blocking startup.** Set `allow_startup_if_app_precheck_fails = true` in `hassette.toml`. This logs the same errors but lets healthy apps start. The broken app still won't run. Remove this setting once the problem is fixed.

## Forgotten `await` {#forgotten-await}

### Handler or job never runs; `HassetteForgottenAwaitWarning` in logs

**Symptom:** A handler never fires, or a scheduled job never runs, even though the registration call looks correct. Shortly after the call, a warning appears:

```
Coroutine from 'on_state_change' was never awaited (app: Hassette.LightingApp.0, call site: /apps/lighting.py:42). Did you forget 'await'?
```

**Cause:** The registration call was made without `await`. The following methods all return a coroutine — without `await`, the coroutine is created and immediately dropped, so the listener never registers, the job never schedules, and the service call never fires:

- **Bus:** `on_*` methods (`on_state_change`, `on_attribute_change`, `on_call_service`, `on`, `on_service_registered`, `on_component_loaded`, `on_hassette_service_status`, `on_app_state_changed`, and all event-specific convenience methods like `on_homeassistant_start`, `on_websocket_connected`, etc.), `add_listener`
- **Scheduler:** `schedule()`, `add_job()`, `run_in()`, `run_once()`, `run_every()`, `run_minutely()`, `run_hourly()`, `run_daily()`, `run_cron()`
- **Api:** `call_service()`, `fire_event()`, `set_state()`, `turn_on()`, `turn_off()`, `toggle()`
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

**`"error"` mode cannot crash the process:** Setting `forgotten_await_behavior = "error"` makes the warning escalate to a raised exception — but because detection happens in Python's garbage collector finalizer (`__del__`), the exception is swallowed by the runtime and printed as `Exception ignored in: ...`. The traceback is visible; the process does not stop. Use [Pyright](#enabling-pyright) if you need a hard build-time failure.

**Importing the warning class:** To use `HassetteForgottenAwaitWarning` in `pytest.warns` or `warnings.filterwarnings`, import it from:

```python
from hassette import HassetteForgottenAwaitWarning
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

## Handler Registration Fails

**[`ListenerNameRequiredError`][hassette.exceptions.ListenerNameRequiredError].** All bus registration methods require a `name=` parameter. Omitting it raises this error immediately at registration time. Add a stable, descriptive name:

```python
await self.bus.on_state_change("light.kitchen", handler=self.on_light_change, name="kitchen_light")
```

**[`DuplicateListenerError`][hassette.exceptions.DuplicateListenerError].** Two listeners registered within the same app instance and session share the same `name` and topic. Use a different name for each listener, or remove the first registration before re-registering. Cross-session duplicates (after a restart) are replaced automatically and don't raise this error.

## Handler Never Fires

Work through this checklist in order.

**1. Entity ID typo.** Hassette does not error on a non-existent entity ID. The handler simply never fires. Double-check the entity ID string. Use `hassette status` or the web UI to confirm the entity exists and its exact ID.

**2. `changed_to` type mismatch.** Home Assistant state values are strings. `changed_to="on"` works. `changed_to=True` does not. It compares a Python `bool` against a string and never matches. Use the string form.

**3. Domain excluded by config.** Check `bus_excluded_domains` and `bus_excluded_entities` in `hassette.toml`. Events from excluded domains are dropped before reaching any handler.

**4. Attribute-only change.** `on_state_change` fires when the main state value changes. If only an attribute changed (brightness, temperature, etc.) without the state string changing, the handler won't fire. Pass `changed=False` to receive both state and attribute changes. See [Filtering](core-concepts/bus/filtering.md#changedfalse).

**5. App not enabled.** Check that the app's config block has `enabled = true` (the default). A disabled app's handlers are never registered.

## Scheduler Not Firing

**Job scheduled for the past.** `run_once(at="07:00")` called after 7 AM defers the job to tomorrow and logs a WARNING. `run_daily(at="07:00")` fires at the next 7 AM occurrence.

**Unit confusion.** `run_every(seconds=5)` fires every 5 seconds. Use named parameters to be explicit: `run_every(minutes=5)`. For `run_cron`, `"5 * * * *"` means "at minute 5 of every hour," not "every 5 minutes." Use `"*/5 * * * *"` for a 5-minute interval.

**Exception in the task.** Unhandled exceptions inside scheduled tasks are caught, logged at ERROR level, and swallowed. The scheduler keeps running. Check your logs for the traceback.

See also: [Job Management](core-concepts/scheduler/management.md#handle-errors).

## Database Degraded / Telemetry Missing

**Stats show zeroed-out metrics.** The telemetry database is unavailable. Check disk space and file permissions.

In Docker, check the data volume:

```bash
docker compose exec hassette df -h /data
```

The database file is at `/data/hassette.db` by default.

**Safe to delete.** Deleting `hassette.db` only removes telemetry history. Your automations continue to run. Restart Hassette to recreate the database.

**Schema version mismatch.** If the database was created by a newer version of Hassette, startup raises [`SchemaVersionError`][hassette.exceptions.SchemaVersionError] and halts. Hassette will not try to update the old database automatically. Either upgrade Hassette to match the database or delete the database to start fresh.

See also: [Database and Telemetry](core-concepts/database-telemetry.md#degraded-mode).

## Cache Not Persisting

**Data lost after restart.** Verify `data_dir` is correctly configured and writable. In Docker, ensure the `/data` volume is mounted. Cache files live under `data_dir`.

**Multi-instance collisions.** All instances of the same app class share one cache namespace. Use `self.app_config.instance_name` as a key prefix to isolate each instance's data:

```python
key = f"{self.app_config.instance_name}:last_seen"
```

See also: [App Cache](core-concepts/cache/patterns.md#troubleshooting).

## Custom State Class Not Registering

**Missing `domain` annotation.** Every custom state class needs a `domain: Literal["your_domain"]` field. Without it, the class raises `NoDomainAnnotationError` internally and is not registered.

**`super().__init_subclass__()` not called.** If you override `__init_subclass__`, call `super().__init_subclass__()` to preserve registration. Omitting it silently prevents the class from being added to the registry.

See also: [Custom States](core-concepts/states/custom-states.md#troubleshooting).

## Web UI Not Accessible

**Running locally.** Open `http://localhost:8126/` after starting Hassette.

**Running in Docker.** Ensure `docker-compose.yml` includes `ports: ["8126:8126"]`.

**Disabled in config.** Check `hassette.toml`:

```toml
[hassette.web_api]
run = true
run_ui = true
```

Both must be `true`. `run = false` disables the entire web API, including the health check. `run_ui = false` disables the dashboard while keeping the API and health check active.

See also: [Web UI](web-ui/index.md).

## Docker-Specific Issues

For container startup failures, dependency installation, health check failures, hot reload issues, and network configuration, see the [Docker Troubleshooting](getting-started/docker/troubleshooting.md) guide.

## Exception Reference

### Connection

**`CouldNotFindHomeAssistantError`** Raised when Hassette cannot reach the Home Assistant WebSocket at startup. Extends [`FatalError`][hassette.exceptions.FatalError]. Hassette will not retry. Check `base_url` and confirm Home Assistant is running and accessible.

**`InvalidAuthError`** The token was rejected by Home Assistant. Generate a new long-lived access token and update `HASSETTE__TOKEN`.

**`BaseUrlRequiredError`** `base_url` is missing entirely. Set it in `hassette.toml`.

**`SchemeRequiredInBaseUrlError`** `base_url` is set but has no scheme. Use `http://` or `https://`.

**`IPV6NotSupportedError`** `base_url` contains an IPv6 address, which Hassette does not support. Use a hostname or IPv4 address instead.

**[`ResourceNotReadyError`][hassette.exceptions.ResourceNotReadyError]** An API call was made while the WebSocket was disconnected or a service was still initializing. The WebSocket service reconnects automatically. Retry after reconnection.

**`ConnectionClosedError`** The WebSocket closed unexpectedly. Hassette handles this internally and reconnects. You only see this if you catch it explicitly.

**[`FailedMessageError`][hassette.exceptions.FailedMessageError]** A message sent over the WebSocket returned an error response from Home Assistant. Check `e.code` for the structured error type from HA. `e.code` is `None` for locally-synthesized failures like transport timeouts.

### Registration

**`ListenerNameRequiredError`** `name=` was omitted on a bus registration call. Add a stable `name=` parameter to the registration.

**`DuplicateListenerError`** Two listeners in the same app instance registered with the same name and topic. Use distinct names.

### State Conversion

**`DomainNotFoundError`** No state class is registered for the requested domain. Import the relevant state module or define a custom state class with a matching `domain` annotation.

**`RegistryNotReadyError`** The state registry was queried before any state classes were imported. Ensure state modules are imported before state conversion is attempted.

**`NoDomainAnnotationError`** A state class is missing `domain: Literal["..."]`. Add the annotation.

**[`InvalidDataForStateConversionError`][hassette.exceptions.InvalidDataForStateConversionError]** The data passed to state conversion is malformed or `None`. Check the upstream event or API response.

**[`UnableToConvertStateError`][hassette.exceptions.UnableToConvertStateError]** The state dict exists but cannot be coerced to the target state class. Check that the class fields match the entity's actual attributes.

**[`InvalidEntityIdError`][hassette.exceptions.InvalidEntityIdError]** An entity ID string is malformed (wrong format, empty, wrong type). Entity IDs must follow the `domain.object_id` pattern.

### Dependency Injection

**`DependencyInjectionError`** The handler signature is invalid. A parameter uses `*args` or is positional-only. Fix the handler signature. (Parameters without type annotations are skipped by injection, not rejected.)

**[`DependencyResolutionError`][hassette.exceptions.DependencyResolutionError]** Injection succeeded at inspection time but failed at runtime while extracting or converting a value. Check the event data and the type annotations in the handler.

### Lifecycle

**`InvalidLifecycleTransitionError`** A resource attempted an invalid status transition. Only raised when `strict_lifecycle = true` in `hassette.toml`. In non-strict mode, the same condition logs a WARNING. Disable strict mode or investigate the resource initialization order.

**`RegistryValidationError`** Startup registry validation found error-level issues (for example, a malformed custom state class). Only raised when `strict_lifecycle = true`; the exception message lists each issue found. In non-strict mode, the same issues log as warnings.

**`AppPrecheckFailedError`** One or more apps failed the precheck. Check the log for the specific app and error. Set `allow_startup_if_app_precheck_fails = true` to let other apps run while you diagnose.

### Configuration

**`SchemaVersionError`** The database was created by a newer version of Hassette than the one currently running. Either upgrade Hassette or delete `hassette.db` to start fresh.

**`CannotOverrideFinalError`** An app class overrides a lifecycle method marked as final (such as `initialize`). Use the public hook (`on_initialize`) instead.

**`InvalidInheritanceError`** An app class inherits from [App][hassette.app.app.App] incorrectly. Check the class definition and the error message for details.

### Framework Base

**[`HassetteError`][hassette.exceptions.HassetteError]** The base class for all Hassette exceptions. Catch this to handle any Hassette-raised error generically.

**`FatalError`** Extends `HassetteError`. Indicates a condition where the service should not restart. Hassette shuts down when this is raised. Subclasses: `CouldNotFindHomeAssistantError`, `InvalidAuthError`, `BaseUrlRequiredError`, `SchemeRequiredInBaseUrlError`, `IPV6NotSupportedError`.
