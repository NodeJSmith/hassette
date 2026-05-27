---
task_id: "T03"
title: "Delete globals module and run final verification"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#5", "AC#1", "AC#6"]
---

## Summary
Delete `src/hassette/cli/globals.py` now that all consumers have been migrated to use `CLIContext`. Remove the remaining `cli_globals.*` assignments from the launcher in `__init__.py` (they were kept temporarily during T01 for backward compatibility while commands still read them). Run the full CLI test suite and type checker to confirm a clean state.

## Prompt
1. **Remove `cli_globals` assignments from `src/hassette/cli/__init__.py`**:
   - Remove `import hassette.cli.globals as cli_globals`
   - Remove the 4 lines that set `cli_globals.env_file_override`, `cli_globals.config_file_override`, `cli_globals.json_mode`, `cli_globals.debug_mode`
   - Keep the `HassetteConfig.model_config` and `AppConfig.model_config` mutations (env_file and config_file lines) — those are unrelated

2. **Delete `src/hassette/cli/globals.py`**

3. **Verify no remaining references**:
   - Run `grep -r "cli.globals\|cli_globals" src/ tests/` — must return no matches
   - Run `grep -r "make_client()" src/` (no-argument calls) — must return no matches (only `make_client(ctx)` calls should remain, plus the function definition which now requires ctx)

4. **Run type checker**: `uv run pyright src/hassette/cli/` — must report no new errors

5. **Run full CLI test suite**: `timeout 300 uv run pytest tests/unit/cli/ -n 2 -v` — all tests must pass

## Focus
- The `HassetteConfig.model_config["env_file"]` and `AppConfig.model_config["env_file"]` mutations in the launcher (lines 146-150 in `__init__.py`) must NOT be removed — they configure Pydantic settings for the running process and are unrelated to the CLI globals.
- After deleting `globals.py`, any missed import will surface as an immediate `ImportError` — the grep in step 3 catches this before running tests.
- `make_client` is defined in `client.py` with signature `make_client(ctx: CLIContext)`. Any zero-argument call that was missed will be caught by pyright as a missing argument error.

## Verify
- [ ] FR#5: `src/hassette/cli/globals.py` does not exist and `grep -r "cli_globals\|cli\.globals" src/` returns no matches
- [ ] AC#1: No module named `globals` exists in the CLI package
- [ ] AC#6: `uv run pyright src/hassette/cli/` exits with code 0 and reports 0 errors
