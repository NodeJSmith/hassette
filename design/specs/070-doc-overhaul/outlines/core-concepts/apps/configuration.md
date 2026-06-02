# Apps — Configuration

**Status:** ABSORBED into `apps/overview.md`
**Voice mode:** N/A
**Page type:** N/A (content merged)
**Reader's job:** N/A

## Rationale

At 34 lines (3 base fields + env prefix + secrets), this does not justify its own page. The reader's job ("define typed config for my app") is a step within "write an app," not a standalone task. Creating a separate page forces the reader to navigate away from the app definition to understand config, then navigate back.

Content folded into the Apps overview as an H2 "Configuration":
- `AppConfig` subclass with `SettingsConfigDict` and `env_prefix`
- Base fields: `instance_name`, `log_level`
- `extra="allow"` behavior, `env_ignore_empty=True`
- Secrets and env vars via Pydantic `BaseSettings`

The existing `configuration.md` doc page should redirect to the Apps overview Configuration section, or be replaced by the merged content. The TOML registration side stays on its own page at Configuration/Applications.

## Snippet Inventory

Snippets move to Apps overview:
- `app_config_definition.py` — used in overview H2: Configuration
- `app_config_env_prefix.py` — used in overview H2: Configuration
