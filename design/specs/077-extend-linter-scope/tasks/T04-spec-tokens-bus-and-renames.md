---
task_id: "T04"
title: "Reword spec tokens in bus tests; rename the two task-ID test files"
status: "done"
depends_on: ["T01", "T02", "T03"]
implements: ["FR#5", "FR#8", "AC#4", "AC#7"]
---

## Summary
Reword the ~208 leaked spec tokens in `tests/unit/bus/` and `tests/integration/bus/` so docstrings and comments describe the behavior under test rather than the planning ID. In the same task, rename the two test files whose names carry lowercase task-ID segments and update the one comment that references them — these renames are needed before scope widens (T09) so the now-case-insensitive filename check passes.

## Target Files
Run `check_spec_tokens.check_file` over the bus dirs for the live file list. Reconnaissance:
- modify: `tests/unit/bus/**/*.py` — ~188 spec tokens across ~11 files.
- modify: `tests/integration/bus/**/*.py` — ~20 spec tokens across ~2 files.
- rename: `tests/unit/bus/test_t03_registration_errors.py` → `tests/unit/bus/test_registration_errors.py` (no collision; confirmed absent).
- rename: `tests/unit/bus/test_t04_once_listener_tracking.py` → `tests/unit/bus/test_once_listener_tracking.py` (no collision; confirmed absent).
- modify: `tests/unit/bus/conftest.py` — line ~50 comment references `test_t04_once_listener_tracking.py`; update to the new name.

## Prompt
Two pieces of work, both for `tests/unit/bus/` and `tests/integration/bus/`. See the design doc (`design/specs/077-extend-linter-scope/design.md`, FR#5 and FR#8, `## Edge Cases`, `## Key Constraints`).

**A. Rename the two task-ID test files (FR#5):**
1. `git mv tests/unit/bus/test_t03_registration_errors.py tests/unit/bus/test_registration_errors.py`
2. `git mv tests/unit/bus/test_t04_once_listener_tracking.py tests/unit/bus/test_once_listener_tracking.py`
3. Update `tests/unit/bus/conftest.py` (~line 50): the comment `... (see test_t04_once_listener_tracking.py).` → reference the new filename.
4. Grep the repo for any other live reference to the old module names (`test_t03_registration_errors`, `test_t04_once_listener_tracking`). The design docs under `design/specs/072-*` and `design/research/*` are historical records — leave those. Update only live code/config/docstring references.
5. Confirm `uv run pytest tests/unit/bus/test_registration_errors.py tests/unit/bus/test_once_listener_tracking.py -q` collects and passes under the new names.

**B. Reword the spec tokens (FR#8):**
For every hit reported by `check_spec_tokens.check_file` over `tests/unit/bus/` and `tests/integration/bus/` (including inside the two just-renamed files), reword the surrounding comment/docstring to describe what the test verifies — drop the `AC#`/`FR#`/`T##`/`WP#` planning code. The sentence must still read correctly and accurately describe the behavior. Examples: "Covers AC#3: handler fires on state change" → "Handler fires on state change"; "Regression test for T04 once-listener tracking" → "Regression test for once-listener tracking". Do not invent behavior to fill a sentence — if a token is the only content, describe what the test actually asserts.

Verify zero spec-token hits remain in both bus dirs via the imported `check_spec_tokens.check_file` (see `context.md` → "Checker verification helper"), and run `uv run pytest tests/unit/bus/ tests/integration/bus/ -q`.

Production `SCAN_DIRS` stays `["src"]` here — verification is via the imported `check_file`. Widening happens in T09.

## Focus
- `tests/unit/bus/` is the single densest spec-token area (~188 across 11 files) — most are `AC#`/`FR#` mapping codes in test docstrings from the planning era.
- The two renamed files are themselves in this area and carry content tokens — reword them too (part B) after renaming (part A).
- `check_filename` won't matter until T09 widens scope, but renaming now means T09's widened+case-insensitive filename scan finds nothing to flag.
- conftest references: only `tests/unit/bus/conftest.py:50` is a live reference (a comment, not an import — pytest collection is unaffected, but FR#5 requires updating it).
- Do not touch string-literal fixtures in `tests/unit/tools/` (different area, not in scope here anyway).
- Depends on T02 (dividers removed from these files first) and T01 (case-insensitive filename behavior already in place).

## Verify
- [ ] FR#5: neither `test_t03_registration_errors.py` nor `test_t04_once_listener_tracking.py` exists; `test_registration_errors.py` and `test_once_listener_tracking.py` exist; the `conftest.py` comment references the new name; no other live reference to the old names remains.
- [ ] AC#4: `uv run pytest tests/unit/bus/test_registration_errors.py tests/unit/bus/test_once_listener_tracking.py -q` collects and passes.
- [ ] FR#8: every reworded docstring/comment in the bus dirs describes the verified behavior, not a planning ID (spot-check 3).
- [ ] AC#7: importing `check_spec_tokens.check_file` and running it over `["tests/unit/bus","tests/integration/bus"]` reports zero hits.
