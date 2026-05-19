---
task_id: "T01"
title: "Create nested config models and restructure HassetteConfig"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#6", "FR#8", "FR#9", "AC#1", "AC#3", "AC#4", "AC#5", "AC#9"]
---

## Summary

Create the 8 nested BaseModel subclasses that organize HassetteConfig's 94 flat fields into logical groups, then restructure HassetteConfig to compose them as nested fields. This is the foundational task — all other tasks depend on the config structure established here. The config module itself (models, config class, TOML source, dev/prod defaults, validators) must be internally consistent and fully tested before any access site migration begins.

## Prompt

### Step 1: Create `src/hassette/config/models.py`

Create a new file with 8 `BaseModel` subclasses. Each must inherit `ExcludeExtrasMixin` (from `classes.py`) and `BaseModel`. Do NOT inherit `BaseSettings`.

Use the field mapping tables in design.md **## Architecture > Nested model structure** as the authoritative source for field names, types, defaults, and constraints. Key points per model:

**DatabaseConfig** (13 fields): 6 existing config fields (`db_path` → `path`, `db_retention_days` → `retention_days`, etc.) plus 7 new fields promoted from module constants in `database_service.py` (`_HEARTBEAT_INTERVAL_SECONDS` → `heartbeat_interval_seconds`, etc.). See design.md table for exact names, types, defaults, and constraints.

**WebSocketConfig** (13 fields): Strip `websocket_` prefix. All fields are direct renames.

**LoggingConfig** (21 fields): Core `log_*` fields RETAIN the `log_` prefix (`log_level`, `log_format`, `log_queue_max`, `log_persistence_level`, `log_retention_days`). Per-service log levels strip `_log_level` suffix (`database_service_log_level` → `database_service`). The `log_all_*` fields strip the `log_` prefix (`log_all_events` → `all_events`). Per-service log levels default to `None` (not `log_level_default_factory`). Add a `model_validator(mode="after")` that fills `None` values from `self.log_level`. Add a similar validator for `all_hass_events`/`all_hassette_events` defaulting from `all_events`.

**LifecycleConfig** (10 fields): No prefix stripping (fields already have clean names). `resource_shutdown_timeout_seconds` defaults from `app_shutdown_timeout_seconds` via `default_factory`. Add `validate_timeouts()` field_validator for `event_handler_timeout_seconds` and `error_handler_timeout_seconds` (same logic as the current `validate_timeout_seconds` in config.py).

**WebApiConfig** (9 fields): Strip `web_api_` prefix. `run_web_api` → `run`, `run_web_ui` → `run_ui`, `web_ui_hot_reload` → `ui_hot_reload`.

**AppConfig** (6 fields): `autodetect_apps` → `autodetect`, `app_dir` → `directory`, etc. Move the `remove_incomplete_apps` field_validator here. Move `autodetect_exclude_dirs` computed default here.

**SchedulerConfig** (5 fields): Strip `scheduler_` prefix. Add `validate_timeouts()` field_validator for `job_timeout_seconds`.

**FileWatcherConfig** (3 fields): Strip `file_watcher_` prefix. `watch_files` stays as `watch_files`.

Add a one-line docstring to each model class describing what fields belong in it (per design.md Goals).

### Step 2: Restructure `src/hassette/config/config.py`

Replace the flat fields with 8 nested model fields on HassetteConfig. Each nested field gets a default instance (`database: DatabaseConfig = Field(default_factory=DatabaseConfig)`). Keep the 21 root-level fields listed in design.md **Root-level fields remaining (21)** table.

Add `nested_model_default_partial_update=True` to `SettingsConfigDict`.

Update `validate_log_retention_days` to reference `self.logging.log_retention_days` and `self.database.retention_days`.

Remove the `validate_timeout_seconds` field_validator from root (it moves into LifecycleConfig and SchedulerConfig).

Remove per-service log level fields, `log_all_*` fields, and all other fields that moved into groups. Remove validators and computed defaults that moved into group models.

### Step 3: Update `src/hassette/config/classes.py`

Modify `HassetteTomlConfigSettingsSource` so that after extracting `[hassette]`, nested sub-dicts (from `[hassette.database]`, `[hassette.websocket]`, etc.) are preserved in the merged dict, not flattened.

### Step 4: Restructure dev/prod TOML defaults

Update `src/hassette/config/hassette.dev.toml` and `src/hassette/config/hassette.prod.toml`: move the 16 grouped keys into nested sections (`[hassette.websocket]`, `[hassette.scheduler]`, `[hassette.lifecycle]`, `[hassette.file_watcher]`). Keep the 3 root-level keys (`dev_mode`, `allow_startup_if_app_precheck_fails`, `state_proxy_poll_interval_seconds`) directly under `[hassette]`.

Update `model_post_init` in `config.py` to handle nested groups from `get_defaults_dict()`. The existing flat iteration still works for the 3 root-level keys. For grouped keys, iterate group names, retrieve each nested sub-dict, and apply via `setattr(getattr(self, group_name), sub_field, value)`.

### Step 5: Update exports

Update `src/hassette/config/__init__.py` to export all 8 nested model classes.

### Step 6: Write tests

**Unit tests for each model** (new test file `tests/unit/test_config_models.py`):
- Each model constructs with all defaults
- Field constraints (`ge=`, type coercion) are enforced
- Computed defaults work (e.g., `resource_shutdown_timeout_seconds` from `app_shutdown_timeout_seconds`)
- LoggingConfig model_validator fills None per-service levels from log_level
- LoggingConfig model_validator fills all_hass/hassette_events from all_events
- LifecycleConfig and SchedulerConfig timeout validators reject non-positive values
- ExcludeExtrasMixin serialization behavior

**Integration tests for config loading** (extend `tests/unit/test_config.py`):
- TOML with nested sections loads correctly
- `HASSETTE__DATABASE__RETENTION_DAYS=14` overrides only that field (partial update)
- Cross-model validation (`log_retention_days > retention_days` raises ValueError with nested paths)
- Empty TOML sections produce valid models with all defaults
- Dev/prod TOML defaults apply correctly via model_post_init

## Focus

- `src/hassette/config/config.py` (599 lines) — the main file being restructured. All 94 fields are here.
- `src/hassette/config/classes.py` (213 lines) — `HassetteTomlConfigSettingsSource` at lines 24-48, `ExcludeExtrasMixin` at lines 51-96.
- `src/hassette/config/helpers.py` (186 lines) — `log_level_default_factory` at line 173 reads `data.get("log_level")`. Within LoggingConfig this works unchanged because the field is still named `log_level`. Do NOT modify this function.
- `src/hassette/config/defaults.py` — `get_defaults_from_toml()` returns a flat dict from TOML files. After restructuring the TOMLs, it returns nested dicts. `get_defaults_dict()` just delegates.
- `src/hassette/config/__init__.py` — currently exports `AppManifest` and `HassetteConfig` only.
- `tests/unit/test_config.py` — comprehensive config tests (55 config accesses). Some will break from field renames. Fix them as part of this task.
- `tests/unit/test_config_log_level.py` — tests for log level defaults (22 accesses). Will need updates for the LoggingConfig model_validator pattern.
- The `autodetect_exclude_dirs` field has a `default_factory` that uses Pydantic's `data` parameter to access sibling fields. This pattern works within a model but verify it in AppConfig context.
- `LOG_ANNOTATION` type alias (line 32 of config.py) is used by LoggingConfig's per-service fields. Import it in models.py or move its definition.

## Verify
- [ ] FR#1: 8 nested model groups exist in `src/hassette/config/models.py` (DatabaseConfig, WebSocketConfig, LoggingConfig, LifecycleConfig, WebApiConfig, AppConfig, SchedulerConfig, FileWatcherConfig)
- [ ] FR#2: `config.database.path`, `config.websocket.heartbeat_interval_seconds`, `config.logging.log_level` return their expected default values without AttributeError on a default-constructed HassetteConfig
- [ ] FR#3: A TOML file with `[hassette.database]`, `[hassette.websocket]`, `[hassette.logging]` sections loads without error and the loaded field values match the values set in the TOML file
- [ ] FR#4: Setting `HASSETTE__DATABASE__RETENTION_DAYS=14` as an environment variable causes `config.database.retention_days` to equal `14` after construction
- [ ] FR#5: Setting `HASSETTE__DATABASE__RETENTION_DAYS=14` does not replace other database defaults (e.g., `config.database.max_size_mb` remains `500`, `config.database.write_queue_max` remains `2000`)
- [ ] FR#6: `logging.log_retention_days > database.retention_days` raises a ValueError referencing both nested paths
- [ ] FR#8: 21 cross-cutting fields remain directly on HassetteConfig root (config_file, env_file, dev_mode, base_url, verify_ssl, token, config_dir, data_dir, etc.)
- [ ] FR#9: All 8 nested model classes inherit BaseModel (not BaseSettings)
- [ ] AC#1: Root-level field count is ~21 cross-cutting fields plus 8 group fields
- [ ] AC#3: TOML with nested sections loads without error and produces correct field values
- [ ] AC#4: `HASSETTE__DATABASE__RETENTION_DAYS=14` sets only that field; other database defaults remain
- [ ] AC#5: Cross-model validation error message references nested paths (e.g., `logging.log_retention_days`, `database.retention_days`)
- [ ] AC#9: `issubclass(DatabaseConfig, BaseModel)` is True and `issubclass(DatabaseConfig, BaseSettings)` is False for all 8 models
