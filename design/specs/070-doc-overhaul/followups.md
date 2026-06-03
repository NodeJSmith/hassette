# Doc Overhaul Follow-ups

Items tracked during the documentation overhaul (PR #970).

## Completed

- **Orphaned pages deleted** — old tab-mirroring pages, advanced/ directory, config orphans, internals.md, domain-states.md. Links redirected to new locations.
- **Broken cross-links fixed** — all inbound links to deleted pages redirected.
- **CLI start/stop/reload** — documented as REST-only (no CLI commands). manage-apps.md is correct.
- **Screenshots wired** — all 14 web UI screenshots referenced by doc pages. 2 unused screenshots deleted.
- **Cross-references added** — 130 mkdocstrings cross-refs across 40 pages via `tools/check_xref_coverage.py`.
- **Bare symbols fixed** — 120 public symbols backtick-formatted across 45 pages via `tools/check_bare_symbols.py`.
- **Backtick leak fixed** — 68 backticks stripped from mkdocstrings reference paths and inline code spans.

## CI Guard Candidates (not yet wired)

- `tools/check_xref_coverage.py` — ensures first-mention cross-references stay linked
- `tools/check_bare_symbols.py` — catches public symbols without backtick formatting

## Filed as Issues

- **#971** — Expose `STATE_REGISTRY` and `TYPE_REGISTRY` on App instances

## Process Artifacts Saved

- `.claude/skills/doc-overhaul/SKILL.md` — skill capturing the full 3-phase process
- `design/specs/070-doc-overhaul/writing-prompt-template.md` — writer/reviewer subagent prompts
- `design/specs/070-doc-overhaul/docs-context.md` — voice calibration artifact
- `design/specs/070-doc-overhaul/outlines/` — all 76 per-page content outlines
