# Design: Replace CLI module globals with explicit context object

**Date:** 2026-05-27
**Status:** archived
**Scope-mode:** hold

## Problem

The CLI passes configuration state (output format, debug verbosity, config file overrides) between the launcher and individual commands through module-level mutable globals. This creates implicit coupling: every command function silently depends on state set elsewhere, the dependency graph is invisible at the function signature level, and tests must use `mock.patch` on module attributes instead of passing values directly. The same pattern is duplicated across the client factory, making it impossible to construct a correctly-configured client without first mutating global state.

## Goals

- Eliminate all module-level mutable globals from the CLI subsystem
- Make every command function's dependencies explicit in its signature
- Enable tests to pass configuration values directly without patching module state
- Preserve all existing CLI user-facing behavior (flags, output, error handling)

## Non-Goals

- Changing CLI flag names, command names, or user-facing output format
- Refactoring the cyclopts app registration structure
- Modifying the `cmd_run` command (it does not use globals)

## User Scenarios

### Developer: Framework maintainer
- **Goal:** add or modify CLI commands with clear, testable interfaces
- **Context:** writing new commands or modifying existing ones

#### Adding a new command
1. **Define the command function**
   - Sees: existing command functions with explicit `ctx` parameter in their signatures
   - Decides: which context fields the command needs
   - Then: adds `ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext()` and passes `ctx` to `make_client(ctx)`

#### Writing a test for a command
1. **Call the command directly**
   - Sees: command function accepts `ctx` as a keyword argument
   - Decides: which context values to set for the test scenario
   - Then: passes `ctx=CLIContext(json_mode=True)` directly — no `mock.patch` needed

### Operator: CLI user
- **Goal:** use hassette CLI commands with global flags
- **Context:** running commands from a terminal

#### Using global flags
1. **Run a command with --json**
   - Sees: same output as before
   - Decides: N/A — behavior unchanged
   - Then: JSON output printed to stdout, identical to current behavior

## Functional Requirements

- **FR#1** A frozen dataclass holds CLI configuration (output format, debug mode, env file override, config file override)
- **FR#2** The meta launcher constructs the context object from parsed global flags and injects it into the resolved command
- **FR#3** Every command function that uses CLI configuration receives it as an explicit parameter
- **FR#4** The client factory accepts the context object as a parameter instead of reading module-level state
- **FR#5** The module containing the mutable globals is deleted with no remaining importers

## Edge Cases

- **Default context values:** When no global flags are passed, the context object uses safe defaults (json_mode=False, debug_mode=False, overrides=None) — identical to the current globals defaults
- **Frozen mutation attempt:** Any accidental attempt to mutate the context after construction raises `FrozenInstanceError`
- **Command with no context dependency:** `cmd_run` does not use globals and should not gain a `ctx` parameter

## Acceptance Criteria

- **AC#1** No module named `globals` exists in the CLI package (FR#5)
- **AC#2** No test uses `patch("hassette.cli.globals.*")` (FR#3, FR#4)
- **AC#3** Every command function that previously read globals has `ctx` in its signature (FR#3)
- **AC#4** `make_client` requires an explicit context parameter with no fallback to module state (FR#4)
- **AC#5** All existing CLI tests pass with no behavior change (all FRs)
- **AC#6** The type checker reports no new errors in the CLI package (all FRs)

## Key Constraints

- The context injection mechanism must work through cyclopts' sub-app dispatch — the launcher resolves commands via `app.parse_args()` and injects the context into `bound.arguments` before calling the resolved command
- `bound.kwargs` on `inspect.BoundArguments` is a read-only computed property — injection must go through `bound.arguments` directly
- Parameters annotated with `Parameter(parse=False)` appear in the `ignored` dict from `parse_args`, not in `bound.kwargs` — the injection must target the argument by name in `bound.arguments`

## Dependencies and Assumptions

- cyclopts 4.15.0 (current version) supports `Parameter(parse=False)` and `app.parse_args()` returning `(command, bound, ignored)` tuples
- No external systems or teams are affected — this is an internal refactoring

## Architecture

### CLIContext dataclass

New file `src/hassette/cli/context.py`:

```python
@dataclass(frozen=True)
class CLIContext:
    json_mode: bool = False
    debug_mode: bool = False
    env_file_override: str | None = None
    config_file_override: str | None = None
```

Frozen dataclass (not Pydantic) — pure transport object with no validation needs.

### Launcher injection

In `src/hassette/cli/__init__.py`, the `launcher()` meta default replaces `app(tokens)` with:

```python
ctx = CLIContext(json_mode=json, debug_mode=debug, env_file_override=env_file, config_file_override=config_file)
command, bound, _ignored = app.parse_args(tokens)
bound.arguments["ctx"] = ctx
command(*bound.args, **bound.kwargs)
```

### Command function signature

Every command that previously read `cli_globals.json_mode` gains a keyword-only `ctx` parameter:

```python
def cmd_status(*, ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext()) -> None:
    client = make_client(ctx)
    result = client.get("/api/health", SystemStatusResponse)
    render_detail(result, json_mode=ctx.json_mode)
```

### Client factory

`make_client()` becomes `make_client(ctx: CLIContext)` — reads env/config overrides and json/debug mode from the context object instead of globals.

## Replacement Targets

| Target | File | Replaced by | Action |
|---|---|---|---|
| `cli_globals.json_mode` | 6 command files | `ctx.json_mode` | Remove import, add ctx param |
| `cli_globals.debug_mode` | `client.py` via `make_client()` | `ctx.debug_mode` | Remove import, add ctx param |
| `cli_globals.env_file_override` | `client.py` via `make_client()` | `ctx.env_file_override` | Remove import, add ctx param |
| `cli_globals.config_file_override` | `client.py` via `make_client()` | `ctx.config_file_override` | Remove import, add ctx param |
| `src/hassette/cli/globals.py` | entire file | `src/hassette/cli/context.py` | Delete after all callers migrated |

## Convention Examples

### Command function pattern (current)

**Source:** `src/hassette/cli/commands/status.py`

```python
def cmd_status() -> None:
    """Show system status (GET /api/health)."""
    client = make_client()
    result = client.get("/api/health", SystemStatusResponse)
    render_detail(result, json_mode=cli_globals.json_mode)
```

### Command test pattern (current — to be replaced)

**Source:** `tests/unit/cli/test_commands_status.py`

```python
def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
    status_data = make_system_status_response()
    client, _ = cli_client_factory.build_with_routes([("GET", "/api/health", 200, status_data.model_dump())])
    captured_stdout: list[str] = []
    with (
        patch("hassette.cli.commands.status.make_client", return_value=client),
        patch("sys.stdout.write", side_effect=capture_write),
        patch("hassette.cli.globals.json_mode", True),
    ):
        cmd_status()
```

DO: Pass `ctx=CLIContext(json_mode=True)` directly to the command function.
DON'T: Patch module globals to set json_mode.

### CLIClientFactory.build_with_routes

**Source:** `tests/unit/cli/conftest.py`

```python
def build_with_routes(
    self,
    routes: list[tuple[str, str, int, Any]],
    json_mode: bool = False,
) -> tuple[HassetteCLIClient, MockTransportBuilder]:
    builder = MockTransportBuilder()
    for method, path_fragment, status, body in routes:
        builder.add(method, path_fragment, status, body)
    transport = builder.build()
    client = self.build(transport, json_mode=json_mode)
    return client, builder
```

## Alternatives Considered

### Single module-level context holder with get/set accessors

Replace 4 globals with 1 `_current_ctx: CLIContext` variable and `get_ctx()`/`set_ctx()` accessors. Commands read via `get_ctx()`. Tests patch one target instead of four.

**Rejected because:** Still module-level mutable state. Tests still need `mock.patch` (one target instead of four, but still patching). Doesn't satisfy the DI invariant — commands don't receive their dependency as a parameter.

### functools.partial rebinding on App registrations

Before `app(tokens)`, replace registered command callables with `functools.partial(cmd, ctx=ctx)`.

**Rejected because:** Mutates `App` registrations at dispatch time. Fragile if cyclopts caches or copies registration state. Module-level `App` objects are shared across test invocations in the same process.

## Test Strategy

### Existing Tests to Adapt

All 6 command test files need migration (16 patches total):

- `tests/unit/cli/test_commands_app.py` — 5 `patch("hassette.cli.globals.json_mode", True)` at lines 80, 231, 376, 445, 501
- `tests/unit/cli/test_commands_job.py` — 2 patches at lines 146, 278
- `tests/unit/cli/test_commands_listener.py` — 2 patches at lines 146, 278
- `tests/unit/cli/test_commands_log.py` — 2 patches at lines 169, 301
- `tests/unit/cli/test_commands_misc.py` — 2 patches at lines 62, 159
- `tests/unit/cli/test_commands_status.py` — 3 patches at lines 71, 140, 205

Each patch is replaced by passing `ctx=CLIContext(json_mode=True)` to the command function call.

### New Test Coverage

- `tests/unit/cli/test_context.py` (new file):
  - `test_defaults` — `CLIContext()` has correct defaults (FR#1)
  - `test_frozen` — assigning to a field raises `FrozenInstanceError` (FR#1)
  - `test_make_client_receives_context` — `make_client(ctx)` passes json_mode and debug_mode to the client (FR#4)
  - `test_launcher_injects_ctx` — smoke test: call meta app with `--json status`, verify command receives `ctx.json_mode=True` (FR#2)

### Tests to Remove

No tests to remove — all existing tests are adapted, not deleted.

## Documentation Updates

No documentation updates required. This is an internal refactoring with no change to CLI user-facing behavior, no new flags, and no change to existing documentation. The CLI help text is auto-generated by cyclopts and will be unchanged.

## Impact

### Changed Files

**Created:**
- `src/hassette/cli/context.py` — CLIContext frozen dataclass
- `tests/unit/cli/test_context.py` — CLIContext and injection tests

**Deleted:**
- `src/hassette/cli/globals.py`

**Modified (cross-cutting):**
- `src/hassette/cli/__init__.py` — launcher injection mechanism (highest risk: changes dispatch path)
- `src/hassette/cli/client.py` — `make_client(ctx)` signature change

**Modified (mechanical):**
- `src/hassette/cli/commands/app.py` — add ctx param, replace globals reads
- `src/hassette/cli/commands/job.py` — add ctx param, replace globals reads
- `src/hassette/cli/commands/listener.py` — add ctx param, replace globals reads
- `src/hassette/cli/commands/log.py` — add ctx param, replace globals reads
- `src/hassette/cli/commands/misc.py` — add ctx param, replace globals reads
- `src/hassette/cli/commands/status.py` — add ctx param, replace globals reads
- `tests/unit/cli/test_commands_app.py` — replace 5 globals patches with ctx=
- `tests/unit/cli/test_commands_job.py` — replace 2 globals patches with ctx=
- `tests/unit/cli/test_commands_listener.py` — replace 2 globals patches with ctx=
- `tests/unit/cli/test_commands_log.py` — replace 2 globals patches with ctx=
- `tests/unit/cli/test_commands_misc.py` — replace 2 globals patches with ctx=
- `tests/unit/cli/test_commands_status.py` — replace 3 globals patches with ctx=

### Behavioral Invariants

- All existing CLI flags (`--json`, `--debug`, `--env-file`, `--config-file`) must continue to work identically
- All command output (human and JSON modes) must be unchanged
- Error handling behavior (HTTP errors, network errors, usage errors) must be unchanged
- The `cmd_run` command must remain unaffected

### Blast Radius

Limited to the CLI subsystem. No changes to the web API, core framework, apps, bus, scheduler, or any runtime component. The CLI is a standalone synchronous client that queries the hassette REST API — no shared state with the running server.

## Open Questions

None — the injection mechanism is proven by proof-of-concept, and all affected code has been surveyed.
