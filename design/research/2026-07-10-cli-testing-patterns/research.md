---
topic: "CLI testing patterns — subprocess vs dispatch vs direct calls"
date: 2026-07-10
status: Draft
---

# Prior Art: CLI Testing Patterns

## The Problem

CLI frameworks add a wiring layer between user input and business logic: flag parsing, type conversion, subcommand routing, global option injection. When tests call the underlying function directly with pre-converted values, that wiring layer is untested. This is exactly how a `--since 7d` bug shipped — the converter worked in isolation, but the cyclopts adapter that bridges Token objects to the converter was never exercised.

The question: what's the right testing level for CLI wiring, and how do mature projects handle it?

## How We Do It Today

All hassette CLI tests call command functions directly (e.g., `cmd_log(since=1700000000.0)`). The HTTP layer is mocked via `MockTransport`, but cyclopts never parses a single flag string. Two recent tests (`test_context.py`, `test_since_converter.py`) dispatch through toy cyclopts `App()` instances, but nobody tests the real `app` from `__init__.py`. System smoke tests also bypass dispatch — they call `client.get()` directly.

## Patterns Found

### Pattern 1: Parse-Without-Execute (cyclopts `parse_args`)

**Used by**: Cyclopts projects, argparse projects (via `parse_args(args)`)
**How it works**: `app.parse_args(["--flag", "value"])` performs all argument parsing, type conversion, env var resolution, and config loading, then returns `(command_function, BoundArguments, _)` without calling the command. Tests assert the right command was selected and arguments were parsed/converted correctly. No side effects, no mocking needed.

For argparse, the equivalent is `parser.parse_args(["--flag"])` returning a `Namespace`. Click/Typer have no equivalent — `invoke()` always executes.

**Strengths**: Fastest wiring test. No mocking. Catches broken converters, wrong flag names, missing defaults, env var misconfiguration. Tests the actual parsing code path.
**Weaknesses**: Doesn't test command behavior, exit codes, or output formatting. Doesn't test error messages for invalid input (those need `app()` with `pytest.raises`).
**Example**: https://cyclopts.readthedocs.io/en/latest/cookbook/unit_testing.html

### Pattern 2: In-Process Dispatch (Click CliRunner / `app()` invocation)

**Used by**: Click, Typer, cyclopts (via `app("arg")` or `app("arg", result_action="return_value")`)
**How it works**: Full CLI dispatch pipeline runs in-process. Click/Typer use `CliRunner.invoke(app, ["--flag"])` with captured stdout/stderr. Cyclopts uses `app("arg")` (calls `sys.exit`) or `app("arg", result_action="return_value")` (returns directly). Tests the complete pipeline: parsing → dispatch → execution → output → exit code.

**Strengths**: Tests full user-facing behavior. Fast. Mocking is easy. Can test error messages, help text, output formatting.
**Weaknesses**: Click's CliRunner is not thread-safe and changes interpreter state. Cyclopts' `app()` calls `sys.exit()` requiring `pytest.raises(SystemExit)`. `result_action="return_value"` avoids this.
**Example**: https://click.palletsprojects.com/en/stable/testing/

### Pattern 3: Subprocess / Black-Box Testing

**Used by**: Rust projects (assert_cmd), Node.js (CLI Testing Library), projects needing true e2e confidence
**How it works**: Spawns the CLI as a child process, captures stdout/stderr, checks exit codes. CLI treated as a black box. Output normalization is critical (strip ANSI, replace paths).

**Strengths**: Tests exactly what users experience. Catches import errors, entry point misconfiguration, missing dependencies.
**Weaknesses**: Slow (process spawn per test). Output normalization is tedious. Mocking is harder. Cannot inspect internal state.
**Example**: https://alexwlchan.net/2025/testing-rust-cli-apps-with-assert-cmd/

### Pattern 4: Separated Architecture (Business Logic + CLI Shell)

**Used by**: Nearly every source recommends this. The single most cited pattern.
**How it works**: Two layers: (1) business logic functions with no CLI awareness, (2) thin CLI shell that parses and dispatches. Test both independently. Business logic gets normal unit tests. CLI shell gets parse_args or mocked dispatch tests.

**Strengths**: Business logic tests are fast and framework-independent. CLI tests focus on wiring. Changing frameworks doesn't break logic tests.
**Weaknesses**: Requires disciplined architecture. The "thin shell" can grow complex (formatting, error handling) and needs its own tests. Over-separation can miss integration bugs.
**Example**: https://rust-cli.github.io/book/tutorial/testing.html

### Pattern 5: Snapshot / Golden File Testing

**Used by**: Rust CLI ecosystem (trycmd, snapbox), shelltestrunner (Haskell)
**How it works**: Run CLI, compare output against saved baseline. Update snapshots when output intentionally changes.

**Strengths**: Low maintenance. Catches formatting regressions. Makes output changes visible in review.
**Weaknesses**: Brittle to incidental changes (timestamps, paths). Can obscure what the test checks. Snapshot bloat.
**Example**: https://docs.rs/trycmd

## Anti-Patterns

1. **Testing auto-generated output like `--help` formatting** — help text is framework-generated and changes with upgrades. Test that help displays (exit code), don't assert layout. (Source: Rust CLI book)
2. **Calling `parse_args()` with no arguments** — reads from `sys.argv`, producing confusing failures. Always pass an explicit list. (Source: cyclopts docs)
3. **Only testing the business logic function directly** — converters, validators, flag names, and defaults are all untested. The `--since 7d` bug is this anti-pattern. (Synthesized from sources)
4. **Mocking at the wrong level** — mock your business logic, not the framework's internals. (Source: Smashing Magazine)

## Relevance to Us

Hassette's CLI tests are almost entirely Anti-Pattern #3 — every test calls the command function directly with pre-converted values. The `SinceArg` converter bug proved this gap is real.

Cyclopts' `parse_args()` (Pattern 1) is purpose-built for the exact gap we have. It's already available — we just aren't using it. It fills the space between "test the function" (no wiring coverage) and "test the full dispatch" (requires mocking the HTTP layer and handling `sys.exit`).

Our architecture already follows Pattern 4 (separated architecture) — command functions are thin shells that call `make_client` and forward parsed args. The existing direct-call tests cover the business logic side well. What's missing is the wiring side.

Subprocess testing (Pattern 3) would add little value here — the entry point works, and the HTTP client needs mocking regardless. The overhead isn't worth it for a framework that provides `parse_args()`.

## Recommendation

**Use `parse_args()` for wiring tests.** For each command, add tests that call `app.parse_args(["subcommand", "--flag", "value"])` on the real `app` object and verify:
- The right command function was selected
- Arguments arrive with the right types (converter wiring)
- Global options (`--json`, `--debug`) propagate correctly

Keep the existing direct-call tests — they cover the function logic (param forwarding, HTTP routing, output rendering). The `parse_args` tests are complementary, not replacement.

For error cases (invalid `--since`, `--source-tier bogus`), `parse_args` raises `SystemExit` directly (cyclopts defaults `exit_on_error=True`), so the same `app.parse_args()` pattern works for both success and error-case wiring tests.

**Don't add subprocess tests.** The ROI is low when `parse_args()` covers the wiring layer and the HTTP layer needs mocking anyway.

## Sources

### Documentation & standards
- https://cyclopts.readthedocs.io/en/latest/cookbook/unit_testing.html — cyclopts official testing guide (parse_args, app invocation, result_action)
- https://click.palletsprojects.com/en/stable/testing/ — Click CliRunner documentation
- https://typer.tiangolo.com/tutorial/testing/ — Typer testing (re-exports Click's CliRunner)
- https://rust-cli.github.io/book/tutorial/testing.html — Rust CLI book testing chapter

### Blog posts & writeups
- https://www.smashingmagazine.com/2022/04/testing-cli-way-people-use-it/ — testing CLIs the way people use them
- https://alexwlchan.net/2025/testing-rust-cli-apps-with-assert-cmd/ — black-box CLI testing in Rust
- https://pytest-with-eric.com/pytest-advanced/pytest-argparse-typer/ — pytest + argparse/typer patterns
- https://til.simonwillison.net/pytest/pytest-argparse — Simon Willison's argparse testing TIL
- https://pythontest.com/testing-argparse-apps/ — three-tier argparse testing architecture
