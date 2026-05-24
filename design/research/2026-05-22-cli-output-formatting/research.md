---
topic: "CLI output formatting patterns"
date: 2026-05-22
status: Draft
---

# Prior Art: CLI Output Formatting Patterns

## The Problem

CLI tools that need both human-readable and machine-readable output face a maintenance trap: two rendering paths that diverge over time. Human output gets a new column but JSON doesn't, or JSON adds a field that the table doesn't show, or error handling works differently in each mode. The architecture chosen for output formatting determines how painful every future command is to write and maintain.

## How We Do It Today

Hassette has no CLI output formatting. The web API returns Pydantic models via FastAPI (automatic JSON serialization). The existing personal CLI tools (ha-api, monarch-api, etc.) use human-readable by default with `--json`.

## Patterns Found

### Pattern 1: Return Data, Not Strings (cliff Pattern)

**Used by**: OpenStack cliff, many internal frameworks

**How it works**: Commands return structured data (tuples, typed objects, Pydantic models) — never formatted strings. The framework handles all rendering. cliff enforces this via base classes: `Lister.take_action()` returns `(column_names, data_iterable)`, and the framework applies the selected formatter.

This eliminates the "two rendering paths" problem entirely. There is one data production path and N formatting paths, but the command author only touches the data path. Adding a new format requires writing one new formatter — zero command modifications.

For Pydantic CLIs: commands return models; a rendering layer calls `model.model_dump()` for JSON and reads `model.model_fields` for table headers.

**Strengths**: Commands are pure data producers — easy to test, no rendering logic. Adding formats is O(1) per format, not O(N) per command. Data shape is a testable contract. Pydantic integration is natural.

**Weaknesses**: Requires discipline — every command must return data, never print directly. Heterogeneous output (tables mixed with prose) is harder to model. Framework coupling.

**Example**: [cliff docs](https://docs.openstack.org/cliff/latest/user/list_commands.html)

### Pattern 2: Automatic Terminal/Pipe Detection

**Used by**: GitHub CLI tableprinter, Rich, git

**How it works**: Same API produces column-aligned tables for terminals and TSV/plain text for pipes. Zero-config for users. Rich auto-detects TTYs and strips ANSI when piped. Respects `NO_COLOR` env var.

GitHub CLI's `tableprinter`: `New(io, isTerminal, terminalWidth)` configures the mode. Same `AddField()/EndRow()/Render()` API produces colorized tables in terminal and TSV when piped. Truncation disabled in non-terminal mode (consumer decides what's too long).

**Strengths**: Piping just works. Single code path for data production. User gets rich formatting in terminal, clean output in pipes.

**Weaknesses**: TSV/plain is less structured than JSON — only for tabular data. Auto-detection can be wrong (CI as TTY, Git Bash). Need escape hatches (`NO_COLOR`, `FORCE_COLOR`).

**Example**: [Rich Console docs](https://rich.readthedocs.io/en/stable/console.html), [go-gh tableprinter](https://pkg.go.dev/github.com/cli/go-gh/v2/pkg/tableprinter)

### Pattern 3: JSON Superset with Curated Human Output

**Used by**: GitHub CLI, Salesforce CLI, Heroku CLI

**How it works**: `--json` produces a superset of the information shown in human mode. Human output is a curated summary with selected columns; JSON output is the complete data model. GitHub CLI requires specifying fields: `--json name,url,status`. Salesforce CLI's JSON includes error details suppressed in human mode.

**Strengths**: Human output stays clean. JSON consumers get all data. JSON is naturally self-documenting.

**Weaknesses**: Two different data shapes for the same command creates a documentation burden. Users may be surprised JSON shows more data.

**Example**: [GitHub CLI formatting](https://cli.github.com/manual/gh_help_formatting)

### Pattern 4: Adaptive Table Rendering

**Used by**: Rich, GitHub CLI tableprinter, pandas

**How it works**: Tables adapt to terminal width using per-column overflow strategies. Rich supports "ellipsis" (default), "crop", and "fold" per column, with min/max width constraints and ratio-based distribution. In non-terminal mode, truncation is disabled entirely.

**Strengths**: Output always fits without horizontal scrolling. Graceful degradation in narrow terminals.

**Weaknesses**: Truncated data can hide critical info. Column priority is a developer decision. Testing depends on terminal width.

**Example**: [Rich Tables docs](https://rich.readthedocs.io/en/stable/tables.html)

### Pattern 5: stdout/stderr Contract for JSON Mode

**Used by**: Salesforce CLI (evolved), Heroku CLI, .NET SDK (after fix)

**How it works**: When JSON mode is active, stdout contains ONLY the JSON document. All diagnostics go to stderr. Errors are included in the JSON envelope on stdout with a status field — not on stderr.

Salesforce CLI initially sent JSON errors to stderr. Third-party code and libraries also wrote to stderr, corrupting the JSON stream. The fix: JSON errors go in the stdout envelope; stderr is best-effort diagnostic only.

The contract: stdout = one valid JSON document (includes error details). stderr = human-readable diagnostics (may be empty, may contain garbage). Exit code = machine-readable success/failure.

**Strengths**: JSON consumers parse stdout reliably. Errors are part of data structure. Works even when subprocesses write unexpected stderr.

**Weaknesses**: Breaking change to fix if gotten wrong initially. Requires wrapping all stderr output carefully.

**Example**: [Salesforce CLI blog](https://developer.salesforce.com/blogs/2020/02/using-salesforce-cli-output-and-scripting)

## Anti-Patterns

- **Leaking non-JSON to stdout in JSON mode**: .NET SDK's `dotnet workload list --machine-readable` emitted manifest update warnings to stdout, breaking JSON parsers. Required a breaking change in .NET 9 to fix. ([source](https://github.com/dotnet/sdk/issues/22887))

- **JSON errors on stderr**: Salesforce CLI learned this the hard way — third-party stderr pollution broke JSON parsing. All JSON (success and error) must go to stdout. ([source](https://developer.salesforce.com/blogs/2020/02/using-salesforce-cli-output-and-scripting))

- **Breaking stdout format in minor releases**: Heroku warns: stdout is an API contract. Changing column order, removing fields, or altering formatting in non-major releases breaks scripts. ([source](https://devcenter.heroku.com/articles/cli-style-guide))

- **Format-dependent query behavior**: AWS CLI's `--query` behaves differently with `--output text` vs JSON — runs per page with text (producing duplicates), once with JSON. Query behavior should be format-independent. ([source](https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-output-format.html))

## Relevance to Us

The "return data, not strings" pattern maps perfectly to hassette's setup. The CLI queries REST endpoints that return Pydantic models — the models ARE the data. The rendering layer is a thin function that checks `--json`:

- **JSON mode**: `model.model_dump_json(indent=2)` → stdout. Done.
- **Human mode**: Read `model.model_fields` for column definitions, render a Rich table with adaptive column widths.

Each command defines which fields to show in human mode (a list of field names + optional display names). JSON mode always shows everything. This is the "JSON superset" pattern with zero extra work — the Pydantic model is already the superset.

The stdout/stderr contract is critical to get right from day one:
- `--json` mode: exactly one JSON document on stdout, diagnostics on stderr
- Human mode: Rich tables on stdout, progress/errors on stderr
- Rich auto-detects TTY and strips formatting when piped

## Recommendation

**Combine Patterns 1 + 2 + 3 + 5**: Commands return Pydantic models (pattern 1). Rich handles terminal detection and table rendering (pattern 2). Human output shows curated columns; JSON shows everything (pattern 3). Strict stdout/stderr contract from day one (pattern 5).

The architecture:

1. **Commands return models** — each cyclopts command function returns a Pydantic response model (or list of models)
2. **A single render function** checks `--json` flag and model type:
   - JSON: `model.model_dump_json()` to stdout
   - Human list: Rich table with configurable column definitions
   - Human detail: Rich panel/key-value display
3. **Column definitions per command** — a simple mapping from model field names to display headers, with optional width hints
4. **Rich Console** for all output — auto-handles TTY detection, NO_COLOR, pipe degradation

This avoids the two-rendering-paths trap entirely. Commands produce data; one render layer formats it.

## Sources

### Reference implementations
- https://pkg.go.dev/k8s.io/cli-runtime/pkg/printers — Kubernetes ResourcePrinter interface
- https://docs.openstack.org/cliff/latest/user/list_commands.html — cliff pluggable formatters
- https://pkg.go.dev/github.com/cli/go-gh/v2/pkg/tableprinter — GitHub CLI tableprinter
- https://github.com/heroku/heroku-cli-util — Heroku CLI formatting utilities

### Blog posts & writeups
- https://developer.salesforce.com/blogs/2020/02/using-salesforce-cli-output-and-scripting — Salesforce stdout/stderr lessons
- https://blog.swdev.ed.ac.uk/2017/04/28/writing-python-command-line-tools-with-cliff/ — cliff "return data" pattern
- https://medium.com/metasintaxis/structured-cli-output-a-best-practice-for-devops-teams-5d0d6c1d71f5 — Structured output contract
- https://nickjanetakis.com/blog/docker-tip-24-docker-ps-vs-docker-container-ls — Docker dual-syntax cost

### Documentation & standards
- https://devcenter.heroku.com/articles/cli-style-guide — Heroku CLI style guide
- https://cli.github.com/manual/gh_help_formatting — GitHub CLI formatting
- https://rich.readthedocs.io/en/stable/console.html — Rich Console auto-detection
- https://rich.readthedocs.io/en/stable/tables.html — Rich Tables column overflow
- https://clig.dev/ — Community CLI guidelines
- https://no-color.org/ — NO_COLOR standard
- https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-output-format.html — AWS CLI output formats
