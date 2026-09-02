---
task_id: "T03"
title: "Add CLI start/stop/reload commands with instance support"
status: "planned"
depends_on: []
implements: ["FR#10", "FR#11", "FR#12", "FR#13", "FR#14", "AC#6", "AC#7", "AC#8", "AC#9", "AC#10"]
---

## Summary

Add a `post()` method to the CLI client, then add `start`, `stop`, and `reload` subcommands to `hassette app`. Each command takes a positional `key` and optional `--instance` flag. `stop` and `reload` prompt for confirmation (`--yes` bypasses). Success messages are instance-aware when `--instance` is provided. This task is independent of the frontend tasks and can run in parallel with T01/T02.

## Target Files

- modify: `src/hassette/cli/client.py`
- modify: `src/hassette/cli/commands/app.py`
- modify: `src/hassette/cli/__init__.py`
- modify: `tests/unit/cli/test_commands_app.py`
- read: `src/hassette/cli/types.py`
- read: `src/hassette/cli/context.py`
- read: `src/hassette/web/models.py`
- read: `design/specs/107-instance-actions-ui-cli/design.md`

## Prompt

### CLI client post method

In `src/hassette/cli/client.py`, add a `post()` method to `HassetteCLIClient` modeled after the existing `get()` method (lines 101-148). Key differences:
- Calls `self._client.post(path, timeout=self.timeout)` instead of `.get()`.
- No `params` argument (POST action routes take no query params).
- No `tolerate_503` (action routes don't return 503 with a valid body).
- Return type: deserialized `ActionResponse` (import from `hassette.web.models`).

The `get()` method's error handling pattern (`ConnectError`, `TimeoutException`, `RequestError` → `_handle_network_error`; non-success → `_handle_http_error`) should be reused identically.

### Action commands

In `src/hassette/cli/commands/app.py`, add three functions:

```python
def cmd_app_start(key: str, instance: InstanceArg = None, *, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
def cmd_app_stop(key: str, instance: InstanceArg = None, yes: Annotated[bool, Parameter(name=["--yes"])] = False, *, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
def cmd_app_reload(key: str, instance: InstanceArg = None, yes: Annotated[bool, Parameter(name=["--yes"])] = False, *, ctx: CLIContextParam = DEFAULT_CLI_CONTEXT) -> None:
```

Each command:
1. Creates a client via `make_client(ctx)`.
2. If `--instance` is provided, resolves it via `client.resolve_instance(key, instance)` to get the index, then POSTs to `/api/apps/{key}/instances/{index}/{action}`.
3. Without `--instance`, POSTs to `/api/apps/{key}/{action}`.
4. For `stop` and `reload`: before POSTing, prompt for confirmation unless `--yes` is set. Use a simple `input()` prompt with `[y/N]` default. Example: `"Stop app 'my_app'? [y/N] "` or `"Reload instance 'office' of 'my_app'? [y/N] "`. Exit cleanly on "n" or empty input.
5. Construct a past-tense success message: `start→started`, `stop→stopped`, `reload→reloaded`. Include instance name when `--instance` is provided (e.g., `Instance 'office' of 'my_app' reloaded`), use app-level text otherwise (e.g., `App 'my_app' reloaded`).
6. Print the message to stdout (or use the CLI output module's print function if one exists).

Import `Parameter` from `cyclopts` and `Annotated` from `typing` for the `--yes` flag.

### Command registration

In `src/hassette/cli/__init__.py`, import the three new functions and register them:

```python
from hassette.cli.commands.app import cmd_app_start, cmd_app_stop, cmd_app_reload
apps_app.command(cmd_app_start, name="start")
apps_app.command(cmd_app_stop, name="stop")
apps_app.command(cmd_app_reload, name="reload")
```

Add these imports alongside the existing `cmd_app` imports at line 9.

### Tests

Add test cases to `tests/unit/cli/test_commands_app.py`:

- `cmd_app_start("my_app")` sends `POST /api/apps/my_app/start` — mock `client.post()`.
- `cmd_app_start("my_app", instance="1")` resolves instance and sends `POST /api/apps/my_app/instances/1/start`.
- `cmd_app_stop` and `cmd_app_reload` follow the same routing pattern.
- `cmd_app_stop` prompts for confirmation; "n" or empty input exits without POSTing.
- `cmd_app_stop` with `yes=True` skips the prompt.
- `cmd_app_start` does not prompt.
- Success message includes instance name when `--instance` provided.
- Error on 404 (app not found, instance out of range) surfaces via `_handle_http_error`.

See design doc `## Architecture → CLI` and `## Convention Examples` for the implementation patterns.

## Focus

- The CLI client currently has only `get()` — no `post()` method exists. Model it after `get()` but simpler (no params, no tolerate_503, no overloads needed for a single return type).
- `InstanceArg` is defined in `src/hassette/cli/types.py:104-108` as `Annotated[str | None, ...]` with `name=["--instance"]`.
- `resolve_instance()` at `client.py:196-229` handles both integer strings and instance names. It fetches manifests, which means the first call with `--instance <name>` makes an extra HTTP request. This is the existing pattern — don't change it.
- `ActionResponse` in `src/hassette/web/models.py:447-452` has `status: Literal["accepted"]`, `app_key: str`, `action: str`.
- The existing CLI tests in `test_commands_app.py` mock the HTTP client at `HassetteCLIClient` level. Follow the same mocking pattern.
- For the confirmation prompt, `input()` works for interactive use. In tests, mock `builtins.input` to simulate user responses.
- `cyclopts.Parameter` is already imported in `types.py` — import it directly in `commands/app.py` for the `--yes` flag.

## Verify

- [ ] FR#10: `hassette app start my_app` sends `POST /api/apps/my_app/start`
- [ ] FR#11: `hassette app start my_app --instance 1` sends `POST /api/apps/my_app/instances/1/start`
- [ ] FR#12: `stop` and `reload` follow the same routing pattern
- [ ] FR#13: Success message includes instance name when `--instance` provided; uses app-level text otherwise
- [ ] FR#14: `stop` and `reload` prompt for confirmation; `--yes` bypasses; `start` does not prompt
- [ ] AC#6: CLI test confirms `start` without `--instance` hits app-level route
- [ ] AC#7: CLI test confirms `start` with `--instance 1` hits instance route
- [ ] AC#8: CLI tests confirm `stop` and `reload` follow same routing
- [ ] AC#9: CLI test confirms confirmation prompt and `--yes` bypass
- [ ] AC#10: CLI test confirms instance-aware success message
