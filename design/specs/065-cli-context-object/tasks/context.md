# Context: CLI Context Object

## Problem & Motivation
The CLI subsystem passes configuration state (output format, debug verbosity, config file overrides) through 4 module-level mutable globals in `src/hassette/cli/globals.py`. Every command function silently depends on state set elsewhere — the dependency graph is invisible at the function signature level, and tests must use `mock.patch` on module attributes instead of passing values directly. This violates the project's dependency injection invariant and makes the CLI harder to test and reason about.

## Visual Artifacts
None.

## Key Decisions
1. **Frozen dataclass, not Pydantic** — `CLIContext` is a pure transport object with no validation needs. `@dataclass(frozen=True)` enforces immutability without Pydantic overhead.
2. **cyclopts `parse_args` + `bound.arguments` injection** — The launcher calls `app.parse_args(tokens)` instead of `app(tokens)`, then injects `ctx` into `bound.arguments["ctx"]` before calling `command(*bound.args, **bound.kwargs)`. This was proven by proof-of-concept to work with sub-apps, nested sub-commands, and positional args.
3. **`Parameter(parse=False)` on command ctx parameter** — Each command declares `ctx: Annotated[CLIContext, Parameter(parse=False)] = CLIContext()`. Cyclopts skips it during parsing (it appears in the `ignored` dict). The default `CLIContext()` provides safe defaults when the launcher doesn't inject.
4. **`bound.arguments`, not `bound.kwargs`** — `BoundArguments.kwargs` is a read-only computed property. Injection must go through `bound.arguments` directly.
5. **`make_client(ctx)` with no fallback** — The client factory requires an explicit `CLIContext` parameter. No fallback to module state — missed callers surface as immediate `TypeError`.

## Constraints & Anti-Patterns
- Do NOT use `bound.kwargs["ctx"] = ctx` — it's a read-only property and mutations are silently ignored.
- Do NOT add a `ctx` parameter to `cmd_run` — it does not use globals and should not gain the dependency.
- Do NOT use `Optional[X]` — use `X | None`.
- Do NOT add `from __future__ import annotations`.
- Do NOT use `_` prefix on methods or functions.
- Tests must use `timeout 300 pytest` per project conventions.
- `make_client` patches in tests (`patch("hassette.cli.commands.*.make_client", return_value=client)`) must remain — they inject mock transports. Only `patch("hassette.cli.globals.json_mode", True)` lines are replaced with `ctx=CLIContext(json_mode=True)`.

## Design Doc References
- `## Architecture` — CLIContext dataclass, launcher injection, command signature, client factory
- `## Replacement Targets` — table mapping each global to its replacement
- `## Test Strategy` — 6 test files with line numbers, 4 new tests, no tests to remove
- `## Key Constraints` — cyclopts parse_args, bound.arguments, Parameter(parse=False)

## Convention Examples

### Command function pattern (current — to be replaced)

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
