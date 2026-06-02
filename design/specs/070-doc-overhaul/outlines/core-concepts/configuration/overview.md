# Configuration — Overview

**Status:** Exists (46 lines) + absorbing auth.md (43 lines) + teaching content from global.md (~90 lines). Rewrite needed.
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Configuration Sources
Priority order (highest wins): init kwargs → env vars (`HASSETTE__` prefix, `__` nested delimiter) → dotenv (.env) → file secrets → hassette.toml. TOML is the base; env vars override it.

### H2: File Locations
TOML: `/config/hassette.toml`, `hassette.toml`, `./config/hassette.toml`. `.env`: `/config/.env`, `.env`, `./config/.env`. Docker `/config/` paths are checked first. CLI flags `--config-file` / `--env-file` override discovery.

### H2: Authentication
Token field accepts four aliases: `token`, `hassette__token`, `ha_token`, `home_assistant_token`. Set via env var or .env file. `verify_ssl` for self-signed certs. `import_dot_env_files` controls whether .env values are also injected into `os.environ`. Link to HA Token getting-started page for step-by-step.

### H2: Configuration Sections
Brief map of what's configurable, linking to the auto-generated reference for field details:
- Connection: `base_url`, `verify_ssl`
- Apps: → Applications page
- Web UI: `[hassette.web_api]`
- Database: `[hassette.database]`
- WebSocket: `[hassette.websocket]`
- Logging: `[hassette.logging]`
- Lifecycle: `[hassette.lifecycle]`
- File Watcher: `[hassette.file_watcher]`
- Scheduler: `[hassette.scheduler]`

### H2: Operational Tuning Guidance
Teaching content that can't come from auto-generated reference — explain the design, not just the fields:

#### H3: WebSocket Resilience
Three-layer retry model (connect retries → early-drop retries → ServiceWatcher budget). When to tune each layer. `max_recovery_seconds` as the total wall-clock cap.

#### H3: Timeout Behavior
Timeout enforcement limitations: sync handlers can't be interrupted mid-execution (the timeout fires but the handler continues). `TimeoutError` swallowing behavior. `run_sync_timeout_seconds` default (6s).

#### H3: Data Directory and Upgrades
`data_dir` path, major version implications, cache path derivation (`data_dir/<ClassName>/cache`).

#### H3: App Discovery
`apps.directory`, `extend_exclude_dirs` vs `exclude_dirs` footgun, `run_app_precheck` and `allow_startup_if_app_precheck_fails`.

#### H3: Event Filtering
`bus_excluded_domains` and `bus_excluded_entities` — glob patterns to silently drop events before they reach handlers. Common use: filtering noisy domains like `sensor` during development. Cross-link to troubleshooting KI-06 for the "handler never runs" pitfall.

#### H3: Development and Debugging
`dev_mode` — auto-detected from debugger attachment or `python -X dev`; enables extra diagnostics. `asyncio_debug_mode` — enables asyncio debug mode for coroutine tracing. `ui_hot_reload` — live reloading of web UI files during development.

#### H3: Web API
`cors_origins` — allowed CORS origins for the REST API.

#### H3: Cache
`default_cache_size` — size limit for per-resource disk caches.

#### H3: State Proxy Polling
`state_proxy_poll_interval_seconds` and `disable_state_proxy_polling` — control the StateProxy's background polling of HA state. Disabling polling means the cache only updates via the WebSocket event stream.

### H2: Full Reference
Link to auto-generated API reference for `HassetteConfig` and all sub-models. All fields, types, defaults, and descriptions are maintained in the source code and rendered automatically.

## Snippet Inventory

No code snippets — TOML examples are inline.

## Cross-Links

- **Links to:** Applications (app registration), Auto-generated HassetteConfig reference, Operating/Log Levels (log tuning in practice), HA Token (getting-started)
- **Linked from:** Architecture, Getting Started (Quickstart, Docker Setup), Operating

## Structural Notes

- **auth.md absorbed** — token aliases and SSL verification folded into Authentication section above
- **global.md replaced** — field listings move to auto-generated reference; ~90 lines of teaching content (WebSocket resilience, timeout behavior, data directory) kept in Operational Tuning Guidance
- **Requires:** adding `hassette.config.models` and `hassette.config.config` to `PUBLIC_MODULES` in `tools/gen_ref_pages.py`
