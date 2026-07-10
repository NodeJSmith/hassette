# CLI Tests

## Two-layer testing

CLI tests cover two distinct layers. Both are required.

### 1. Wiring tests (`test_parse_args.py`)

Test through cyclopts dispatch via `app.parse_args(argv)`. This exercises flag parsing, type conversion, subcommand routing, and converter lambdas — the layer between user input and your function. No mocking needed; no command execution.

```python
from hassette.cli import app

cmd, bound, _ = app.parse_args(["log", "--since", "7d"])
assert cmd.__name__ == "cmd_log"
assert isinstance(bound.arguments["since"], float)
```

For global flags (`--json`, `--debug`, `--config-file`), use `app.meta.parse_args(argv)`.

When adding a new command or flag, add a `parse_args` test for it. When adding a custom `converter=` on a `Parameter`, add a test that dispatches through `parse_args` with the real `app` — not a toy `App()`.

### 2. Function tests (`test_commands_*.py`)

Test command logic by calling the function directly with pre-converted values. These use `MockTransport` to mock the HTTP layer and verify endpoint routing, param forwarding, and output rendering.

```python
cmd_log(since=1700000000.0, limit=20)  # pre-converted epoch float
```

These tests do not exercise cyclopts at all. They exist to test that the function does the right thing with its arguments.

### Why both layers exist

A `--since 7d` bug shipped because every test called `cmd_log(since=<float>)` directly. The cyclopts converter lambda — the only code that bridges user input to the function — was never executed by any test. The converter received a tuple of `Token` objects, not a string, and nobody knew until a user hit it.

Direct function calls test function logic. `parse_args` tests prove the wiring is correct. Neither substitutes for the other.

## Fixtures and helpers

`conftest.py` provides:
- `CLIClientFactory` — builds `HassetteCLIClient` instances backed by `MockTransport`
- `MockTransportBuilder` — route table for mock HTTP responses
- `GetSpy` — wraps `client.get` to record paths and params
- `capture_stdout()` / `capture_stderr()` / `capture_json_stdout()` — Rich console capture
- `capture_human(func, *args)` — returns `(stdout, stderr)` strings
- `SINCE_EPOCH` — pre-computed epoch float for direct-call tests

## File layout

| File | What it tests |
|---|---|
| `test_parse_args.py` | Cyclopts dispatch: routing, converters, flag combos, global flags, invalid input |
| `test_commands_*.py` | Command function logic: endpoint routing, param forwarding, output |
| `test_since_converter.py` | `convert_since()` unit tests: relative durations, ISO formats, invalid inputs |
| `test_client.py` | `HassetteCLIClient` HTTP handling, error formatting |
| `test_context.py` | `CLIContext` and launcher meta-command pattern |
| `test_output.py` | Table rendering, formatters, JSON mode |
| `test_output_detail.py` | Detail/panel rendering |
| `test_completion.py` | Shell completion generation |
