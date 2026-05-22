---
topic: "CLI tool for querying hassette API"
date: 2026-05-22
status: Final
---

# Prior Art: CLI Tool for Querying the Hassette API

## The Problem

Hassette is a long-running async daemon that exposes telemetry and control via a FastAPI web service (~24 REST endpoints + WebSocket). There's no way to query hassette from the terminal — checking app status, viewing listeners, tailing logs, or inspecting scheduler jobs requires the browser UI or raw curl/httpie. A typed CLI tool would provide fast terminal access with proper output formatting and shared response models.

## How We Do It Today

Hassette has a minimal argparse entry point (`hassette`) that only starts the framework — 3 flags (`--config-file`, `--env-file`, `--version`). No subcommands, no query capabilities. pydantic-settings is already used extensively for hierarchical config (`HassetteConfig` with env vars, dotenv, TOML sources). The web API has rich Pydantic response models (`SystemStatusResponse`, `ListenerWithSummary`, `JobSummary`, etc.) that a CLI could import directly.

## CLI Framework Evaluation

Three frameworks were evaluated for CLI parsing. Click and Typer were excluded early — the decorator-heavy approach was considered the wrong direction for a model-first project.

### pydantic-settings CLI

**Used by**: Projects using pydantic-settings v2.x+ with `CliApp`, `CliSubCommand`, `CliPositionalArg`

Config-first approach — define settings models, get CLI as a side effect. Already a hassette dependency. Layered settings (CLI > env > dotenv > defaults) for free. But weaker CLI-specific features: limited tab completion, less customizable help formatting, newer and less battle-tested. Async `cli_cmd` should only be on leaf subcommands.

**Verdict**: Good for simple CLIs but may hit a ceiling as complexity grows. No new dependency, but limited escape hatches.

### tyro (brentyi/tyro)

**Vitals**: 4.5 years old, v1.0.13 stable, 1,051 stars, MIT, bus factor 1

Pure model-first — Union types become subcommands, no decorators. 4 core deps (minimal). Excellent Pydantic v1+v2 support, plugin registry for extensibility. 2,335 tests, 8 Python version CI matrix. But CLI-only — no settings layering, no config file integration. Bash/Zsh completion via shtab. Help text is functional but not rich.

**Verdict**: Elegant and well-engineered but CLI-only. Would need supplementing for rich output and config. May hit a ceiling on CLI-specific customizations.

### cyclopts (BrianPugh/cyclopts)

**Vitals**: 2.5 years old, v4.15.0 (v5.0.0 alpha), 1,165 stars, Apache 2.0, bus factor 1

Decorator-based like Click but with native type coercion and Pydantic support. Rich-based help formatting (4 formatters), Bash/Zsh/Fish completion with install helpers, built-in config sources (JSON, TOML, YAML, env vars), async support (trio + asyncio). 1,242 tests, 15-combo CI matrix (3 OS x 5 Python). Well-designed for scale — stack-based dispatch, lazy command resolution, parameter groups.

**Key signal**: Prefect migrated their entire CLI from Typer to cyclopts in Prefect 3.6. FastMCP also migrated. Prefect cited: eliminating Click dependency chain, better type annotation support, Python function signatures mapping directly to CLI behavior, ~38% shorter implementations.

**Verdict**: Production-grade, scales well, best-in-class help/completion, Pydantic-native. Strong real-world validation from Prefect.

### Decision

**cyclopts** — best combination of Pydantic integration, CLI features, and room to grow. The Prefect migration validates it at scale. Rich is already included as a dependency (needed for human-readable output anyway). The decorator pattern is philosophically closer to Click/Typer but the type-driven coercion makes it feel different in practice.

## Entry Point & Packaging Patterns

### Pattern: Same Package, CLI as Optional Extra

**Used by**: FastAPI (`fastapi[standard]`), various framework projects

Core package installs without CLI deps. A `[cli]` extra pulls in CLI tooling. Entry point always registered in pyproject.toml but catches ImportError gracefully, printing install instructions. One package, one version — no client/server version mismatch.

### Pattern: Single Binary with Subcommand Groups

**Used by**: Celery, Airflow, Prefect, Dagster, kubectl, docker

One entry point binary exposes all functionality through subcommand groups. Server and query commands share the same binary. High discoverability.

### Pattern: Separate Server and Client Binaries

**Used by**: Home Assistant (`hass` + `hass-cli`), Supervisor, Redis, PostgreSQL

Clean separation but two packages to maintain. Version compatibility management overhead.

### Direction for hassette

Combine same-package extra with single binary subcommands. `hassette[cli]` extra for deps. Extend the existing `hassette` entry point with subcommands. When no subcommand is given, fall back to starting the framework (backwards compat).

## Output Formatting

### Pattern: Dual Output with --json Flag

**Used by**: GitHub CLI (gh), kubectl, docker, Heroku CLI, Celery, AWS CLI

Human-readable tables by default, `--json` for structured JSON. Heroku CLI style guide codifies: flat grep-parseable tables, full data in JSON (not truncated), stdout for data, stderr for progress. Rich auto-strips formatting when piped.

This matches the user's existing CLI conventions (ha-api, monarch-api, etc.).

## Anti-Patterns

- **Bundling all deps in core**: CLI deps should be optional. FastAPI learned this. ([source](https://github.com/fastapi/fastapi/pull/11935))
- **Section-header tables**: Flat tables with a type/category column are always better than grouped tables with dividers. ([source](https://devcenter.heroku.com/articles/cli-style-guide))
- **Underscores in extra names**: Use hyphens (`hassette[cli]` not `hassette[cli_tools]`). ([source](https://hynek.me/articles/python-recursive-optional-dependencies/))

## Sources

### Reference implementations
- https://github.com/PrefectHQ/prefect/pull/20838 — Prefect CLI migration from Typer to cyclopts
- https://github.com/PrefectHQ/fastmcp/pull/1062 — FastMCP CLI migration to cyclopts
- https://github.com/BrianPugh/cyclopts — cyclopts repository
- https://github.com/brentyi/tyro — tyro repository
- https://github.com/fastapi/fastapi/pull/11935 — FastAPI [standard] extras pattern

### Blog posts & writeups
- https://hynek.me/articles/python-recursive-optional-dependencies/ — Recursive optional deps
- https://www.maskset.net/blog/2025/07/01/improving-python-clis-with-pydantic-and-dataclasses/ — Model-first CLI patterns

### Documentation & standards
- https://cyclopts.readthedocs.io/en/latest/vs_typer/README.html — Cyclopts vs Typer comparison
- https://cyclopts.readthedocs.io/en/latest/migration/typer.html — Cyclopts migration guide from Typer
- https://devcenter.heroku.com/articles/cli-style-guide — Heroku CLI style guide (output formatting)
- https://docs.celeryq.dev/en/stable/reference/cli.html — Celery CLI reference
- https://brentyi.github.io/tyro/ — tyro documentation
