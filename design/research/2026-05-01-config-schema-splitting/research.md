---
topic: "Configuration file design — schema, splitting, and DX"
date: 2026-05-01
status: Draft
---

# Prior Art: Configuration File Design — Schema, Splitting, and DX

## The Problem

As a config-driven automation framework, hassette's `hassette.toml` is the primary interface between the framework and its users. Two questions arise as the project matures:

1. **Should the config have a formal schema?** IDE autocompletion and validation for config files is increasingly expected. Without a published schema, users write config blind — relying on docs pages and trial-and-error.

2. **Should config support splitting across multiple files?** A single `hassette.toml` works for small setups, but users with 10+ apps may want to organize config by room, function, or app group.

## How We Do It Today

Hassette uses Pydantic Settings v2 (`BaseSettings`) with a custom `HassetteTomlConfigSettingsSource` that loads a single `hassette.toml` file. The `[hassette]` section is merged into the top level. Config sources are layered: CLI flags > env vars > `.env` file > TOML file > defaults. `AppManifest` validates per-app entries with `extra="allow"`, silently collecting unknown keys.

There is no formal schema definition (no JSON Schema export), no multi-file support (no includes, packages, or directory loading), and no IDE autocompletion for `hassette.toml`. The config reference docs are hand-written.

## Patterns Found

### Pattern 1: Pydantic Model as Schema Source of Truth

**Used by**: FastAPI (OpenAPI from Pydantic), Pydantic Settings, Litestar, many Python CLI tools

**How it works**: The config schema is defined as Pydantic models that serve triple duty: (1) runtime validation when config is loaded, (2) JSON Schema export via `model_json_schema()` for IDE tooling, and (3) documentation generation from field descriptions and examples. The JSON Schema is always in sync with runtime behavior because it's generated from the same models.

Pydantic Settings extends this by adding config source priority (env vars > files > defaults) without custom loading code.

**Strengths**: Single source of truth eliminates schema drift. Runtime validation gives precise error messages. JSON Schema export enables IDE integration for free. Already using Pydantic — zero new dependencies.

**Weaknesses**: JSON Schema export may not capture all custom validators (cross-field validation, model validators). Complex discriminated unions produce hard-to-read schemas. `extra="allow"` makes the schema open-ended, reducing validation value.

**Example**: https://docs.pydantic.dev/latest/concepts/json_schema/

### Pattern 2: SchemaStore Publication for IDE Integration

**Used by**: Ruff, Docker Compose, GitHub Actions, ESLint, Prettier, Terraform, 800+ projects

**How it works**: A project generates its config schema as JSON Schema, then submits it to SchemaStore with `fileMatch` patterns (e.g., `hassette.toml`). Once published, every IDE with TOML language server support (Taplo in VS Code/JetBrains/Neovim) automatically provides autocompletion, validation, and inline documentation. Zero setup for end users.

**Strengths**: Massive leverage — one schema, IDE support everywhere. Zero user setup. Combining with Pattern 1 means the schema is auto-generated and always current.

**Weaknesses**: SchemaStore is a centralized dependency. Review process takes time. JSON Schema expressiveness is limited for complex validation rules.

**Example**: https://www.schemastore.org/, https://json-schema-everywhere.github.io/toml

### Pattern 3: Function-Oriented Packages (Deep Merge)

**Used by**: Home Assistant (packages), ESPHome (packages), Docker Compose (include)

**How it works**: Config is split by *function* (everything for "kitchen lighting" in one file) rather than by domain (all automations in one file). Each package file can define entries across multiple top-level sections. The framework deep-merges all packages into a single effective config at startup.

HA implements this with `!include_dir_named packages/` which loads all YAML files from a directory. ESPHome adds merge-by-component-ID for more precise merging. Docker Compose's `include` loads each file as an independent model and rejects conflicts rather than silently overriding.

**Strengths**: Natural grouping that matches how users think ("kitchen stuff" not "all automations"). Easy enable/disable by adding/removing a file. No central manifest to maintain.

**Weaknesses**: Deep merge semantics can surprise users (what if two packages define the same app?). Debugging "which file contributed this value?" requires tooling. Merge rules must be clearly documented.

**Example**: https://www.home-assistant.io/docs/configuration/packages/

### Pattern 4: Base + Override Files (Environment Layering)

**Used by**: Docker Compose, Ansible, Terraform, Kubernetes (Kustomize)

**How it works**: A base config defines shared defaults. Environment-specific override files layer on top. Docker Compose auto-discovers `compose.override.yml` next to `compose.yml`. Merge rules are explicit: scalars last-wins, lists append, maps merge by key.

For hassette, this would look like `hassette.toml` (base) + `hassette.local.toml` (per-machine overrides, gitignored). The local file overrides specific keys without duplicating the entire config.

**Strengths**: Clean separation of shared vs environment-specific config. Base file serves as documentation of defaults. Override file is gitignored for secrets/local paths.

**Weaknesses**: More files to manage. Precedence rules must be short and documented (Ansible's 22-level precedence is a cautionary tale).

**Example**: https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/

### Pattern 5: Auto-Load All Files in Directory

**Used by**: Terraform (all `.tf` files), HA (`!include_dir_*`), Ansible (roles)

**How it works**: The framework auto-loads all files matching a pattern in a designated directory. Drop a file in, it's included. No manifest, no import statement. Terraform loads all `.tf` files in the module directory as a single unit with no order dependency.

For hassette, this could be an `apps/` directory where each `.toml` file defines one or more apps, auto-merged into the `[apps]` section of the effective config.

**Strengths**: Zero-friction for adding new apps. Filesystem-based organization. No central manifest to maintain.

**Weaknesses**: No explicit control over load order. Risk of accidentally including temp/backup files. Requires naming conventions.

**Example**: https://developer.hashicorp.com/terraform/language/modules/develop/structure

## Anti-Patterns

- **Ansible's 22-level variable precedence**: Keep the override chain short — 3-4 levels max (defaults > config file > local overrides > env vars > CLI flags). Beyond that, users can't reason about which value wins. Hassette already has 4 levels via Pydantic Settings; adding multi-file config should not add more.

- **Silent duplicate key override**: YAML silently keeps the last value for duplicate keys. TOML rejects duplicate keys by spec — this is a built-in advantage of staying TOML-only.

- **Config-as-code**: When templating becomes too powerful (Ansible Jinja2, Helm), config files become programs. Config should be data with limited interpolation, not a program. Hassette's Pydantic-based approach keeps logic in Python, not in the config file — this is the right call.

## Emerging Trends

- **TOML replacing YAML for Python tools**: PEP 621, Ruff, uv, mypy, pytest — the Python ecosystem has decisively moved to TOML. AppDaemon 4.3+ added TOML support alongside YAML. Hassette being TOML-only is aligned with the trend.

- **Pydantic + JSON Schema + SchemaStore as the standard stack**: Define config as Pydantic models → export JSON Schema → publish to SchemaStore. This "define once, validate everywhere" pattern is becoming table stakes for Python developer tools.

## Relevance to Us

Hassette is well-positioned for all of these patterns because the foundation is already Pydantic Settings:

1. **Schema export is nearly free** — `HassetteConfig.model_json_schema()` would produce a JSON Schema today. The gap is that `extra="allow"` on `AppManifest` makes the schema open-ended, and custom validators won't be reflected. But the global config section would be fully schematized.

2. **SchemaStore publication is high-leverage, low-effort** — generate the schema in CI, submit to SchemaStore, and every IDE user gets autocompletion. This is the single biggest DX improvement available.

3. **Multi-file config should follow HA's packages pattern** — hassette users are HA users. They already know the `packages/` directory pattern. An `apps/` or `conf.d/` directory where each TOML file contributes app definitions would feel natural.

4. **Local overrides (`hassette.local.toml`) solve the secrets/environment problem** — base config checked into git, local overrides gitignored. This is simpler than hassette needing to document env var overrides for every field.

5. **The existing 4-level precedence (CLI > env > .env > TOML) is already right** — adding multi-file support should not add precedence levels. Package files and the base file should merge into a single effective TOML before Pydantic validates it.

## Recommendation

Three improvements, in priority order:

1. **JSON Schema export + SchemaStore** (Pattern 1 + 2) — Highest leverage. Add a `scripts/export_config_schema.py` that calls `HassetteConfig.model_json_schema()`, writes the schema, and publish to SchemaStore. CI checks freshness. This gives every IDE user autocomplete and validation immediately.

2. **`hassette.local.toml` overlay** (Pattern 4) — Load a second TOML file if present, merge into the base config before validation. Gitignore it by default. Solves the "I don't want to put my HA URL in version control" problem without env var gymnastics.

3. **App directory auto-loading** (Pattern 3 + 5) — If a `conf.d/` or `apps.d/` directory exists, auto-load all `.toml` files and merge their `[apps.*]` sections into the effective config. This is a natural extension of the existing `app_dir` + `autodetect_apps` pattern (which auto-discovers Python files but not their config).

Pattern 3 (function-oriented packages with deep merge of arbitrary top-level keys) is probably overkill for hassette. HA needs it because its config covers dozens of domains (automations, sensors, scripts, scenes, etc.). Hassette's config has two main sections: `[hassette]` globals and `[apps.*]` entries. Splitting just the apps section (option 3 above) covers 90% of the use case without the complexity of full deep merge.

## Sources

### Reference implementations
- https://www.home-assistant.io/docs/configuration/splitting_configuration/ — HA config splitting with !include directives
- https://www.home-assistant.io/docs/configuration/packages/ — HA packages (function-oriented config)
- https://esphome.io/components/packages/ — ESPHome packages with merge rules
- https://esphome.io/components/substitutions/ — ESPHome variable substitution
- https://esphome.io/guides/yaml/ — ESPHome CONFIG_SCHEMA per-component validation
- https://appdaemon.readthedocs.io/en/latest/CONFIGURE.html — AppDaemon dual YAML/TOML config
- https://docs.astral.sh/ruff/configuration/ — Ruff hierarchical config discovery
- https://developer.hashicorp.com/terraform/language/modules/develop/structure — Terraform module structure

### Documentation & standards
- https://json-schema-everywhere.github.io/toml — JSON Schema for TOML validation
- https://taplo.tamasfe.dev/cli/usage/validation.html — Taplo TOML schema validation
- https://www.schemastore.org/ — JSON Schema Store (800+ schemas)
- https://docs.pydantic.dev/latest/concepts/json_schema/ — Pydantic JSON Schema export
- https://docs.pydantic.dev/latest/concepts/pydantic_settings/ — Pydantic Settings config sources
- https://packaging.python.org/en/latest/specifications/pyproject-toml/ — PEP 621 pyproject.toml spec
- https://pypi.org/project/validate-pyproject/ — JSON Schema validation for pyproject.toml

### Blog posts & writeups
- https://ruudvanasseldonk.com/2023/01/11/the-yaml-document-from-hell — YAML implicit type coercion pitfalls
- https://nickb.dev/blog/design-dilemma-configuration-files/ — Config format design tradeoffs
- https://olegtarasov.me/esphome-packages-substitutions-tutorial/ — ESPHome packages + substitutions tutorial

### Merge & override patterns
- https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/ — Docker Compose multi-file merge rules
- https://docs.docker.com/compose/how-tos/multiple-compose-files/include/ — Docker Compose include (conflict-rejection)
- https://docs.ansible.com/projects/ansible/latest/tips_tricks/sample_setup.html — Ansible directory-based variable hierarchy
