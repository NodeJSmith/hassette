# Configuration

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Configure Hassette to connect to Home Assistant, set up app discovery, and understand where settings live.

## What was cut (and where it goes)

- **auth.md as a separate page** — absorbed. Token setup is 2 paragraphs, not a page. The reader who needs to configure Hassette should not have to navigate to a separate page for the most common first-time task.
- **global.md as a separate page** — replaced by auto-generated `HassetteConfig` API reference. The existing global.md is a 300-line hand-maintained field listing that duplicates what mkdocstrings generates. The teaching content (WebSocket resilience, timeout behavior) moves to Operating/overview.md. The overview page keeps brief design-rationale notes for fields where the "why" is not obvious from the field name and type.
- **Credentials section** — absorbed into Authentication. The existing page had a "Credentials" section that just said "see Authentication." One indirection removed.

## Outline

### (Opening)
All Hassette settings live in `hassette.toml`. Environment variables and CLI flags override TOML values. The configuration controls connection, app discovery, the web UI, storage, and runtime behavior.

### H2: Configuration Sources
Priority order (highest wins): CLI flags -> env vars (`HASSETTE__` prefix, `__` nested delimiter) -> `.env` files -> `hassette.toml`. When the same setting appears in multiple sources, the higher-precedence source wins.

### H2: File Locations
TOML and `.env` discovery paths. Docker `/config/` paths checked first. CLI flags `--config-file` / `--env-file` override discovery.

### H2: Authentication
Token field accepts four aliases: `token`, `hassette__token`, `ha_token`, `home_assistant_token`. Recommended: `HASSETTE__TOKEN` env var or `.env` file. Never commit tokens. `verify_ssl = false` for self-signed certs. Link to Getting Started HA Token page for step-by-step creation.

### H2: Configuration Sections
Brief map of what is configurable, with links:
- Connection: `base_url`, `verify_ssl`
- Apps: -> Applications page
- Web UI: `[hassette.web_api]`
- Database: `[hassette.database]`
- WebSocket: `[hassette.websocket]`
- Logging: `[hassette.logging]`
- Lifecycle: `[hassette.lifecycle]`
- File Watcher: `[hassette.file_watcher]`
- Scheduler: `[hassette.scheduler]`

### H2: Design Notes
Brief rationale for fields where the auto-generated reference does not explain the "why." Each H3 is 1-3 sentences. Readers looking for field types and defaults go to the auto-generated reference.

#### H3: Data Directory and Upgrades
`data_dir` path, major version implications, cache path derivation.

#### H3: App Discovery
`apps.directory`, `extend_exclude_dirs` vs `exclude_dirs` footgun, precheck behavior.

#### H3: Event Filtering
`bus_excluded_domains` and `bus_excluded_entities` — glob patterns to drop events before handlers.

#### H3: Development and Debugging
`dev_mode` auto-detection, `asyncio_debug_mode`, `ui_hot_reload`.

#### H3: State Proxy Polling
`state_proxy_poll_interval_seconds` and `disable_state_proxy_polling`.

### H2: Full Reference
Link to auto-generated API reference for `HassetteConfig` and all sub-models.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `file_discovery.md` | Keep | H2: File Locations (included via --8<--) |
| `basic_config.toml` | Keep | Could use as opening example |
| `storage_example.toml` | Drop | Covered by auto-generated reference |
| `web_ui_example.toml` | Drop | Covered by auto-generated reference |
| `database_example.toml` | Drop | Covered by auto-generated reference |
| `bus_filter_example.toml` | Keep | H3: Event Filtering |

## Cross-Links

- **Links to:** Applications (app registration), Auto-generated HassetteConfig reference, Operating/overview (WebSocket resilience, timeouts), HA Token (getting-started)
- **Linked from:** Architecture, Getting Started, Operating

## Structural Notes

- **auth.md absorbed** — token aliases and SSL verification folded into Authentication section
- **global.md replaced** — field listings move to auto-generated reference; teaching content (WebSocket resilience, timeout behavior) moves to Operating/overview.md
- **Requires:** adding `hassette.config.models` and `hassette.config.config` to `PUBLIC_MODULES` in `tools/gen_ref_pages.py`
