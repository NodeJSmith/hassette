---
topic: "Configuration Class Organization"
date: 2026-05-01
status: Draft
---

# Prior Art: Configuration Class Organization

## The Problem

Frameworks grow knobs. What starts as 10 settings becomes 50, then 100. At some point the single config class becomes unwieldy — users can't find what's configurable, contributors can't tell which settings are related, and the class itself becomes a merge conflict magnet. But splitting too eagerly creates its own problems: multiple files to check, import chains, and the question of where cross-cutting settings (log level, debug mode) live.

The design space has two axes: **structure** (flat vs nested vs hierarchical) and **source resolution** (how defaults, files, env vars, and CLI args compose). Structure determines discoverability and maintainability; source resolution determines the operational experience. Most frameworks solve one axis well and struggle with the other. The ideal is: grouped for discoverability, flat for env var simplicity, validated at startup, and discoverable without reading source code.

## How We Do It Today

Hassette uses a **single flat `HassetteConfig(BaseSettings)` class with 97 fields across 559 lines**. Settings are organized into ~10 logical blocks via code comments (not class hierarchy): HA connection, app management, service timeouts, web API, database, 11 per-service log levels, event bus filters, production mode. Env vars use `HASSETTE__` prefix with `__` nested delimiter. Defaults come from dev/prod TOML files loaded via a custom `HassetteTomlConfigSettingsSource`. The class supports CLI args, multiple env file locations, and `extra="allow"` for privacy filtering. It's a pragmatic monolith — works today but scales poorly beyond ~100 fields.

## Patterns Found

### Pattern 1: Nested Pydantic Models Under Root Settings (Prefect Model)

**Used by**: Prefect (v3), increasingly common in modern Python frameworks

**How it works**: A single root class inherits from `BaseSettings`. Each logical group is a separate `BaseModel` subclass (critically: not `BaseSettings`) that becomes a field on the root. The root uses `env_nested_delimiter='__'` and `env_prefix='FRAMEWORK_'` so `FRAMEWORK_SERVER__DATABASE__HOST` maps to `settings.server.database.host`.

Prefect organizes ~20 groups in a `settings/models/` package — one file per group (`api.py`, `logging.py`, `tasks.py`), subdirectories for deep nesting (`server/database.py`). The root class in `root.py` composes all groups plus a few ungrouped scalar fields (home directory, debug mode). Cross-cutting validation lives on the root via `@model_validator(mode='after')`. A `copy_with_update()` method creates modified instances immutably.

Prefect's migration from flat to nested was incremental — one group at a time, with `AliasChoices` accepting both old flat env var names and new nested names for backward compatibility. PR #15580 added the first group; PR #15772 restructured into the `models/` package.

**Strengths**: Type-safe access with IDE autocompletion (`settings.logging.level`). Discoverability — each group is an inspectable class. Independent per-group validation plus cross-group validation on root. Env vars work naturally via nested delimiter. Groups importable independently for tests. Scales well — new group = new file + new field.

**Weaknesses**: Sub-models MUST be `BaseModel` not `BaseSettings` — if they inherit `BaseSettings`, Pydantic initializes them independently, ignoring parent prefix ([source](https://github.com/pydantic/pydantic/discussions/8989)). Un-prefixed env vars can leak into nested models ([Prefect #15943](https://github.com/PrefectHQ/prefect/issues/15943)). Backward compatibility with flat names requires validation aliases during migration. More boilerplate than flat for small config surfaces (<20 settings).

**Example**: https://github.com/PrefectHQ/prefect/blob/main/src/prefect/settings/models/root.py

### Pattern 2: INI Sections with Environment Variable Override (Airflow Model)

**Used by**: Apache Airflow, many traditional Python projects

**How it works**: Configuration as INI file with named sections (`[core]`, `[webserver]`, `[scheduler]`, `[database]`). A custom `AirflowConfigParser` extends `ConfigParser` with type conversion, command execution for secrets (`_cmd` suffix), and env var overrides following `AIRFLOW__{SECTION}__{KEY}`. Five-tier resolution: env > config file > commands > default config > exception.

**Strengths**: Simple mental model — sections are visible, keys are flat strings. Env var mapping is mechanical. Config file is human-readable without code knowledge. ConfigParser prevents accidental mutation.

**Weaknesses**: No type safety at schema level. Only one hierarchy level (section > key). String-based access lacks IDE support. Five-tier fallback adds debugging complexity.

**Example**: https://airflow.apache.org/docs/apache-airflow/stable/configurations-ref.html

### Pattern 3: Flat Module with Environment-Based Splitting (Django Model)

**Used by**: Django, many web frameworks

**How it works**: Settings are module-level variables in a Python file. For large projects, split into `settings/base.py`, `local.py`, `staging.py`, `production.py` selected via `DJANGO_SETTINGS_MODULE`. The 12-factor approach uses `django-environ` to read individual values from env vars.

**Strengths**: Zero ceremony. Full Python expressiveness. Every developer knows it. Easy to grep.

**Weaknesses**: No schema, validation, or types — invalid config discovered at runtime. No IDE autocompletion on access. Inheritance chains hard to trace. No structural pressure to organize — settings creep.

**Example**: https://djangostars.com/blog/configuring-django-settings-best-practices/

### Pattern 4: Flat Namespace with Semantic Prefixes (Celery Model)

**Used by**: Celery, Redis client libraries, many single-purpose libraries

**How it works**: All settings are top-level attributes grouped by naming convention: `task_always_eager`, `worker_concurrency`, `broker_url`, `result_backend`, `beat_schedule`. Celery v4.0 rationalized inconsistent legacy prefixes into clean category prefixes. Django integration adds `CELERY_` via `namespace='CELERY'`.

**Strengths**: Simple — all settings in one place, sorted by prefix. Grep-friendly. No nesting complexity. Easy to add settings.

**Weaknesses**: No structural enforcement — prefixes are conventions only. Flat list becomes overwhelming at 100+ settings. No per-group validation. Prefix ambiguity (`task_result_expires` — task or result?). Migration requires long deprecation.

**Example**: https://docs.celeryq.dev/en/stable/userguide/configuration.html

### Pattern 5: Domain-Key Config with Schema Validation (Home Assistant Model)

**Used by**: Home Assistant, Ansible, Kubernetes

**How it works**: YAML file where each top-level key is a domain (integration). Each domain owns its config subtree and defines a validation schema. ADR-0007 standardized that all config must live under the integration's domain key — solving the discoverability problem where users didn't know where to configure things.

**Strengths**: Natural discoverability — one key per domain. Schema validation at load time. Each domain evolves independently. YAML readable by non-developers.

**Weaknesses**: Voluptuous schemas are verbose. YAML-specific — doesn't directly apply to programmatic config. No cross-domain validation. Schema definitions separate from code.

**Example**: https://github.com/home-assistant/architecture/blob/master/adr/0007-integration-config-yaml-structure.md

### Pattern 6: Declare-Close-to-Usage with Root Composition

**Used by**: Recommended by Preferred Networks engineering blog, adopted in various internal tools

**How it works**: Each module declares its own config dataclass in the same file or neighboring `config.py`. These contain only the settings that module needs, with types, defaults, and validators local to the module. A root config class composes all module configs:

```python
# app/db/config.py
class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432

# app/config.py
class AppConfig(BaseSettings):
    db: DatabaseConfig
    server: ServerConfig
```

The key principle: "configuration entries should be declared close to the place where they are used." This prevents shared generic settings (one `timeout` affecting HTTP, DB, and cache).

**Strengths**: Maximum discoverability — config next to code. Independently testable. Changes don't touch a central file. Prevents accidental coupling. IDE go-to-definition lands in the right module.

**Weaknesses**: Requires discipline to maintain root composition. Loading from env vars needs root-level mapping. Can duplicate legitimate shared settings. Multiple config files to discover.

**Example**: https://tech.preferred.jp/en/blog/working-with-configuration-in-python/

### Pattern 7: Multi-Source Override Chain (Pydantic Settings Native)

**Used by**: Any Pydantic Settings user

**How it works**: `settings_customise_sources()` returns a tuple of settings sources in priority order. Default: CLI > init > env > dotenv > secrets > defaults. Custom sources inserted at any position. Key features for large configs: `nested_model_default_partial_update=True` (partial env updates preserve other defaults), multiple secrets directories with layered override, `env_nested_max_split` for ambiguous delimiters.

**Strengths**: Override chain explicit and customizable. Supports any source format. Partial updates. Composable with any structure pattern. CLI integration built in.

**Weaknesses**: Custom sources require Pydantic internals knowledge. Debugging "where did this value come from?" requires inspecting priority. More sources = harder reasoning.

**Example**: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/

## Anti-Patterns

- **Sub-models inheriting from BaseSettings**: Must be `BaseModel` for nested delimiter to work. `BaseSettings` sub-models initialize independently, ignoring parent prefix — produces hard-to-debug value resolution bugs. ([source](https://github.com/pydantic/pydantic/discussions/8989))

- **Shared generic settings across unrelated components**: A single `timeout` used by HTTP client, database, and cache creates invisible coupling. Each component should declare its own with a domain-specific name. ([source](https://tech.preferred.jp/en/blog/working-with-configuration-in-python/))

- **Late validation (validate at point of use)**: Invalid config can lurk for hours until the code path is hit. Validate everything at startup and fail fast. ([source](https://tech.preferred.jp/en/blog/working-with-configuration-in-python/))

- **Un-prefixed environment variable leakage**: Without strict `env_prefix`, Pydantic Settings can match bare field names at any nesting level. A `database` field matches `DATABASE` env var even without the framework prefix, causing silent corruption. ([source](https://github.com/PrefectHQ/prefect/issues/15943))

- **Complex logic in settings files**: Conditional logic and computation in config definitions makes config hard to reason about. Computed values belong in validators, not default definitions. ([source](https://djangostars.com/blog/configuring-django-settings-best-practices/))

## Emerging Trends

**Convergence on Pydantic Settings**: Even projects that started with custom solutions (Prefect's original system, various dataclass approaches) are migrating to Pydantic Settings v2. Runtime validation, type safety, nested models, and multi-source loading cover common requirements without custom framework code.

**Incremental migration from flat to nested**: Prefect's path — one nested group at a time with `AliasChoices` for backward compatibility — is becoming the standard approach. Avoids big-bang migration that breaks existing env var names. ([source](https://github.com/PrefectHQ/prefect/pull/15580))

**CLI integration as first-class citizen**: Pydantic Settings' `cli_parse_args` treats CLI args as just another source in the priority chain, eliminating the impedance mismatch between "CLI config" and "everything else."

## Relevance to Us

Hassette is at 97 fields — right at the threshold where flat stops working. The comment-block grouping shows the natural seam lines already exist (database, websocket, scheduler, web API, log levels). The `env_nested_delimiter="__"` is already configured, meaning nested models would work with the existing env var convention.

**What we're doing well:**
- **Pydantic Settings as the foundation** — already using `BaseSettings` with proper source customization (TOML, env, CLI, dotenv).
- **Custom TOML source** — dev/prod TOML defaults is a mature pattern for environment-specific configuration.
- **`env_nested_delimiter="__"`** — already set, so transitioning to nested models won't break existing env vars if aliases are added.
- **Eager validation** — `validate_assignment=True` and startup-time loading means invalid config fails fast.

**Natural split candidates** (based on existing comment-block groupings):
1. **DatabaseConfig** — `db_path`, `db_retention_days`, `db_max_size_mb`, `db_migration_timeout_seconds`, etc. (6 fields)
2. **WebSocketConfig** — 11 `websocket_*` fields
3. **SchedulerConfig** — 7 `scheduler_*` fields
4. **WebApiConfig** — 8 `web_api_*` fields
5. **LoggingConfig** — 11 per-service `*_log_level` fields + top-level `log_level`
6. **TelemetryConfig** — `telemetry_write_queue_max`, retention settings
7. **AppConfig** — `autodetect_apps`, `app_manifests`, `config_dir`

Cross-cutting fields (top-level `log_level`, `dev_mode`, `production_mode`, `token`) stay as scalar fields on the root.

**The Prefect pitfall to avoid:** Sub-models must be `BaseModel` not `BaseSettings` — hassette's existing `HassetteConfig(BaseSettings)` must remain the only `BaseSettings` subclass. Also guard against un-prefixed env var leakage (Prefect #15943) — the `HASSETTE__` prefix should be enforced at every level.

## Recommendation

**Adopt Pattern 1 (Prefect's nested Pydantic models) incrementally.** Hassette is already at the inflection point (97 fields) and has the infrastructure for it (`env_nested_delimiter` already set, Pydantic Settings as the base).

The migration path, following Prefect's approach:
1. Start with the most cohesive group — **DatabaseConfig** (6 fields, clean prefix, no cross-cutting dependencies)
2. Add it as a `BaseModel` field on `HassetteConfig` with `AliasChoices` accepting both `db_path` (flat) and `database__path` (nested) env var names
3. One group at a time, ~2-3 per PR, until the root class is a composition of typed groups
4. Cross-cutting fields (`dev_mode`, `log_level`, `token`) stay on the root as scalars

The declare-close-to-usage pattern (Pattern 6) is aspirational but probably overkill at hassette's scale — having all groups in a `config/` package (Prefect's `settings/models/` approach) is cleaner than scattering config classes across the codebase.

## Sources

### Reference implementations
- https://github.com/PrefectHQ/prefect/blob/main/src/prefect/settings/models/root.py — Prefect root Settings class
- https://github.com/PrefectHQ/prefect/pull/15772 — Prefect settings submodule refactor
- https://github.com/PrefectHQ/prefect/pull/15580 — Prefect first nested group (APISettings)
- https://docs.celeryq.dev/en/stable/userguide/configuration.html — Celery flat config
- https://github.com/coleifer/huey/blob/master/huey/storage.py — Huey SQLite config

### Blog posts & writeups
- https://tech.preferred.jp/en/blog/working-with-configuration-in-python/ — Declare-close-to-usage principle
- https://djangostars.com/blog/configuring-django-settings-best-practices/ — Django settings patterns
- https://medium.com/@tszumowski/delightful-designs-airflows-configuration-parser-1ef1a6b3d03c — Airflow config analysis
- https://medium.com/@jayanthsarma8/config-management-with-pydantic-base-settings-de22b79fd191 — Pydantic nested settings tutorial
- https://ai.ragv.in/posts/sane-configs-with-pydantic-settings/ — Pydantic Settings patterns

### Documentation & standards
- https://docs.prefect.io/v3/develop/settings-and-profiles — Prefect settings and profiles
- https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ — Pydantic Settings docs
- https://airflow.apache.org/docs/apache-airflow/stable/configurations-ref.html — Airflow config reference
- https://github.com/home-assistant/architecture/blob/master/adr/0007-integration-config-yaml-structure.md — HA ADR-0007

### Issues & discussions
- https://github.com/PrefectHQ/prefect/issues/15943 — Un-prefixed env var leakage in nested models
- https://github.com/pydantic/pydantic/discussions/8989 — BaseSettings vs BaseModel for sub-models
- https://github.com/celery/celery/discussions/7038 — Celery naming conventions debate
- https://news.ycombinator.com/item?id=22964910 — HN discussion on Python config patterns
