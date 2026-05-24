---
task_id: "T02"
title: "Set up cyclopts framework and refactor entry point"
status: "done"
depends_on: ["T01"]
implements: ["FR#2", "FR#8", "FR#10", "AC#6", "AC#10"]
---

## Summary

Create the `cli/` package with cyclopts App setup and refactor `__main__.py` to delegate all argument parsing to cyclopts. The default command (no subcommand) starts the framework server with the same flags previously handled by argparse and pydantic-settings. Subcommand stubs are registered but implemented in later tasks. Shell tab completion is configured. The existing `test_main.py` tests are rewritten to test cyclopts dispatch.

## Prompt

### Create `src/hassette/cli/__init__.py`

Define the cyclopts `App` instance:
- App name: `"hassette"`
- Version: read from package metadata (`importlib.metadata.version("hassette")`)
- Register `--version` via cyclopts' built-in version flag support

Define the default command function (no subcommand → start server). This function:
1. Accepts HassetteConfig's top-level fields as CLI parameters: `--token`, `--base-url`, `--verify-ssl`, `--config-file`, `--env-file`, `--dev-mode`, and any other top-level fields on HassetteConfig. Check `src/hassette/config/config.py` lines 44-170 for the full field list.
2. Re-implements the short aliases from the removed `cli_shortcuts`: `-t` for `--token`, `-u`/`--url` for `--base-url`, `-c` for `--config-file`, `-e`/`--env` for `--env-file`. Use cyclopts parameter name aliases.
3. Passes non-None values as init kwargs to `HassetteConfig()` — cyclopts-parsed values become the highest priority in the pydantic-settings source chain.
4. Validates `config.token is not None` and raises `FatalError` if missing (from T01).
5. Calls `asyncio.run(main(config))` with the constructed config.
6. Wraps in the same exception handling structure as the current `entrypoint()` (KeyboardInterrupt, AppPrecheckFailedError, FatalError, generic Exception).

Create the `commands/` subdirectory with an empty `__init__.py`. The command modules are created in T05-T08 — register empty subcommand groups here as placeholders so the package structure is complete.

### Define shared flag types

Define reusable annotated types (or a module `cli/types.py`) for shared flags used across commands:
- `--since`: Custom cyclopts type converter. Converts to Unix epoch float. Exits non-zero with usage error on invalid format. Accepted formats (see `design/research/2026-05-24-cli-datetime-input/research.md`):
  - **Relative durations**: `Ns`, `Nm`, `Nh`, `Nd`, `Nw` (e.g., `1h`, `7d`, `30m`, `2w`). Single value + suffix only — no compound durations (`1h30m`), no `M` (months) or `y` (years).
  - **ISO 8601 with timezone**: `2026-05-22T14:00:00-04:00` or `2026-05-22T18:00:00Z` — used as-is.
  - **ISO 8601 naive**: `2026-05-22T14:00:00` — interpreted as **local time** (system timezone). This matches the Git/journalctl convention for user-facing CLI tools.
  - **Date only**: `2026-05-22` — interpreted as midnight local time (progressive omission, journalctl pattern).
  - No natural language ("yesterday", "last week"). Help text: `"Filter by time. Accepts relative (1h, 7d, 30m) or absolute (2026-05-22, 2026-05-22T14:00:00) timestamps. Naive timestamps use local time."`
- `--limit`: `int | None`, optional
- `--source-tier`: `Literal["app", "framework"] | None`, optional
- `--json`: `bool`, default False
- `--app`: `str | None`, optional
- `--instance`: `str | None`, optional (raw value — resolution happens in the client layer, T03)

### Refactor `src/hassette/__main__.py`

Replace the current argparse-based implementation:
1. Remove `get_parser()` function and argparse imports entirely
2. Remove the `main()` function's argparse call (`get_parser().parse_known_args()`)
3. `entrypoint()` now calls the cyclopts App's dispatch (e.g., `app()` or `app.main()`)
4. Keep `enable_logging(get_log_level(), log_format="auto")` call at the start of `entrypoint()`
5. The `main()` async function changes signature: accept a `HassetteConfig` parameter instead of constructing it internally from argparse args

### Shell completion

Register cyclopts shell completion support. cyclopts provides built-in completion for bash, zsh, and fish via a `--install-completion` flag or equivalent. Verify the exact API in cyclopts v4 docs and wire it up.

### Rewrite tests

`tests/unit/core/test_main.py` directly tests `get_parser()` and patches `hassette.__main__.get_parser`. These tests must be rewritten:
- Test that the default command (no subcommand) calls `asyncio.run(main(...))` with a HassetteConfig
- Test that SIGTERM handler registration still works (preserve the existing signal handling test logic)
- Test that `--config-file` and `--env-file` are passed through to HassetteConfig
- Test that `--version` prints the version and exits
- Remove all references to `get_parser` and argparse `Namespace`

### Unit tests (new)

- `--since` converter:
  - Relative: `1h` → epoch ~3600s ago, `7d` → epoch ~7 days ago, `30m` → epoch ~30min ago, `2w` → epoch ~14 days ago, `30s` → epoch ~30s ago
  - ISO 8601 with tz: `2026-05-22T14:00:00-04:00` → correct epoch
  - ISO 8601 naive: `2026-05-22T14:00:00` → epoch in local timezone (not UTC)
  - Date only: `2026-05-22` → epoch for midnight local time on that date
  - Invalid: `abc`, `1x`, `--`, empty → non-zero exit with usage error listing accepted formats
  - No compound: `1h30m` → non-zero exit (not supported)
- `--source-tier` accepts `app` and `framework`, rejects other values
- Default command passes CLI flags through to HassetteConfig init kwargs

## Focus

- `src/hassette/__main__.py`: lines 3 (argparse import), 18-38 (get_parser), 41-62 (main), 65-81 (entrypoint)
- `src/hassette/config/config.py`: HassetteConfig at line 44, field list lines 78-170, removed cli_shortcuts aliases at 63-68
- `tests/unit/core/test_main.py`: 3 tests that patch `get_parser` — all must be rewritten
- cyclopts App dispatch: the top-level `app()` call handles routing. The default command fires when no subcommand is given. Verify cyclopts v4 API for default command registration.
- The entry point in `pyproject.toml` (line 114) stays as `hassette = "hassette.__main__:entrypoint"` — unchanged

## Verify

- [ ] FR#2: Subcommand stubs are registered on the cyclopts App (each API resource has a noun-based subcommand name)
- [ ] FR#8: `hassette` with no arguments starts the framework server with config from env/flags
- [ ] FR#10: `hassette --install-completion` (or equivalent) enables shell tab completion
- [ ] AC#6: Running `hassette` with no arguments and a valid token starts the framework identically to the pre-change behavior
- [ ] AC#10: After running the completion installation command, tab completion suggests command names
