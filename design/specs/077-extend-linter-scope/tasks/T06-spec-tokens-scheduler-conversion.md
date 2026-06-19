---
task_id: "T06"
title: "Reword spec tokens in scheduler + coroutine-conversion + sync-executor tests"
status: "planned"
depends_on: ["T02", "T03"]
implements: ["FR#8", "AC#7"]
---

## Summary
Reword the ~140 leaked spec tokens in the scheduler unit tests and the large single-file suites (sync-executor, the coroutine-conversion tests, forgotten-await completeness) so docstrings and comments describe behavior rather than planning IDs.

## Target Files
Run `check_spec_tokens.check_file` over each path below for the live list. Reconnaissance:
- modify: `tests/unit/scheduler/**/*.py` — ~31 tokens across ~2 files.
- modify: `tests/unit/test_sync_executor_service.py` — ~37 tokens.
- modify: `tests/unit/test_api_coroutine_conversion.py` — ~31 tokens.
- modify: `tests/unit/test_entity_coroutine_conversion.py` — ~26 tokens.
- modify: `tests/unit/test_forgotten_await_completeness.py` — ~14 tokens.

## Prompt
For every hit reported by `check_spec_tokens.check_file` over the five paths in Target Files, reword the surrounding comment or docstring to describe what the test verifies and drop the planning code, per the design doc (`design/specs/077-extend-linter-scope/design.md`, FR#8 and `## Key Constraints`).

- Keep the sentence accurate and readable; do not invent behavior to fill a sentence.
- No suppression — reword every hit.

Verify zero spec-token hits remain across these paths via the imported `check_spec_tokens.check_file` (see `context.md`), then run `uv run pytest tests/unit/scheduler/ tests/unit/test_sync_executor_service.py tests/unit/test_api_coroutine_conversion.py tests/unit/test_entity_coroutine_conversion.py tests/unit/test_forgotten_await_completeness.py -q`.

Production `SCAN_DIRS` stays `["src"]` here — verification is via the imported `check_file`. Widening happens in T09.

## Focus
- These are the large single-file suites — `test_sync_executor_service.py` and the two coroutine-conversion files carry the most tokens per file, so expect dense docstring rewording.
- `test_sync_executor_service.py`, `test_scheduler_coroutine_conversion.py`, and `test_forgotten_await_completeness.py` also had lazy imports resolved in T03 — this task only touches comments/docstrings (spec tokens), a different concern. T06 explicitly `depends_on` T03, so the lazy-import pass on these shared files is already committed before this task starts. Avoid re-touching import lines.
- Files here are disjoint from T04/T05/T07/T08.
- Do not touch `tests/unit/tools/` fixtures.

## Verify
- [ ] FR#8: every reworded docstring/comment across the five paths describes verified behavior, not a planning ID (spot-check 3).
- [ ] AC#7: importing `check_spec_tokens.check_file` and running it over the five paths reports zero hits; the corresponding pytest run passes.
