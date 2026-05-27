---
task_id: "T02"
title: "Migrate all command functions to use CLIContext parameter"
status: "planned"
depends_on: ["T01"]
implements: ["FR#3", "AC#2", "AC#3", "AC#5"]
---

## Summary
Update all 6 command modules to receive `CLIContext` as an explicit parameter instead of reading from module-level globals. Each command function gains a `ctx` keyword-only parameter annotated with `Parameter(parse=False)`, replaces `cli_globals.json_mode` reads with `ctx.json_mode`, and passes `ctx` to `make_client()`. The corresponding test files are updated to pass `ctx=CLIContext(json_mode=True)` directly instead of patching `hassette.cli.globals.json_mode`.

## Prompt
Apply the same mechanical pattern to all 6 command files and their test files:

### Source file pattern (apply to each)

For each command file:
1. Remove `import hassette.cli.globals as cli_globals`
2. Add `from typing import Annotated` (if not already present)
3. Add `from cyclopts import Parameter` (if not already present)
4. Add `from hassette.cli.context import CLIContext`
5. Add `*, ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext()` as a keyword-only parameter to every command function (add after existing parameters, before the closing paren)
6. Replace `cli_globals.json_mode` → `ctx.json_mode` (some commands assign `json_mode = cli_globals.json_mode` first — replace with `json_mode = ctx.json_mode`)
7. Replace `make_client()` → `make_client(ctx)`

**Files and their command functions:**

- `src/hassette/cli/commands/status.py`: `cmd_status`, `cmd_telemetry`, `cmd_dashboard`
- `src/hassette/cli/commands/app.py`: `cmd_app`, `cmd_app_health`, `cmd_app_activity`, `cmd_app_config`, `cmd_app_source`
- `src/hassette/cli/commands/job.py`: `cmd_job`
- `src/hassette/cli/commands/listener.py`: `cmd_listener`
- `src/hassette/cli/commands/log.py`: `cmd_log`, `cmd_execution`
- `src/hassette/cli/commands/misc.py`: `cmd_config`, `cmd_event`

**Note on functions with existing parameters:**

Functions like `cmd_app_health(key, instance, since, source_tier)` already have positional/keyword parameters. Add `ctx` after a bare `*` separator if one doesn't exist, or after the existing parameters if `*` already separates keyword-only args. Example:

```python
def cmd_app_health(
    key: str,
    instance: InstanceArg = None,
    since: SinceArg = None,
    source_tier: SourceTierArg = None,
    *,
    ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext(),
) -> None:
```

For functions with no existing parameters (like `cmd_status()`, `cmd_telemetry()`), use:

```python
def cmd_status(*, ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext()) -> None:
```

### Test file pattern (apply to each)

For each test file:
1. Add `from hassette.cli.context import CLIContext`
2. Find every `patch("hassette.cli.globals.json_mode", True)` context manager
3. Remove it from the `with` block
4. Add `ctx=CLIContext(json_mode=True)` to the command function call inside that `with` block

**Test files and their patch locations:**

- `tests/unit/cli/test_commands_status.py`: lines 71, 140, 205
- `tests/unit/cli/test_commands_app.py`: lines 80, 231, 376, 445, 501
- `tests/unit/cli/test_commands_job.py`: lines 146, 278
- `tests/unit/cli/test_commands_listener.py`: lines 146, 278
- `tests/unit/cli/test_commands_log.py`: lines 169, 301
- `tests/unit/cli/test_commands_misc.py`: lines 62, 159

**Important:** Keep the `make_client` patches — they inject mock transports and are still needed. Only remove the `cli_globals.json_mode` patches.

## Focus
- The `Annotated` import may already exist in some command files (check before adding a duplicate).
- `cyclopts.Parameter` may already be imported in some files — check first.
- `cmd_job` and `cmd_listener` assign `json_mode = cli_globals.json_mode` to a local variable before using it. Replace the assignment with `json_mode = ctx.json_mode`.
- Some command functions have no `*` separator and all parameters have defaults (acting as keyword-only via convention). Add a bare `*` before `ctx` to make it explicitly keyword-only.
- In test files, when removing a `patch` from a multi-line `with` block, ensure the remaining context managers still have correct comma placement and parentheses.
- Run the test suite after all migrations to verify nothing broke: `timeout 300 uv run pytest tests/unit/cli/ -n 2 -v`
- The Verify section uses the same pytest command — ensure the flags match exactly when running verification

## Verify
- [ ] FR#3: Every command function that previously read `cli_globals.json_mode` now has `ctx: Annotated[CLIContext, Parameter(parse=False)]` in its signature
- [ ] AC#2: No test file contains `patch("hassette.cli.globals.*")` — verified by `grep -r "cli.globals\|cli_globals" tests/`
- [ ] AC#3: All 14 command functions that previously read globals have `ctx` in their signature
- [ ] AC#5: `timeout 300 uv run pytest tests/unit/cli/ -n 2` passes with zero failures
