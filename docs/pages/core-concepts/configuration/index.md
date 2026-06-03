# Configuration

All Hassette settings live in `hassette.toml`. Environment variables and CLI flags override TOML values. The configuration controls connection, app discovery, the web UI, storage, and runtime behavior.

## Configuration Sources

Hassette loads settings from four sources, applied in this precedence order (highest wins):

1. **CLI flags**, arguments passed to `hassette` at startup
2. **Environment variables**, prefixed with `HASSETTE__`, using `__` as the nested delimiter
3. **`.env` files**, same key names as environment variables
4. **`hassette.toml`**, the primary configuration file

When the same setting appears in multiple sources, the higher-precedence source wins.

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

[`HassetteConfig`][hassette.config.HassetteConfig] organizes settings into named subsections. Each maps to a TOML table:

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

App definitions live inside `[hassette.apps]` as named subsections:

```toml
--8<-- "pages/core-concepts/configuration/snippets/basic_config.toml"
```

[App Configuration](../apps/configuration.md) covers app registration details and multi-instance configuration.

## Design Notes

The `HassetteConfig` reference covers every field, its type, and its default. The notes below explain the "why" for fields where the field name alone does not make the intent obvious.

### Data Directory and Upgrades

`data_dir` sets the root for all persistent data Hassette writes, including the telemetry database and caches. The default is platform-specific. Changing `data_dir` between major versions requires migrating the existing data manually. No automatic migration runs. `database.path` defaults to a file inside `data_dir` but can be overridden to an independent location.

### App Discovery

`apps.directory` is the root from which Hassette loads app modules. Auto-detection (`apps.autodetect`, default `true`) scans that directory recursively for Python files that define an `App` subclass.

`extend_exclude_dirs` adds directories to the built-in exclusion list. `exclude_dirs` replaces it entirely. Setting `exclude_dirs` directly removes the framework defaults and can cause Hassette to scan directories it would normally skip.

`run_app_precheck` controls whether Hassette imports and validates all app modules before starting. When a module fails precheck, Hassette refuses to start. `allow_startup_if_app_precheck_fails` overrides that refusal. Development environments may enable it; production environments should not.

### Event Filtering

`bus_excluded_domains` and `bus_excluded_entities` drop events before any handler sees them. Both accept glob patterns.

```toml
--8<-- "pages/core-concepts/configuration/snippets/bus_filter_example.toml"
```

Filtering at this level removes the events from every app simultaneously. Per-handler filtering using predicates is more selective. The [`Bus`](../bus/index.md) page covers handler-level options.

### Development and Debugging

`dev_mode` enables additional logging and development features. Hassette sets it automatically when `debugpy` is loaded, when `sys.gettrace()` is non-`None`, or when the interpreter runs with `python -X dev`. Setting it explicitly in `hassette.toml` or via `HASSETTE__DEV_MODE=true` overrides auto-detection.

`asyncio_debug_mode` enables the asyncio event loop's own debug mode, which logs slow callbacks and unawaited coroutines. It runs independently of `dev_mode`.

`web_api.ui_hot_reload` pushes live reloads to the browser when web UI static files change. It serves framework contributors working on the UI itself, not app authors.

### State Proxy Polling

The `StateManager` keeps a local cache of entity states. `state_proxy_poll_interval_seconds` controls how often that cache refreshes via a full API pull, supplementing the WebSocket event stream. `disable_state_proxy_polling` turns off the periodic poll entirely, leaving the cache reliant on the event stream alone.

## Full Reference

The `HassetteConfig` API reference lists every field with its type, default, and description.
