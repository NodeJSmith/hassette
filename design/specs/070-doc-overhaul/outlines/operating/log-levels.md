# Operating Hassette — Log Level Tuning

**Page type:** Operating (procedural reference)
**Reader's job:** Narrow log noise to debug a specific area without flooding output from everything else.
**Voice mode:** Procedural — "you" allowed, action-first

## What was cut (and where it goes)

- **Full 13-field table** replaced by a symptom-lookup table and a link to the `LoggingConfig` API reference. The existing page listed all 13 fields in a static table that drifts when fields are added. The reader's actual question is "my scheduler is misbehaving, which field do I set?" — a symptom table answers that directly.

## Outline

### H2: Symptom Lookup
Lead with the action. Table: Symptom | Field to set. The reader has a specific problem; this table tells them which knob to turn. Cover the 8 most common symptoms (events not firing, jobs not running, app not loading, stale state, WS errors, API latency, noisy file changes, web UI errors).

### H2: How It Works
`[hassette.logging]` section in `hassette.toml`. Set a per-service field to a log level string (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). Unset fields inherit the global `log_level` (default `INFO`). One basic TOML snippet.

### H2: Debug Flags
Boolean flags for bus debug verbosity: `all_events`, `all_hass_events`, `all_hassette_events`. Output format: `log_format` (`"auto"`, `"console"`, `"json"`). Database persistence level: `log_persistence_level`.

### H2: Per-App Log Levels
Set in `[hassette.apps.<key>.config]`, not in `[hassette.logging]`. The `logging.apps` field sets the default for all apps; per-app config overrides it. One TOML snippet.

### H2: Examples
Three concrete examples, each a TOML snippet with one sentence of explanation:
- Debugging the scheduler
- Quieting the file watcher
- Debugging Home Assistant communication

### H2: Full Field Reference
Link to auto-generated `LoggingConfig` API reference for the complete field list. Avoids hardcoding names that change.

## Snippet Inventory

Moving from `advanced/snippets/log-level-tuning/` to `operating/snippets/`:

| Snippet | Decision | Notes |
|---|---|---|
| `basic_example.toml` | Move | Basic per-service override |
| `debug_scheduler.toml` | Move | Scheduler debugging |
| `quiet_file_watcher.toml` | Move | Suppress file watcher noise |
| `debug_ha_comms.toml` | Move | WebSocket + API debugging |
| `per_app_log_level.toml` | Move | Per-app override |

## Cross-Links

- **Links to:** Operating overview, Configuration/Global (logging settings), `LoggingConfig` API reference
- **Linked from:** Operating overview, Web UI/Logs, Troubleshooting
