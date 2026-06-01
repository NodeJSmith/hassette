# Operating Hassette — Log Level Tuning

**Status:** Stub (3 lines), content moving from Advanced (99 lines)
**Voice mode:** Procedural — "you" allowed, step-by-step
**Content source:** `docs/pages/advanced/log-level-tuning.md` + KI-03

## Outline

### H2: When to Use This
Debug a specific area without flooding logs. Brief.

### H2: How It Works
`[hassette.logging]` section in hassette.toml. Per-service granularity.

### H2: Available Fields
Link to auto-generated `LoggingConfig` reference for the full field list (avoids hardcoding names that may change). Provide 2-3 inline examples of the most common ones (`websocket`, `bus_service`, `scheduler_service`) to orient the reader, but don't enumerate all 13+.

### H2: Fallback Behavior
Unset fields use global log level.

### H2: Debug Flags
`all_events`, `all_hass_events`, `all_hassette_events` — boolean flags for bus debug verbosity. `log_format` (`"auto"`, `"console"`, `"json"`) for output format.

### H2: Per-App Log Levels
Set in the app config block under `[hassette.apps.<key>.config]`, not in `[hassette.logging]`.

### H2: Examples
#### H3: Debugging the Scheduler
#### H3: Quieting the File Watcher
#### H3: Debugging Home Assistant Communication

## Snippet Inventory

Moving from `advanced/snippets/log-level-tuning/`:
| Snippet | Status | Notes |
|---|---|---|
| `basic_example.toml` | Move | → `operating/snippets/` |
| `debug_scheduler.toml` | Move | |
| `quiet_file_watcher.toml` | Move | |
| `debug_ha_comms.toml` | Move | |
| `per_app_log_level.toml` | Move | |

## Cross-Links

- **Links to:** Operating overview, Configuration/Global (logging settings)
- **Linked from:** Operating overview, Web UI/Logs
