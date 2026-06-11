# Configuration

All Hassette settings live in `hassette.toml`. Environment variables and CLI flags override TOML values. The configuration controls connection, app discovery (finding and loading your automation classes), the web UI, storage, and runtime behavior.

A minimal `hassette.toml` declares the Home Assistant URL, the apps directory, and one app:

```toml
--8<-- "pages/core-concepts/configuration/snippets/basic_config.toml"
```

The token is the only required credential. `HASSETTE__TOKEN` supplies it via environment variable — put it in a `.env` file next to `hassette.toml` (the recommended setup, covered under Configuration Sources below), keeping the credential out of version control. [Create a Long-Lived Access Token](../../getting-started/ha_token.md) covers token generation.

## Configuration Sources

Hassette loads settings from four sources, applied in this precedence order (highest wins):

1. **CLI flags**, arguments passed to `hassette` at startup
2. **Environment variables**, prefixed with `HASSETTE__`, using `__` as the nested delimiter
3. **`.env` files**, same key names as environment variables
4. **`hassette.toml`**, the primary configuration file

When the same setting appears in multiple sources, the higher-precedence source wins.

`.env` files do double duty: they feed settings resolution and are loaded into `os.environ`, so other libraries see those variables too. `import_dot_env_files = false` limits them to settings resolution only — useful when the process environment is managed externally (a container orchestrator, systemd) and `.env` should not leak into it.

## File Locations

--8<-- "pages/core-concepts/configuration/snippets/file_discovery.md"

!!! tip "Docker"
    In Docker, the configuration volume mounts to `/config`. Hassette checks `/config/hassette.toml` first.

## Authentication

The `token` field accepts four aliases: `token`, `hassette__token`, `ha_token`, and `home_assistant_token`. This means the same token can be supplied under any of those names in any source.

The recommended approach is an environment variable or `.env` file so the token stays out of version control:

```
HASSETTE__TOKEN=your_long_lived_access_token
```

`verify_ssl` controls certificate validation. Setting it to `false` allows connections to Home Assistant instances with self-signed certificates. [Create a Long-Lived Access Token](../../getting-started/ha_token.md) covers step-by-step token generation.

## Configuration Sections

[`HassetteConfig`][hassette.config.HassetteConfig] is the Pydantic settings model that backs `hassette.toml`. It organizes settings into named subsections, each mapping to a TOML table:

| TOML section | Controls |
|---|---|
| `[hassette]` | Connection (`base_url`, `verify_ssl`, `token`), runtime flags, data directory |
| `[hassette.apps]` | App discovery, auto-detection, individual app definitions |
| `[hassette.web_api]` | Web UI and API server host, port, and feature flags |
| `[hassette.database]` | Storage path, retention, and write-queue settings |
| `[hassette.websocket]` | Connection, retry, and recovery timing |
| `[hassette.logging]` | Log level, format, queue, and per-service overrides |
| `[hassette.lifecycle]` | Startup, shutdown, and per-operation timeouts |
| `[hassette.file_watcher]` | Debounce, step timing, and enable/disable |
| `[hassette.scheduler]` | Job delay thresholds and execution timeouts |

App definitions live inside `[hassette.apps]` as named subsections, as shown in the opening example. [App Configuration](../apps/configuration.md) covers registration details and multi-instance configuration.

## Design Notes

The `HassetteConfig` reference covers every field, its type, and its default. The notes below explain the "why" for fields where the field name alone does not make the intent obvious.

### Data Directory and Upgrades

`data_dir` sets the root for all persistent data Hassette writes, including the telemetry database and caches. The default is platform-specific. Changing `data_dir` between major versions requires migrating the existing data manually. No automatic migration runs. `database.path` defaults to a file inside `data_dir` but can be overridden to an independent location.

### App Discovery

`apps.directory` is the root from which Hassette loads app modules. Auto-detection (`apps.autodetect`, default `true`) scans that directory recursively for Python files that define an [`App`](../apps/index.md) subclass — the base class for all Hassette automations.

`extend_exclude_dirs` adds directories to the built-in exclusion list (`.venv`, `venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.git`). `exclude_dirs` replaces it entirely. Setting `exclude_dirs` directly removes the framework defaults and can cause Hassette to scan directories it would normally skip.

`run_app_precheck` controls whether Hassette imports and validates all app modules before starting. When a module fails precheck, Hassette refuses to start. `allow_startup_if_app_precheck_fails` overrides that refusal. Development environments may enable it; production environments benefit from leaving it disabled.

### Event Filtering

`bus_excluded_domains` and `bus_excluded_entities` drop events before any handler sees them — the [bus](../bus/index.md) is Hassette's event delivery system, and handlers are the app functions subscribed to it. Both settings accept glob patterns.

```toml
--8<-- "pages/core-concepts/configuration/snippets/bus_filter_example.toml"
```

Filtering at this level removes the events from every app simultaneously. Per-handler filtering using predicates is more selective. The [`Bus`](../bus/index.md) page covers handler-level options.

`hassette_event_buffer_size` (default 1000) sets the capacity of the internal channel that carries events from the WebSocket to the bus. When the buffer fills, event intake pauses until handlers catch up — events are delayed, not dropped. Raising the buffer absorbs longer bursts; excluding noisy domains is usually the better first move.

### Development and Debugging

`dev_mode` enables additional logging and development features. Hassette sets it automatically when `debugpy` is loaded, when `sys.gettrace()` is non-`None`, or when the interpreter runs with `python -X dev`. Setting it explicitly in `hassette.toml` or via `HASSETTE__DEV_MODE=true` overrides auto-detection.

`asyncio_debug_mode` enables the asyncio event loop's own debug mode, which logs slow callbacks and unawaited coroutines. It runs independently of `dev_mode`.

`web_api.ui_hot_reload` pushes live reloads to the browser when web UI static files change. It serves framework contributors working on the UI itself, not app authors.

`strict_lifecycle` turns three classes of internal warnings into exceptions: invalid resource status transitions and invalid WebSocket connection-state transitions raise `InvalidLifecycleTransitionError`, and startup registry validation issues raise `RegistryValidationError`. The default (`false`) logs WARNING instead. The [test harness](../../testing/harness.md) enables it by default so tests fail loudly. [Troubleshooting](../../troubleshooting.md) covers both exceptions.

`allow_reload_in_prod` enables the file watcher's automatic app reloads outside `dev_mode`. Manual app management (start/stop/reload via the API or web UI) works regardless of this setting.

### File Watcher

The file watcher reloads apps when their source files change (in `dev_mode`, or with `allow_reload_in_prod`). `[hassette.file_watcher]` tunes it: `debounce_milliseconds` (default 3000) is the quiet period required after the last change before a reload fires, `step_milliseconds` (default 500) is how long the watcher waits for additional changes to batch into the same reload, and `watch_files = false` disables watching entirely.

### State Proxy Polling

The [`StateManager`](../states/index.md) — the local entity-state cache apps access via `self.states` — keeps a copy of all entity states. `state_proxy_poll_interval_seconds` controls how often that cache refreshes via a full API pull, supplementing the WebSocket event stream. `disable_state_proxy_polling` turns off the periodic poll entirely, leaving the cache reliant on the event stream alone.

## Verify the Configuration

Run `hassette status` to confirm Hassette can reach Home Assistant with the current config:

```
hassette status
```

A successful connection shows `status: ok` and the installed Hassette version. Auth failures show `websocket_connected: false` with a `degraded` or `starting` status — check the token value and `verify_ssl` setting.

## Full Reference

The [`HassetteConfig`][hassette.config.HassetteConfig] API reference lists every field with its type, default, and description.

## Next Steps

- [App Configuration](../apps/configuration.md): registering apps, passing config values, and multi-instance setup
- [Apps overview](../apps/index.md): defining `AppConfig` models and accessing config values in Python
- [CLI Configuration](../../cli/configuration.md): CLI flags and environment variables for runtime overrides
