# Context: Migrate HassetteConfig to Nested Pydantic Models

## Problem & Motivation

HassetteConfig is a single flat class with 94 annotated fields. Related settings are distinguished only by naming convention (prefix-based grouping like `websocket_*`, `scheduler_*`), making the config hard to navigate, reason about, and extend. Users configuring the framework in TOML or environment variables face a flat list with no logical grouping. Additionally, 7 operational parameters in the database service are hardcoded as module-level constants, preventing users on constrained hardware from tuning them without source modification.

## Visual Artifacts

None.

## Key Decisions

1. **8 nested model groups** — DatabaseConfig (13 fields incl. 7 promoted constants), WebSocketConfig (13), LoggingConfig (21), LifecycleConfig (10), WebApiConfig (9), AppConfig (6), SchedulerConfig (5), FileWatcherConfig (3). 21 cross-cutting fields remain at root.
2. **BaseModel, not BaseSettings** — Nested models inherit `BaseModel`. If they inherited `BaseSettings`, Pydantic initializes them independently and ignores the parent prefix, causing env var leakage (Prefect issue #15943).
3. **`nested_model_default_partial_update=True`** — Required in `model_config` so a single env var override merges into nested model defaults rather than replacing the entire nested model.
4. **LoggingConfig naming exception** — Core `log_*` fields retain the `log_` prefix (e.g., `log_level`, `log_format`, `log_retention_days`) for `log_level_default_factory` compatibility. The `log_all_*` booleans strip the prefix (→ `all_events`, `all_hass_events`, `all_hassette_events`).
5. **Per-service log levels default to `None`** — A `model_validator(mode="after")` on LoggingConfig fills `None` values from `self.log_level`, replacing the current `default_factory=log_level_default_factory` pattern.
6. **`data_dir` and `config_dir` stay root-level** — They're framework-wide (used by DB service, resource caches, config endpoint), not app-specific.
7. **No backward compatibility shims** for Python field names. AliasChoices only for documented env vars that appear in Docker guides.
8. **Single `models.py` file** — All 8 model classes in one file. Can split later if individual models grow significantly.
9. **Test factory gets `extra="forbid"`** — Catches stale flat field names that should now be nested.
10. **`preserve_config` uses `model_validate`** — Full reconstruction fires all validators including cross-field ones, replacing the per-key `setattr` approach.

## Constraints & Anti-Patterns

- Do NOT make nested models inherit `BaseSettings` — causes env var leakage.
- Do NOT strip the `log_` prefix from `log_level`, `log_format`, `log_queue_max`, `log_persistence_level`, `log_retention_days` — breaks `log_level_default_factory` used by both `LoggingConfig` and `AppConfig`.
- Do NOT forget `nested_model_default_partial_update=True` — without it, a single env var replaces the entire nested model.
- Do NOT introduce backward compatibility shims for flat Python field names — no external users.
- All nested models MUST inherit `ExcludeExtrasMixin` to prevent accidental serialization of extra fields.
- The `validate_timeout_seconds` validator must be split: `LifecycleConfig` validates `event_handler_timeout_seconds` and `error_handler_timeout_seconds`; `SchedulerConfig` validates `job_timeout_seconds`.

## Design Doc References

- **## Problem** — what's wrong with the flat config
- **## Architecture > Nested model structure** — complete field mapping tables for all 8 groups + root
- **## Architecture > model_config changes** — `nested_model_default_partial_update` setting
- **## Architecture > Dev/prod TOML defaults migration** — restructuring hassette.dev.toml / hassette.prod.toml
- **## Architecture > TOML source update** — modifying `HassetteTomlConfigSettingsSource`
- **## Architecture > Cross-field validation** — which validators stay on root vs move into groups
- **## Architecture > File organization** — single `models.py` approach
- **## Architecture > Access site migration** — mechanical rename patterns per group
- **## Architecture > Test factory update** — `make_test_config()` changes
- **## Architecture > preserve_config fixture migration** — `model_validate` restoration
- **## Convention Examples** — real code snippets showing current patterns

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

After migration, nested sub-dicts (from `[hassette.database]`, etc.) must be preserved, not flattened.

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

Update to accept nested model dicts/instances. Override `extra="forbid"` on the hermetic subclass.

### Database service config access

**Source:** `src/hassette/core/database_service.py`

```python
async def on_initialize(self) -> None:
    timeout = self.hassette.config.db_migration_timeout_seconds
    self._db_write_queue = asyncio.Queue(
        maxsize=self.hassette.config.db_write_queue_max
    )
```

Migrates to `self.hassette.config.database.migration_timeout_seconds` and `self.hassette.config.database.write_queue_max`. Hardcoded constants become `self.hassette.config.database.heartbeat_interval_seconds`, etc.

### log_level_default_factory

**Source:** `src/hassette/config/helpers.py:173-185`

```python
def log_level_default_factory(data: dict[str, LOG_LEVEL_TYPE | None]) -> LOG_LEVEL_TYPE:
    return coerce_log_level(data.get("log_level"), "INFO")
```

This factory reads `log_level` from the data dict. Within `LoggingConfig`, this works unchanged because the field is still named `log_level`. Per-service log levels switch to `default=None` + model_validator fill pattern.

### config_log_level property pattern (25 services)

Each service class overrides `config_log_level` to return its specific config field:

```python
@property
def config_log_level(self) -> LOG_LEVEL_TYPE:
    return self.hassette.config.database_service_log_level
```

After migration: `self.hassette.config.logging.database_service`.
