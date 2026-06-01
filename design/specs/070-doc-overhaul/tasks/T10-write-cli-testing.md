---
task_id: "T10"
title: "Write CLI and Testing sections"
status: "planned"
depends_on: ["T04"]
implements: ["FR#1", "FR#14", "AC#1", "AC#16"]
---

## Summary

Writes the CLI section (4 pages) and Testing section (4 pages) from blank. Both sections are reference-heavy — CLI is command/flag/example tables, Testing covers the harness, factories, time control, and concurrency helpers. These sections lean toward the reference exemplar voice: terse, tabular, functional definitions. Code examples come from the existing 34 testing snippets (rewritten as needed).

## Prompt

Work on the `docs/overhaul` branch. Before writing, read:
- `design/specs/070-doc-overhaul/docs-context.md` (calibration artifact)
- `design/specs/070-doc-overhaul/outlines/cli/` and `design/specs/070-doc-overhaul/outlines/testing/` (Phase 2 outlines)
- The reference exemplar page from T03 (voice reference for terse/tabular content)
- `.claude/rules/voice-guide.md` and `.claude/rules/doc-rules.md`

### CLI pages (4):

- `cli/index.md` — CLI overview, how to invoke `hassette`
- `cli/commands.md` — Command reference: `run`, `status`, `app`, `listener`, `log`, `job`
- `cli/configuration.md` — CLI-specific configuration, environment variables
- `cli/workflows.md` — Common CLI workflows (checking app health, tailing logs, debugging)

CLI pages are scanning-oriented: command/flag/example tables, not prose. Follow the "Pages that don't fit a template" exception in doc-rules.md for CLI reference.

### Testing pages (4):

- `testing/index.md` — Testing overview, two mock strategies (HassetteHarness vs create_hassette_stub)
- `testing/factories.md` — Test factory functions for creating events, states, configs
- `testing/time-control.md` — Time manipulation in tests, freezing time, advancing schedulers
- `testing/concurrency.md` — Testing async handlers, concurrent operations, race conditions

Testing pages follow the concept template but lean reference. The decision table for HassetteHarness vs stub is a key piece — readers need to quickly determine which strategy fits their test.

### Voice:

These sections are closest to the reference exemplar. Tables before prose in command references. Functional definitions in table cells. But concept-level content (like "when to use HassetteHarness vs stub") still uses the concept page voice (system-as-subject, declarative).

### Snippet handling:

Testing has 34 existing snippets. The Phase 2 outline (T04) maps which to keep, rewrite, or delete. CLI has no snippets currently — add them for command examples if the outlines call for it.

## Focus

**Testing snippets are substantial** — 34 files covering harness setup, factory usage, time control, and concurrency patterns. These are the examples users copy. Ensure they reflect current API signatures.

**CLI has no snippets** — this is unusual. The Phase 2 outline may call for snippet files showing CLI invocations with expected output. If so, these would be non-Python files (shell commands) — check if `pymdownx.snippets` supports them or if inline code blocks are acceptable for CLI output examples. Note: FR#14 requires snippet files for Hassette *code* examples — CLI output may be an exception.

**The harness vs stub decision** is one of the most-referenced pieces in the testing docs. The current `tests/TESTING.md` has the decision table — preserve and improve it.

## Verify

- [ ] FR#1: All pages pass the voice audit checklist
- [ ] FR#14: Every Hassette code example comes from a snippet file — no inline code blocks for code examples (CLI output examples may be inline if they're not Hassette code)
- [ ] AC#1: Voice audit checklist applied and all items pass
- [ ] AC#16: No inline Hassette code examples that should be in snippet files
