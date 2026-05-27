---
task_id: "T01"
title: "Create CLIContext, update make_client, and wire launcher injection"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#4", "AC#4"]
---

## Summary
Create the `CLIContext` frozen dataclass that replaces the 4 module-level mutable globals, update `make_client()` to accept it as an explicit parameter, and wire the cyclopts meta launcher to inject `ctx` into resolved commands via `app.parse_args()` + `bound.arguments`. This task builds the complete injection pipeline — subsequent tasks migrate commands and tests to use it.

## Prompt
1. **Create `src/hassette/cli/context.py`** with a frozen dataclass:
   ```python
   @dataclass(frozen=True)
   class CLIContext:
       json_mode: bool = False
       debug_mode: bool = False
       env_file_override: str | None = None
       config_file_override: str | None = None
   ```

2. **Update `src/hassette/cli/client.py`**:
   - Add `from hassette.cli.context import CLIContext`
   - Change `make_client()` signature to `make_client(ctx: CLIContext)` (required parameter, no default)
   - Replace `cli_globals.env_file_override` → `ctx.env_file_override`, etc. inside `make_client`
   - Keep `import hassette.cli.globals as cli_globals` for now — it will be removed in T03 after all commands are migrated. But `make_client` itself must no longer read from it.

   Wait — `make_client` is the only consumer of `cli_globals` in `client.py`. Remove the import in this task since `make_client` no longer uses it.

3. **Update `src/hassette/cli/__init__.py`** launcher:
   - Add `from hassette.cli.context import CLIContext`
   - In `launcher()` (lines 127-152), the current body is:
     ```python
     cli_globals.env_file_override = env_file
     cli_globals.config_file_override = config_file
     cli_globals.json_mode = json
     cli_globals.debug_mode = debug

     if env_file:
         HassetteConfig.model_config["env_file"] = env_file
         AppConfig.model_config["env_file"] = env_file
     if config_file:
         HassetteConfig.model_config["toml_file"] = config_file

     app(tokens)
     ```
   - Replace the body with:
     ```python
     cli_globals.env_file_override = env_file
     cli_globals.config_file_override = config_file
     cli_globals.json_mode = json
     cli_globals.debug_mode = debug
     ctx = CLIContext(json_mode=json, debug_mode=debug, env_file_override=env_file, config_file_override=config_file)
     command, bound, ignored = app.parse_args(tokens)
     bound.arguments["ctx"] = ctx
     command(*bound.args, **bound.kwargs)
     ```
   - Keep the `cli_globals.*` assignments — they are still read by command functions until T02 migrates them. The `HassetteConfig`/`AppConfig` env_file and config_file mutations (lines 146-150) must also remain.

4. **Create `tests/unit/cli/test_context.py`** with these tests:
   - `test_defaults`: `CLIContext()` has `json_mode=False`, `debug_mode=False`, both overrides `None`
   - `test_frozen_raises_on_mutation`: assigning to a field raises `dataclasses.FrozenInstanceError`
   - `test_make_client_receives_json_mode`: call `make_client(CLIContext(json_mode=True))` with a mock transport (use `CLIClientFactory` from conftest), verify `client.json_mode is True`
   - `test_make_client_receives_debug_mode`: same for `debug_mode`
   - `test_launcher_injects_ctx`: integration smoke test — build a minimal cyclopts app that mirrors the launcher pattern, verify the command receives `ctx.json_mode=True` when `--json` is passed. Do NOT test against the real `app` object from `__init__.py` — that would pull in all command registrations.

## Focus
- `bound.kwargs` on `inspect.BoundArguments` is a read-only computed property — mutations are silently ignored. You MUST use `bound.arguments["ctx"] = ctx`.
- `Parameter(parse=False)` causes the parameter to appear in the `ignored` dict from `parse_args()`, not in `bound`. The injection into `bound.arguments` is what makes it available to the command.
- The existing `make_client` patches in tests (`patch("hassette.cli.commands.*.make_client", return_value=client)`) are unaffected by the signature change because they mock `make_client` entirely — the patched version never calls the real function.
- Keep `cli_globals.*` assignments in the launcher temporarily — commands still read them until T02 migrates them.
- The `HassetteConfig.model_config` mutations for env_file and config_file (lines 146-150 in `__init__.py`) are unrelated to this refactor and must remain.

## Verify
- [ ] FR#1: `CLIContext` is a frozen dataclass with fields `json_mode`, `debug_mode`, `env_file_override`, `config_file_override` and correct defaults
- [ ] FR#2: The launcher uses `app.parse_args(tokens)` + `bound.arguments["ctx"] = ctx` + `command(*bound.args, **bound.kwargs)` instead of `app(tokens)`
- [ ] FR#4: `make_client` requires an explicit `CLIContext` parameter and reads all config from it (no `cli_globals` references in `make_client`)
- [ ] AC#4: `make_client(ctx: CLIContext)` has no fallback to module state — calling `make_client()` with no arguments raises `TypeError`
