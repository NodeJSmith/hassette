---
task_id: "T05"
title: "Reword spec tokens in tests/unit/core"
status: "planned"
depends_on: ["T02", "T03"]
implements: ["FR#8", "AC#7"]
---

## Summary
Reword the ~132 leaked spec tokens across the ~22 files in `tests/unit/core/` so docstrings and comments describe the behavior under test rather than the planning ID (`AC#`/`FR#`/`T##`/`WP#`).

## Target Files
Run `check_spec_tokens.check_file` over `tests/unit/core/` for the live file list (~22 files, ~132 tokens).
- modify: `tests/unit/core/**/*.py` — spec-token rewording.

## Prompt
For every hit reported by `check_spec_tokens.check_file` over `tests/unit/core/`, reword the surrounding comment or docstring to describe what the test verifies and drop the planning code, per the design doc (`design/specs/077-extend-linter-scope/design.md`, FR#8 and `## Key Constraints`).

- Keep the sentence accurate and readable — "Verifies FR#2: service waits for DB readiness" → "Verifies the service waits for DB readiness".
- Do not invent behavior to fill a sentence; if a token is the only content, describe what the test actually asserts.
- Do not weaken or suppress — there is no escape hatch; reword every hit.

Verify zero spec-token hits remain in `tests/unit/core/` via the imported `check_spec_tokens.check_file` (see `context.md` → "Checker verification helper"), then run `uv run pytest tests/unit/core/ -q`.

Production `SCAN_DIRS` stays `["src"]` here — verification is via the imported `check_file`. Widening happens in T09.

## Focus
- `tests/unit/core/` spreads ~132 tokens across ~22 files — the widest file count of any spec area, so most files have only a handful each.
- Depends on T02 so dividers in these files are already gone before token rewording.
- This area's files are disjoint from T04/T06/T07/T08 — no shared write targets.
- Do not touch anything under `tests/unit/tools/` (string-literal fixtures, different area).

## Verify
- [ ] FR#8: every reworded docstring/comment in `tests/unit/core/` describes verified behavior, not a planning ID (spot-check 3).
- [ ] AC#7: importing `check_spec_tokens.check_file` and running it over `["tests/unit/core"]` reports zero hits; `uv run pytest tests/unit/core/ -q` passes.
