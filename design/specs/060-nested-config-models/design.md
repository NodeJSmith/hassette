# Design: Migrate HassetteConfig to Nested Pydantic Models

**Date:** 2026-05-19
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-05-01-config-class-organization/research.md

## Problem

The framework's configuration is a single flat class with 94 fields. Related settings are distinguished only by naming convention (prefix-based grouping), making the config hard to navigate, reason about, and extend. Adding new fields exacerbates the problem — there is no structure to guide where a new setting belongs. Users configuring the framework in TOML or environment variables face a flat list with no logical grouping.

Separately, 7 operational parameters in the database service are hardcoded as module-level constants. Users running on constrained hardware (Raspberry Pi) or high-traffic deployments cannot tune these values without modifying source code.

## Goals

- Organize configuration into logical groups so users can find and understand related settings together
- Provide structured TOML sections that mirror the internal model hierarchy
- Promote hardcoded database service constants to configurable fields with safe defaults
- Each nested model group has a docstring describing what fields belong in it, so developers adding new config fields can identify the correct group without reading existing fields
- Reduce root-level field count from 94 to ~21 cross-cutting fields

## User Scenarios

### Framework user: Home automation developer

- **Goal:** Configure hassette for their Home Assistant setup
- **Context:** Writing `hassette.toml` and/or setting environment variables

#### Configuring database retention

1. **Opens hassette.toml to adjust retention**
   - Sees: A `[database]` section grouping all database settings together
   - Decides: Sets `retention_days = 14` under `[database]`
   - Then: Hassette loads the nested section and applies validation

2. **Overrides a single field via environment variable**
   - Sees: Documentation showing `HASSETTE__DATABASE__RETENTION_DAYS=14`
   - Decides: Sets the env var in their Docker Compose file
   - Then: Pydantic merges the override into the nested model without replacing other database defaults

#### Tuning database operational intervals on a Raspberry Pi

1. **Wants to reduce heartbeat frequency to save resources**
   - Sees: `heartbeat_interval_seconds = 300` under `[database]` with its default
   - Decides: Increases to `600` to reduce I/O on constrained hardware
   - Then: Database service reads the configured value instead of the hardcoded constant

### Developer: Hassette contributor

- **Goal:** Add a new configuration field to hassette
- **Context:** Extending the framework with a new feature that needs user-configurable behavior

#### Adding a new websocket field

1. **Determines where the field belongs**
   - Sees: `WebSocketConfig` model in `src/hassette/config/models.py` with all websocket fields grouped
   - Decides: Adds the field to `WebSocketConfig` with a default and Field metadata
   - Then: The field is automatically available in TOML under `[websocket]` and as `HASSETTE__WEBSOCKET__<FIELD>`

## Functional Requirements

- **FR#1** Configuration is organized into 8 nested model groups: database, websocket, logging, lifecycle, web API, app, scheduler, and file watcher
- **FR#2** Each group is accessible as a nested attribute on the root configuration object
- **FR#3** TOML configuration files use section headers matching the nested model names
- **FR#4** Environment variables use double-underscore delimiters to address nested fields
- **FR#5** Setting a single environment variable for a nested field does not replace the entire group's defaults
- **FR#6** Cross-group validation rules enforce constraints spanning multiple nested models
- **FR#7** Seven hardcoded database service operational constants are promoted to configurable fields with their current values as defaults
- **FR#8** Fields that do not belong to any group remain directly on the root configuration
- **FR#9** Nested model groups are defined as standard model subclasses, not settings subclasses
- **FR#10** The test factory supports creating configuration with nested model field overrides

## Edge Cases

- **Partial env var override**: Setting `HASSETTE__DATABASE__RETENTION_DAYS=14` must only override that single field, not replace the entire database group with defaults + that one override. Requires `nested_model_default_partial_update=True`.
- **TOML source with [hassette] wrapper**: The current TOML source flattens `[hassette]` into top-level. With nested models, `[hassette.database]` must be preserved as a nested dict, not flattened.
- **Computed defaults across nesting**: `resource_shutdown_timeout_seconds` defaults to `app_shutdown_timeout_seconds`. Both will be in `LifecycleConfig` so this stays internal. `log_all_hass_events` and `log_all_hassette_events` default from `log_all_events` — same situation within `LoggingConfig`.
- **Per-service log level defaults**: Each `*_log_level` field defaults to the global `level`. Within `LoggingConfig`, these can default to `None` and a model validator fills them from `self.level`.
- **CLI argument mapping**: HassetteConfig uses `cli_kebab_case=True` and `cli_shortcuts`. Nested models change the CLI argument paths (e.g., `--database.path` or `--database-path`). Verify CLI parsing still works.
- **ExcludeExtrasMixin inheritance**: Nested models must inherit the mixin to prevent accidental serialization of extra fields.
- **Empty TOML sections**: A `[database]` section with no keys should produce a valid `DatabaseConfig` with all defaults, not fail.

## Acceptance Criteria

- **AC#1** Root configuration field count is reduced to ~21 cross-cutting fields (FR#1, FR#8)
- **AC#2** `config.database.path`, `config.websocket.heartbeat_interval_seconds`, and similar nested access paths work correctly (FR#2)
- **AC#3** A TOML file with `[database]` / `[websocket]` / `[logging]` sections loads correctly (FR#3)
- **AC#4** `HASSETTE__DATABASE__RETENTION_DAYS=14` sets only that field without replacing other database defaults (FR#4, FR#5)
- **AC#5** `log_retention_days > db_retention_days` raises a validation error referencing both nested paths (FR#6)
- **AC#6** Database service reads all 7 operational parameters from config instead of module constants (FR#7)
- **AC#7** `make_test_config(database={"retention_days": 14})` or equivalent nested override syntax works (FR#10)
- **AC#8** All existing tests pass with the new config structure (no regressions)
- **AC#9** Nested model subclasses use standard model base, not settings base (FR#9)
- **AC#10** Pyright type checking passes with no new errors

## Key Constraints

- Nested model groups MUST inherit from `BaseModel`, not `BaseSettings`. If a sub-model inherits `BaseSettings`, Pydantic initializes it independently, ignoring the parent prefix — causing un-prefixed environment variables to leak into the model (Prefect issue #15943).
- Do not introduce backward compatibility shims for Python field names. However, add `AliasChoices` on nested fields for documented env vars that appear in Docker guides and user-facing docs (`HASSETTE__APP_DIR` → `app.directory`, `HASSETTE__LOG_LEVEL` → `logging.level`). Env var aliases are low-cost and protect real Docker users.
- `nested_model_default_partial_update=True` MUST be set in `model_config`. Without it, a single env var override replaces the entire nested model default.

## Dependencies and Assumptions

- **pydantic-settings >=2.6.0** for `nested_model_default_partial_update` support (project has 2.11.0 installed)
- Assumes no external consumers depend on the flat field names (confirmed: no real users)
- The `HassetteTomlConfigSettingsSource` custom class will need modification to handle nested TOML sections

## Architecture

### Nested model structure

Extract 8 `BaseModel` subclasses from `HassetteConfig`. Each becomes a field on the root with a default instance. All nested models inherit `ExcludeExtrasMixin`.

Field naming: strip the group prefix when moving to a nested model. `db_retention_days` becomes `database.retention_days`. `websocket_heartbeat_interval_seconds` becomes `websocket.heartbeat_interval_seconds`. Exception: core `LoggingConfig` fields that start with `log_` retain the prefix (e.g., `log_level`, `log_format`, `log_retention_days`) so the shared `log_level_default_factory` works unchanged for both `LoggingConfig` and `AppConfig`. The `log_all_*` boolean fields strip the `log_` prefix (→ `all_events`, `all_hass_events`, `all_hassette_events`) because they don't use the factory and the stripped names are clearer.

**DatabaseConfig** (13 fields — `src/hassette/config/models.py`):

| Nested name | Old name / source | Type | Default | Constraint |
|---|---|---|---|---|
| `path` | `db_path` | `Path \| None` | `None` | — |
| `retention_days` | `db_retention_days` | `int` | `7` | `ge=1` |
| `max_size_mb` | `db_max_size_mb` | `float` | `500` | `ge=0` |
| `migration_timeout_seconds` | `db_migration_timeout_seconds` | `int` | `120` | `ge=10` |
| `write_queue_max` | `db_write_queue_max` | `int` | `2000` | `ge=1` |
| `telemetry_write_queue_max` | `telemetry_write_queue_max` | `int` | `1000` | `ge=1` |
| `heartbeat_interval_seconds` | `_HEARTBEAT_INTERVAL_SECONDS` constant | `int` | `300` | `ge=10` |
| `retention_interval_seconds` | `_RETENTION_INTERVAL_SECONDS` constant | `int` | `3600` | `ge=60` |
| `size_failsafe_interval_seconds` | `_SIZE_FAILSAFE_INTERVAL_SECONDS` constant | `int` | `3600` | `ge=60` |
| `size_failsafe_max_iterations` | `_SIZE_FAILSAFE_MAX_ITERATIONS` constant | `int` | `10` | `ge=1` |
| `size_failsafe_delete_batch` | `_SIZE_FAILSAFE_DELETE_BATCH` constant | `int` | `1000` | `ge=1` |
| `size_failsafe_vacuum_pages` | `_SIZE_FAILSAFE_VACUUM_PAGES` constant | `int` | `100` | `ge=1` |
| `max_consecutive_heartbeat_failures` | `_MAX_CONSECUTIVE_HEARTBEAT_FAILURES` constant | `int` | `3` | `ge=1` |

**WebSocketConfig** (13 fields):

| Nested name | Old name | Type | Default |
|---|---|---|---|
| `authentication_timeout_seconds` | `websocket_authentication_timeout_seconds` | `int` | `10` |
| `response_timeout_seconds` | `websocket_response_timeout_seconds` | `int` | `15` |
| `connection_timeout_seconds` | `websocket_connection_timeout_seconds` | `int` | `5` |
| `total_timeout_seconds` | `websocket_total_timeout_seconds` | `int` | `30` |
| `heartbeat_interval_seconds` | `websocket_heartbeat_interval_seconds` | `int` | `30` |
| `connect_retry_max_attempts` | `websocket_connect_retry_max_attempts` | `int` | `5` |
| `connect_retry_initial_wait_seconds` | `websocket_connect_retry_initial_wait_seconds` | `float` | `1.0` |
| `connect_retry_max_wait_seconds` | `websocket_connect_retry_max_wait_seconds` | `float` | `32.0` |
| `early_drop_stable_window_seconds` | `websocket_early_drop_stable_window_seconds` | `float` | `30.0` |
| `early_drop_max_retries` | `websocket_early_drop_max_retries` | `int` | `5` |
| `early_drop_backoff_initial_seconds` | `websocket_early_drop_backoff_initial_seconds` | `float` | `2.0` |
| `early_drop_backoff_max_seconds` | `websocket_early_drop_backoff_max_seconds` | `float` | `60.0` |
| `max_recovery_seconds` | `websocket_max_recovery_seconds` | `float` | `300.0` |

**LoggingConfig** (21 fields):

| Nested name | Old name | Type | Default |
|---|---|---|---|
| `log_level` | `log_level` | `LOG_ANNOTATION` | `"INFO"` |
| `log_format` | `log_format` | `Literal["auto", "console", "json"]` | `"auto"` |
| `log_queue_max` | `log_queue_max` | `int` | `2000` |
| `log_persistence_level` | `log_persistence_level` | `LOG_ANNOTATION` | `"INFO"` |
| `log_retention_days` | `log_retention_days` | `int` | `3` |
| `database_service` | `database_service_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `bus_service` | `bus_service_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `scheduler_service` | `scheduler_service_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `app_handler` | `app_handler_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `web_api` | `web_api_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `websocket` | `websocket_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `service_watcher` | `service_watcher_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `file_watcher` | `file_watcher_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `task_bucket` | `task_bucket_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `command_executor` | `command_executor_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `apps` | `apps_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `state_proxy` | `state_proxy_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `api` | `api_log_level` | `LOG_ANNOTATION \| None` | `None` |
| `all_events` | `log_all_events` | `bool` | `False` |
| `all_hass_events` | `log_all_hass_events` | `bool` | computed from `all_events` |
| `all_hassette_events` | `log_all_hassette_events` | `bool` | computed from `all_events` |

Per-service log levels default to `None`. A `model_validator(mode="after")` on `LoggingConfig` fills `None` values with `self.log_level`. The field keeps its `log_level` name (not stripped to `level`) so the shared `log_level_default_factory` in `helpers.py` works unchanged for both `LoggingConfig` and `AppConfig` — no factory split needed.

**LifecycleConfig** (10 fields):

| Nested name | Old name | Type | Default |
|---|---|---|---|
| `startup_timeout_seconds` | `startup_timeout_seconds` | `int` | `30` |
| `app_startup_timeout_seconds` | `app_startup_timeout_seconds` | `int` | `20` |
| `app_shutdown_timeout_seconds` | `app_shutdown_timeout_seconds` | `int` | `10` |
| `resource_shutdown_timeout_seconds` | `resource_shutdown_timeout_seconds` | `int` | computed from `app_shutdown_timeout_seconds` |
| `total_shutdown_timeout_seconds` | `total_shutdown_timeout_seconds` | `int` | `30` |
| `registration_await_timeout` | `registration_await_timeout` | `int` | `30` |
| `event_handler_timeout_seconds` | `event_handler_timeout_seconds` | `float \| None` | `600.0` |
| `error_handler_timeout_seconds` | `error_handler_timeout_seconds` | `float \| None` | `5.0` |
| `run_sync_timeout_seconds` | `run_sync_timeout_seconds` | `int` | `6` |
| `task_cancellation_timeout_seconds` | `task_cancellation_timeout_seconds` | `int` | `5` |

**WebApiConfig** (9 fields):

| Nested name | Old name | Type | Default |
|---|---|---|---|
| `run` | `run_web_api` | `bool` | `True` |
| `run_ui` | `run_web_ui` | `bool` | `True` |
| `ui_hot_reload` | `web_ui_hot_reload` | `bool` | `False` |
| `host` | `web_api_host` | `str` | `"0.0.0.0"` |
| `port` | `web_api_port` | `int` | `8126` |
| `cors_origins` | `web_api_cors_origins` | `tuple[str, ...]` | `("http://localhost:3000", "http://localhost:5173")` |
| `event_buffer_size` | `web_api_event_buffer_size` | `int` | `500` |
| `log_buffer_size` | `web_api_log_buffer_size` | `int` | `2000` |
| `job_history_size` | `web_api_job_history_size` | `int` | `1000` |

**AppConfig** (6 fields):

| Nested name | Old name | Type | Default |
|---|---|---|---|
| `autodetect` | `autodetect_apps` | `bool` | `True` |
| `extend_exclude_dirs` | `extend_autodetect_exclude_dirs` | `tuple[str, ...]` | `()` |
| `exclude_dirs` | `autodetect_exclude_dirs` | `tuple[str, ...]` | computed |
| `manifests` | `app_manifests` | `dict[str, AppManifest]` | `{}` |
| `apps` | `apps` | `dict[str, RawAppDict]` | `{}` |
| `directory` | `app_dir` | `Path` | computed |

**SchedulerConfig** (5 fields):

| Nested name | Old name | Type | Default |
|---|---|---|---|
| `min_delay_seconds` | `scheduler_min_delay_seconds` | `int` | `1` |
| `max_delay_seconds` | `scheduler_max_delay_seconds` | `int` | `30` |
| `default_delay_seconds` | `scheduler_default_delay_seconds` | `int` | `15` |
| `behind_schedule_threshold_seconds` | `scheduler_behind_schedule_threshold_seconds` | `int` | `5` |
| `job_timeout_seconds` | `scheduler_job_timeout_seconds` | `float \| None` | `600.0` |

**FileWatcherConfig** (3 fields):

| Nested name | Old name | Type | Default |
|---|---|---|---|
| `debounce_milliseconds` | `file_watcher_debounce_milliseconds` | `int` | `3000` |
| `step_milliseconds` | `file_watcher_step_milliseconds` | `int` | `500` |
| `watch_files` | `watch_files` | `bool` | `True` |

**Root-level fields remaining (21):**

| Field | Type | Default | Why root |
|---|---|---|---|
| `config_file` | `Path \| str \| None` | `Path("hassette.toml")` | Bootstrap — needed before config loads |
| `env_file` | `Path \| str \| None` | `Path(".env")` | Bootstrap |
| `dev_mode` | `bool` | computed | Cross-cutting mode flag |
| `base_url` | `str` | `"http://127.0.0.1:8123"` | HA connection — cross-cutting |
| `verify_ssl` | `bool` | `True` | HA connection |
| `token` | `str` | required | HA connection |
| `config_dir` | `Path` | computed | Framework-wide — used by config loading |
| `data_dir` | `Path` | computed | Framework-wide — used by DB service, resource caches, config endpoint |
| `import_dot_env_files` | `bool` | `True` | Bootstrap behavior |
| `run_app_precheck` | `bool` | `True` | Startup behavior |
| `allow_startup_if_app_precheck_fails` | `bool` | `False` | Startup behavior |
| `hassette_event_buffer_size` | `int` | `1000` | Internal routing (no clean group) |
| `default_cache_size` | `int` | `100 * 1024 * 1024` | No clean group |
| `strict_lifecycle` | `bool` | `False` | Cross-cutting mode flag |
| `asyncio_debug_mode` | `bool` | `False` | Cross-cutting debug flag |
| `state_proxy_poll_interval_seconds` | `int` | `30` | No clean group (2 fields) |
| `disable_state_proxy_polling` | `bool` | `False` | No clean group |
| `bus_excluded_domains` | `tuple[str, ...]` | `()` | No clean group (2 fields) |
| `bus_excluded_entities` | `tuple[str, ...]` | `()` | No clean group |
| `allow_reload_in_prod` | `bool` | `False` | Cross-cutting mode flag |
| `allow_only_app_in_prod` | `bool` | `False` | Cross-cutting mode flag |

### model_config changes

Add `nested_model_default_partial_update=True` to `SettingsConfigDict` so individual env var overrides merge into nested model defaults rather than replacing the entire nested model.

### Dev/prod TOML defaults migration

`hassette.dev.toml` and `hassette.prod.toml` each contain 19 flat keys under `[hassette]`. Of those, 16 move into nested groups (lifecycle, websocket, scheduler, file_watcher) and 3 remain root-level (`dev_mode`, `allow_startup_if_app_precheck_fails`, `state_proxy_poll_interval_seconds`). `model_post_init` (`config.py:539-549`) iterates `type(self).model_fields` and calls `setattr` for matching flat keys from `get_defaults_dict()`. After migration, root `model_fields` still contains 21 cross-cutting flat fields + 8 group fields, so the 3 root-level TOML keys continue to match. The 16 grouped keys no longer match root fields.

**Fix:** Restructure both TOML files to use nested sections (`[hassette.websocket]`, `[hassette.scheduler]`, `[hassette.lifecycle]`, etc.) for the 16 grouped keys; keep the 3 root-level keys directly under `[hassette]`. Update `model_post_init` to iterate group names, retrieve each nested group's sub-dict from the defaults, and apply via `setattr(getattr(self, group_name), sub_field, value)` for each sub-field. Root-level keys continue to work via the existing flat mechanism.

**Files affected:** `src/hassette/config/hassette.dev.toml`, `src/hassette/config/hassette.prod.toml`, `src/hassette/config/defaults.py`, `src/hassette/config/config.py` (`model_post_init`).

### TOML source update

Modify `HassetteTomlConfigSettingsSource` to handle nested TOML sections. The current behavior flattens `[hassette]` into top-level keys. With nested models:

- `[hassette.database]` must be preserved as `{"database": {...}}` in the merged dict
- Top-level keys outside `[hassette]` (if any) are merged as before
- An empty `[database]` section produces `{}`, which Pydantic fills with defaults

The simplest approach: after extracting the `[hassette]` section, pass the dict (which now contains nested sub-dicts) directly to `InitSettingsSource` — Pydantic's nested model resolution handles the rest.

### Cross-field validation

Validators that span nested models stay on the root `HassetteConfig`:

- `validate_log_retention_days` → `self.logging.log_retention_days <= self.database.retention_days`

Validators that are internal to a single group move into that group's model:

- Timeout positivity check → `LifecycleConfig.validate_timeouts()` (for `event_handler_timeout_seconds`, `error_handler_timeout_seconds`) and `SchedulerConfig.validate_timeouts()` (for `job_timeout_seconds`)
- Log level default fill → `LoggingConfig.fill_defaults()`
- `log_all_hass_events` / `log_all_hassette_events` computed defaults → `LoggingConfig`
- `resource_shutdown_timeout_seconds` computed default → `LifecycleConfig`
- `autodetect_exclude_dirs` computed default → `AppConfig`
- `remove_incomplete_apps` field validator → `AppConfig`

### File organization

Create `src/hassette/config/models.py` for the 8 nested model classes. Keep `HassetteConfig` in `config.py` (or `config/config.py`), importing the models. This follows Prefect's pattern of one file per group (though at this scale a single `models.py` is sufficient).

### Access site migration

All access sites change from `config.db_path` to `config.database.path`, etc. The access pattern is consistent throughout the codebase (`self.hassette.config.*`), making this a mechanical find-and-replace per group.

**Config API endpoint migration:**

`src/hassette/web/routes/config.py` uses `_CONFIG_SAFE_FIELDS` (a flat 24-field allowlist) with `model_dump(include=...)` and a flat `ConfigResponse` model in `web/models.py`. After migration, flat field names no longer match root-level fields. Replace `_CONFIG_SAFE_FIELDS` with an exclude-based approach (exclude sensitive root fields like `token`) and restructure `ConfigResponse` into nested sub-models mirroring the new config structure. Regenerate TypeScript types and update 4 frontend files: `config.tsx` (~28 field accesses), `factories.ts`, `handlers.ts`, `config.test.tsx`. Also update `web_mocks.py` flat attribute assignments on MagicMock.

Key files affected:
- `src/hassette/core/database_service.py` — `config.db_*` → `config.database.*`, remove hardcoded constants
- `src/hassette/core/command_executor.py` — `config.telemetry_write_queue_max` → `config.database.telemetry_write_queue_max`
- `src/hassette/web/routes/logs.py` — `config.log_retention_days` → `config.logging.log_retention_days`
- All services reading their `*_log_level` — `config.bus_service_log_level` → `config.logging.bus_service`
- `src/hassette/core/websocket_service.py` — `config.websocket_*` → `config.websocket.*`
- `src/hassette/scheduler/` — `config.scheduler_*` → `config.scheduler.*`
- `src/hassette/web/` — `config.web_api_*` → `config.web_api.*`, `config.run_web_api` → `config.web_api.run`
- `src/hassette/app/` — `config.autodetect_apps` → `config.app.autodetect`, `config.app_dir` → `config.app.directory`
- `src/hassette/core/core.py` — timeout fields → `config.lifecycle.*`

### Test factory update

`make_test_config()` in `src/hassette/test_utils/config.py` needs to accept nested model fields. Two approaches:

1. **Nested dict kwargs**: `make_test_config(database={"retention_days": 14})`
2. **Model instances**: `make_test_config(database=DatabaseConfig(retention_days=14))`

Support both — Pydantic handles dict-to-model coercion natively when the field type is `DatabaseConfig`.

### preserve_config fixture migration

`src/hassette/test_utils/harness.py:152-162` snapshots config via `model_dump()` and restores via per-key `setattr`. With nested models, this bypasses root model validators on restore (cross-field constraints like retention_days are silently skipped). Change `preserve_config` to restore via `HassetteConfig.model_validate(original)` — full reconstruction fires all validators including cross-field ones.

## Convention Examples

### Cross-field validation pattern

**Source:** `src/hassette/config/config.py:490-503`

```python
@model_validator(mode="after")
def validate_log_retention_days(self) -> "HassetteConfig":
    """Ensure log_retention_days <= db_retention_days."""
    if self.log_retention_days > self.db_retention_days:
        raise ValueError(
            f"log_retention_days ({self.log_retention_days}) must be <= "
            f"db_retention_days ({self.db_retention_days})"
        )
    return self
```

This pattern stays on the root model but references nested paths: `self.logging.log_retention_days` and `self.database.retention_days`.

### ExcludeExtrasMixin

**Source:** `src/hassette/config/classes.py`

```python
class ExcludeExtrasMixin:
    def model_dump(self, *, exclude: Any | None = None, **kwargs: Any) -> dict[str, Any]:
        extra_keys = self._get_extra_keys()
        if extra_keys and kwargs.get("include") is not None:
            pass
        elif extra_keys:
            exclude = self._merge_exclude(exclude, extra_keys)
        return super().model_dump(exclude=exclude, **kwargs)
```

All nested config models must inherit this mixin to prevent accidental serialization of extra fields.

### TOML custom source

**Source:** `src/hassette/config/classes.py:24-48`

```python
class HassetteTomlConfigSettingsSource(TomlConfigSettingsSource):
    def __init__(self, settings_cls, toml_file=DEFAULT_PATH):
        self.toml_data = self._read_files(self.toml_file_path)
        if "hassette" not in self.toml_data:
            super().__init__(settings_cls, self.toml_file_path)
            return
        hassette_values = self.toml_data.pop("hassette")
        self.toml_data.update(hassette_values)
        InitSettingsSource.__init__(self, settings_cls, self.toml_data)
```

This needs modification: after merging `[hassette]` values, nested sub-dicts (from `[hassette.database]`, etc.) must be preserved, not flattened.

### Hermetic test factory

**Source:** `src/hassette/test_utils/config.py`

```python
def _get_hermetic_hassette_config_cls():
    cell: list[dict[str, Any]] = [{}]

    class _Cls(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "toml_file": None,
            "env_file": None,
        }

        @classmethod
        def settings_customise_sources(cls, settings_cls, **_kwargs):
            return (InitSettingsSource(settings_cls, init_kwargs=cell[0]),)

    return (_Cls, cell)
```

This pattern avoids accumulating Pydantic subclasses. Update to accept nested model dicts/instances in `init_kwargs`. Additionally, override `extra="forbid"` on the hermetic subclass so stale/invalid field names fail loudly instead of being silently absorbed into `model_extra`. This catches migration regressions (flat field names that should now be nested) and future typos. Update the factory's internal defaults dict to nested form: `"autodetect_apps": False` → `"app": {"autodetect": False}`, `"run_web_api": False` → `"web_api": {"run": False}`, etc.

### Database service config access

**Source:** `src/hassette/core/database_service.py`

```python
async def on_initialize(self) -> None:
    timeout = self.hassette.config.db_migration_timeout_seconds
    self._db_write_queue = asyncio.Queue(
        maxsize=self.hassette.config.db_write_queue_max
    )
```

Migrates to `self.hassette.config.database.migration_timeout_seconds` and `self.hassette.config.database.write_queue_max`. Hardcoded constants (`_HEARTBEAT_INTERVAL_SECONDS`, etc.) become `self.hassette.config.database.heartbeat_interval_seconds`.

## Alternatives Considered

### Keep flat config, add comment grouping only

Add section comments and reorganize field order without extracting nested models. Zero breaking changes, zero migration effort, but the underlying problem (flat namespace, no structural guidance for new fields) remains. Rejected because the config is already at 94 fields and growing.

### Incremental migration with AliasChoices backward compatibility

Extract one group at a time, using `AliasChoices` to accept both flat (`db_path`) and nested (`database__path`) env var names during a transition period. The standard approach for projects with external users. Rejected because hassette has no external users — the backward compat machinery adds complexity with no benefit.

### One file per config group (Prefect pattern)

Create `src/hassette/config/database.py`, `src/hassette/config/websocket.py`, etc. Prefect does this with ~20 groups. At 8 groups with small models, a single `models.py` is sufficient. Can split later if individual models grow significantly.

## Test Strategy

- **Unit tests for each nested model**: Validate defaults, field constraints (`ge=`, type coercion), computed defaults, and intra-model validators
- **Unit tests for cross-model validation**: Root-level validators spanning nested models (retention days constraint)
- **Integration tests for config loading**: TOML with nested sections, env var overrides (single field and full group), mixed sources (TOML + env override)
- **Regression tests for `make_test_config`**: Verify the test factory accepts both flat kwargs and nested dict/model overrides
- **Regression tests for CLI parsing**: Verify nested fields are accessible via CLI arguments
- **Existing test suite**: Must pass without modification to test assertions (only config access paths change)

## Documentation Updates

- **Config reference page** (`docs/`): Restructure to show grouped sections with TOML examples
- **Getting started guide**: Update `hassette.toml` examples to use nested sections
- **Environment variable reference**: Update to show nested delimiter paths (`HASSETTE__DATABASE__PATH`)
- **Developer guide**: Add guidance on where new config fields should go (which group, or root-level)
- **Docstrings**: Update `HassetteConfig` class docstring and add docstrings to each nested model

## Impact

**High-touch files:**
- `src/hassette/config/config.py` — Major restructure (extract fields, update validators)
- `src/hassette/config/classes.py` — TOML source update
- `src/hassette/config/models.py` — New file with 8 model classes
- `src/hassette/test_utils/config.py` — Test factory update
- `src/hassette/core/database_service.py` — Remove constants, update access paths

**Medium-touch files (access path updates):**
- `src/hassette/core/core.py`
- `src/hassette/core/command_executor.py`
- `src/hassette/core/websocket_service.py`
- `src/hassette/scheduler/` (multiple files)
- `src/hassette/web/` (routes, middleware)
- `src/hassette/app/` (app handler, lifecycle)
- `src/hassette/bus/` (excluded domains/entities access)
- `src/hassette/resources/` (log level access)

**Test files:** All tests that create or access config will need access path updates. The hermetic test factory change propagates automatically to tests using `make_test_config()`.

**Blast radius:** Large — touches most of the codebase through config access paths. However, each individual change is mechanical (rename a field access). No behavioral changes except the 7 newly configurable database constants.

<!-- Gap check 2026-05-19: 0 major gaps — all 55 source files with config access are covered by the Impact section (25 config_log_level properties covered by "All services reading their *_log_level"; test_utils files covered by "Test files" note; frontend covered by Config API endpoint migration section). -->

## Open Questions

None — all design decisions resolved during discovery.
