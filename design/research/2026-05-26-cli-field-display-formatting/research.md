---
topic: "CLI field display formatting with Pydantic models"
date: 2026-05-26
status: Draft
---

# Prior Art: CLI Field Display Formatting with Pydantic Models

## The Problem

CLI tools that share Pydantic models between a JSON API and human-readable terminal output need a way to format raw field values (epoch timestamps as "3m ago", durations in seconds as "2h 30m", booleans as checkmarks or lowercase). The formatting must not contaminate JSON serialization — `--json` should always return raw values. The question is where the knowledge of "this field is a duration" should live: on the model, in the render layer, or somewhere in between.

## How We Do It Today

Hassette uses a **render-layer-only approach**. Models in `web/models.py` store raw values with no display metadata. Formatter functions (`fmt_duration_ms`, `fmt_relative_time`, `uptime_fmt`) live in `cli/output.py` and `cli/commands/status.py`. They're wired to fields via `Column` definitions in each command file. This works well for table views (`render_table`) but `render_detail` (used by `config`, `status`, `app health`) has no formatter support — it just calls `str()` on raw values. When a model gains a new field, there's no signal that it needs a formatter.

## Patterns Found

### Pattern 1: Separate Render Layer (Formatter Functions per Command)

**Used by**: GitHub CLI (gh), kubectl, HTTPie, sqlite-utils/Datasette
**How it works**: The data model stores raw values only. JSON serialization uses the model directly. Human output is produced by a separate "printer" per command/resource type that selects fields and applies formatting transforms. gh uses `AddField` calls with formatting closures. kubectl has per-resource-type printers that produce computed columns like "AGE" from raw timestamps.

**Strengths**: Clean separation — JSON output is guaranteed uncontaminated. Different commands can show different views of the same model. No coupling between domain and presentation layers.

**Weaknesses**: When a model gains a field, the formatter must be updated separately — no compile-time or introspection-time enforcement. Format knowledge is scattered across command files. Duplication risk when multiple commands format the same field type.

**Example**: [gh table_printer.go](https://github.com/cli/cli/blob/trunk/internal/tableprinter/table_printer.go), [gh json_flags.go](https://github.com/cli/cli/blob/trunk/pkg/cmdutil/json_flags.go)

### Pattern 2: Annotated Metadata Display Hints

**Used by**: No major CLI project at scale (yet). Documented in Pydantic ecosystem, used for XML structure and database column metadata. Pydantic v2 infrastructure supports it natively.
**How it works**: A small frozen dataclass like `DisplayAs(format="duration")` is placed in `Annotated` metadata on model fields. Pydantic preserves it in `model_fields[name].metadata` without interpreting it. The render layer introspects the metadata and dispatches to a formatter registry.

```python
class AppStatus(BaseModel):
    uptime_seconds: Annotated[float, DisplayAs("duration")]
    last_seen: Annotated[float, DisplayAs("relative_time")]
```

**Strengths**: Format hints co-located with field definitions — adding a field and declaring its display format happen together. Render layer is generic (one function for all models). JSON serialization is untouched. Discoverable via introspection.

**Weaknesses**: Unproven at scale for CLI display. Shared vocabulary of format names creates coupling between model and render layers. Typos in format strings aren't caught until runtime. One display format per field — different contexts may want different formatting for the same field.

**Example**: [wimonder.dev: Adding metadata to Pydantic fields](https://wimonder.dev/posts/adding-metadata-to-pydantic-fields/), [Pydantic Annotated types](https://deepwiki.com/pydantic/pydantic/3.5-annotated-metadata-and-custom-types)

### Pattern 3: Custom Semantic Types

**Used by**: Conceptually common in typed Python. Similar to `pydantic.HttpUrl`, `pydantic.EmailStr`.
**How it works**: Instead of `uptime_seconds: float` with a hint, create `Duration(float)` that carries formatting knowledge via `__str__`. The render layer recognizes the type and formats accordingly, or just calls `str()`.

**Strengths**: Type carries formatting. Type checkers understand it. Consistent formatting across all models using the same type.

**Weaknesses**: Subclassing primitives is fragile (arithmetic returns `float`, not `Duration`). Can't have different display for the same type in different contexts. Doesn't help when the type is genuinely `float` but the display varies by meaning (seconds vs. percentage).

**Example**: [no source found]

### Pattern 4: computed_field / field_serializer (Anti-Pattern)

**Used by**: Some FastAPI projects for API response formatting.
**How it works**: Add `@computed_field` for display-only fields or `@field_serializer` to transform values during serialization.

**Strengths**: Self-contained in the model. Works with existing Pydantic tooling.

**Weaknesses**: **Widely considered an anti-pattern.** computed_field pollutes JSON output with display-only fields. field_serializer changes JSON values, breaking machine consumers. Mixes presentation concerns into the data model.

**Example**: [Pydantic serialization docs](https://docs.pydantic.dev/latest/concepts/serialization/)

### Pattern 5: Rich Console Protocol (__rich_console__)

**Used by**: Pydantic natively (via `__rich_repr__`); Textual apps.
**How it works**: Models implement `__rich_console__` to yield Rich renderables (Tables, Panels) with formatted fields. `rich.print(model)` renders the custom output.

**Strengths**: Rich integration is native. No external formatter needed.

**Weaknesses**: Couples presentation to domain. Different commands can't have different views. Models become Rich-aware.

**Example**: [Pydantic Rich integration](https://docs.pydantic.dev/latest/integrations/rich/)

## Anti-Patterns

- **field_serializer for display**: Downstream systems expecting `uptime_seconds: 3600` get `"1 hour"` instead. Breaks machine consumers.
- **computed_field display properties**: `uptime_display: str` pollutes JSON schema and API responses with presentation concerns.
- **__str__ for table output**: Every context calling `str(model)` gets the same output — logging, errors, debugging all show table formatting.
- **One universal auto-formatter**: Over-generalizing leads to edge cases — some commands need field subsets, computed columns, or context-specific formatting. Per-resource printers (kubectl's approach) are simpler to maintain than one magic formatter.

## Emerging Trends

Pydantic v2's aggressive move toward `Annotated` as the primary metadata mechanism creates a natural extension point for display hints. The infrastructure (`model_fields[name].metadata`) is production-ready. No major project has standardized display-format metadata in Annotated yet, but the pattern is viable and consistent with the direction Pydantic is heading.

## Relevance to Us

Hassette already has Pattern 1 (separate render layer) for table views via `Column` definitions. The gap is `render_detail`, which has no formatter support. We have two viable paths:

1. **Extend Pattern 1**: Add `formatters: dict[str, Callable]` to `render_detail()`. Commands pass field-name → formatter mappings. Consistent with existing `Column`-based architecture. Well-proven by gh/kubectl. Downside: format knowledge stays scattered in command files.

2. **Adopt Pattern 2**: Add `Annotated` metadata hints on model fields. `render_detail` introspects metadata automatically. Format knowledge lives next to field definitions. Novel for CLI display but uses proven Pydantic infrastructure. Downside: unproven at scale, one format per field.

A **hybrid** is also viable: `Annotated` metadata as the default, with render-layer overrides for commands that need different formatting.

## Recommendation

**Pattern 2 (Annotated metadata) is the best fit** for hassette's specific situation — a small-to-medium codebase where models are defined once and rendered in one CLI context. The "one format per field" weakness doesn't apply here because each field genuinely has one natural display format (a duration is always a duration, a timestamp is always relative). The co-location benefit — adding a field automatically declares its display format — prevents the drift that Pattern 1 is prone to.

Use Pattern 1 (`Column` definitions) for table views where field selection and ordering matter. Use Pattern 2 (`Annotated` hints) for detail views where every field is shown and the question is only "how to format the value."

Avoid Patterns 4 (field_serializer) and 5 (__rich_console__) — both contaminate the wrong layer.

## Sources

### Reference implementations
- [gh table_printer.go](https://github.com/cli/cli/blob/trunk/internal/tableprinter/table_printer.go) — gh's table rendering with per-field formatting
- [gh json_flags.go](https://github.com/cli/cli/blob/trunk/pkg/cmdutil/json_flags.go) — gh's JSON output separation
- [sqlite-utils CLI](https://sqlite-utils.datasette.io/en/stable/cli.html) — multi-format output with pluggable renderers
- [jc project](https://kellyjonbrazil.github.io/jc/) — inverse pattern (text → JSON), per-type parsers
- [humanize library](https://python-humanize.readthedocs.io/en/latest/time/) — standalone formatting functions

### Blog posts & writeups
- [wimonder.dev: Adding metadata to Pydantic fields](https://wimonder.dev/posts/adding-metadata-to-pydantic-fields/) — Annotated metadata patterns
- [heaths.dev: gh table formatting](https://heaths.dev/tips/2021/08/24/gh-table-formatting.html) — gh 2.0 formatting architecture

### Documentation & standards
- [Pydantic Rich integration](https://docs.pydantic.dev/latest/integrations/rich/) — native __rich_repr__ support
- [Pydantic serialization](https://docs.pydantic.dev/latest/concepts/serialization/) — field_serializer and computed_field
- [Pydantic Annotated types](https://deepwiki.com/pydantic/pydantic/3.5-annotated-metadata-and-custom-types) — metadata infrastructure
- [kubectl output formats](https://www.baeldung.com/ops/kubectl-output-format) — kubectl's per-resource printer architecture

### Community discussions
- [Pydantic #7787: pretty printing](https://github.com/pydantic/pydantic/discussions/7787) — unsolved problem, no consensus
- [Pydantic #2606: __rich_repr__](https://github.com/pydantic/pydantic/discussions/2606) — Rich protocol integration
