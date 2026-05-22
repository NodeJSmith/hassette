# Brief: CLI Query Tool for Hassette

**Date:** 2026-05-22
**Status:** explored

## Idea

A CLI tool integrated into the hassette package (`hassette[cli]`) that lets users query hassette's REST API from the terminal. Uses cyclopts for CLI parsing and shares Pydantic response models with the server to avoid type duplication. Extends the existing `hassette` binary with subcommands — `hassette status`, `hassette apps`, `hassette logs`, etc. Human-readable output by default with a `--json` flag for scripting.

## Key Decisions Made

- **CLI framework**: cyclopts (v4.x, pinned). Chosen over pydantic-settings CLI (too limited for future growth), tyro (CLI-only, no rich help), and click/typer (wrong direction — decorator-heavy without type-driven coercion). Validated by Prefect's migration from Typer to cyclopts in Prefect 3.6.
- **Entry point**: Extend the existing `hassette` binary with subcommands. No subcommand = start the framework (backwards compat). No separate binary.
- **Output format**: Human-readable tables by default (Rich), `--json` for structured JSON (Pydantic `.model_dump_json()`). Matches existing personal CLI conventions (ha-api, monarch-api).
- **Packaging**: `hassette[cli]` optional extra. Entry point always registered; catches ImportError and prints install instructions. cyclopts and rich go in the extra (rich is already a cyclopts dep).
- **Server discovery**: Instantiate `HassetteConfig` from the same config sources (env vars, .env, TOML) and derive API URL from `web_api.host` / `web_api.port`. No separate CLI config mechanism.
- **v1 scope**: All GET (read-only) endpoints. Mutations (start/stop/reload) and WebSocket streaming deferred.
- **cyclopts version**: Pin to v4.x. Evaluate v5 after it stabilizes and after initial CLI ships.

## Open Questions

- **HassetteConfig partial loading**: Can the CLI instantiate `HassetteConfig` without HA-specific required fields (token, base_url)? May need to load just the `WebApiConfig` section or make HA fields optional with sentinel defaults.
- **HTTP client**: httpx (async) or plain httpx sync? The CLI queries are request-response — async may not be needed for v1, but cyclopts has async support if we want it later.
- **Subcommand grouping**: Should telemetry endpoints be under `hassette telemetry <app_key> health` or flattened to `hassette app-health <app_key>`? Depth vs. discoverability tradeoff.
- **Shared query params**: Several endpoints share `--since`, `--source-tier`, `--app-key`, `--limit`. How to share these across subcommands without duplication (cyclopts' `default_parameter` inheritance? shared base model?).

## Scope Boundaries

**In scope (v1):**
- All GET endpoints (~20 read-only queries)
- Human-readable + --json output
- `hassette[cli]` optional extra packaging
- Server discovery via HassetteConfig
- Tab completion (bash/zsh/fish via cyclopts)

**Explicitly out (v2+):**
- Mutations: `hassette app start/stop/reload`
- WebSocket streaming: `hassette logs --follow`, `hassette events --watch`
- Interactive features: prompts, selection menus
- Config file management: `hassette config set/get`
- Multi-instance profiles (named server configs)

**Deferred:**
- cyclopts v5 migration
- Documentation site pages for CLI usage

## Risks and Concerns

- **cyclopts v5 breaking changes**: v5-develop has hierarchical parsing overhaul and fuzzy matching deprecation. Pinning to v4 mitigates this but creates a future migration. The migration should be manageable given hassette's CLI scope.
- **Bus factor**: cyclopts is a single-maintainer project (Brian Pugh, ~96% of commits). Mitigated by: Apache 2.0 license (forkable), active maintenance, growing community (1,165 stars, 30 contributors), and Prefect's adoption adding ecosystem pressure to maintain.
- **HassetteConfig coupling**: Reusing the server's config for CLI discovery is elegant but couples the CLI to the full config schema. If HassetteConfig grows complex fields with strict validation, the CLI may break on instantiation. Need a clean fallback.
- **Rich as a dependency**: cyclopts pulls in rich, which is a non-trivial dependency. This is acceptable for the `[cli]` extra (users who install it want terminal output), but reinforces that CLI deps must stay optional.

## Codebase Context

- **Existing entry point**: `src/hassette/__main__.py` uses argparse with `parse_known_args()` for `--config-file`, `--env-file`, `--version`. Will need to be refactored to integrate cyclopts subcommands.
- **Response models**: `src/hassette/web/models.py` has all Pydantic response models (SystemStatusResponse, ListenerWithSummary, JobSummary, etc.) — the CLI imports these directly.
- **Config system**: `src/hassette/config/config.py` uses pydantic-settings BaseSettings with env, dotenv, TOML sources. `WebApiConfig` section has `host`, `port`, `run`, `run_ui` fields.
- **No existing CLI deps**: No click, typer, rich, or tabulate in current dependencies. Clean starting point.
- **Prior art saved**: `design/research/2026-05-22-cli-tool-prior-art/research.md`
