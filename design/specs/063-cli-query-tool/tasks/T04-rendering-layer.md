---
task_id: "T04"
title: "Create shared rendering layer"
status: "planned"
depends_on: ["T02"]
implements: ["FR#3", "FR#4", "FR#5", "FR#9", "AC#2", "AC#3", "AC#7"]
---

## Summary

Create the rendering layer that all CLI commands use for output formatting. Commands return Pydantic response models; this layer handles Rich tables for collections, key-value panels for single objects, and JSON serialization for structured output. Enforces the stdout cleanliness contract and provides pipe-aware formatting.

## Prompt

### Create `src/hassette/cli/output.py`

**Column definition:**

Define a `Column` dataclass (or NamedTuple) that maps a model field to a table column:

```python
@dataclass(frozen=True)
class Column:
    field: str        # model field name (dot notation for nested, e.g., "status")
    header: str       # display header text
    max_width: int | None = None
    overflow: str = "ellipsis"  # Rich overflow mode
```

Each command module will declare a list of `Column` objects for its table output.

**Rendering functions:**

1. **`render_table(items, columns, json_mode)`**: For list/collection responses.
   - JSON mode: serialize the list via `[item.model_dump(mode="json") for item in items]`, then `json.dumps(indent=2)` to stdout.
   - Human mode: build a Rich `Table` with columns from the `Column` list. Extract field values from each model. Print via Rich console to stdout.
   - Empty list: human mode prints "No results." to stderr; JSON mode prints `[]` to stdout.

2. **`render_detail(item, json_mode)`**: For single-object responses.
   - JSON mode: `item.model_dump_json(indent=2)` to stdout.
   - Human mode: Rich key-value panel (or formatted output) showing all model fields with labels.

3. **`render_raw(data, json_mode)`**: For untyped dict responses (services endpoint).
   - JSON mode: `json.dumps(data, indent=2)` to stdout.
   - Human mode: Rich-formatted JSON or tree view.

**Pipe detection and environment:**
- Rich auto-detects TTY vs pipe and strips ANSI when piped — leverage this default behavior
- In non-TTY mode, disable column truncation (max_width is ignored) so piped output contains full values
- Respect `NO_COLOR` environment variable (Rich handles this automatically)

**stderr contract:**
- Create two Rich Console instances: one for stdout (data output), one for stderr (diagnostics)
- All error messages, warnings, and "no results" messages go to the stderr console
- stdout console is used only by render functions

**stdout cleanliness guarantee (FR#5):**
- In JSON mode, stdout must contain exactly one valid JSON document — no Rich formatting, no progress indicators, no warnings
- Validate this by ensuring all non-data output uses the stderr console

### Unit tests

- Table rendering: mock Pydantic model list → verify Rich table has correct columns and values
- Detail rendering: mock single model → verify key-value output
- JSON mode: verify valid JSON on stdout, nothing else on stdout
- Empty list: human mode → "No results." on stderr, empty stdout; JSON mode → `[]` on stdout
- Pipe detection: verify truncation disabled in non-TTY mode (mock `console.is_terminal`)
- Adding a new output format only requires changes to output.py (AC#7 — architectural constraint, verified by the module structure)

## Focus

- Rich Console API: `Console(file=sys.stdout)` and `Console(file=sys.stderr, stderr=True)`. The stderr console should be used for all diagnostics.
- Pydantic serialization: `model.model_dump(mode="json")` returns a dict with JSON-safe values (datetimes as strings, enums as values). `model.model_dump_json(indent=2)` returns a JSON string directly.
- Rich Table: `from rich.table import Table`. Add columns with `table.add_column(header, max_width=...)`. Add rows with `table.add_row(...)`.
- NO_COLOR: Rich checks `NO_COLOR` env var automatically when `Console(no_color=...)` is not explicitly set.
- The rendering layer must be format-agnostic — it should not know about specific command semantics. Commands pass Column lists and models; output.py renders them.

## Verify

- [ ] FR#3: Human-readable table output for collections; key-value panel for single objects
- [ ] FR#4: `--json` flag produces structured JSON containing the complete response model
- [ ] FR#5: In JSON mode, stdout contains exactly one valid JSON document with no other content
- [ ] FR#9: Commands pass models to the rendering layer; all formatting happens in output.py
- [ ] AC#2: Table output fits within 80 columns for the default column set (verified with representative data)
- [ ] AC#3: JSON mode stdout is valid parseable JSON with no ANSI codes or other content
- [ ] AC#7: Adding a hypothetical new format (e.g., CSV) would only require changes to output.py
