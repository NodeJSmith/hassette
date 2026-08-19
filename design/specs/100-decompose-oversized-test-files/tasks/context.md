# Context: Decompose Six Oversized Test Files

## Problem & Motivation

Six test files exceed the repo's 800-line threshold enforced by the `file-sizes` CI job (a known,
pre-existing, non-blocking baseline finding per CLAUDE.md — see "Known-failing lint checks").
Each file was filed as its own `size:small` GitHub issue (#1578-#1583). All six splits are
mechanical: no production code changes, no behavior changes, just moving existing test
classes/functions into new sibling files (or a new subpackage for one file that has no sibling
convention yet).

## Key Decisions

1. Every split follows the target directory's own existing convention. Five of six directories
   already have a sibling-file split pattern in use (e.g. `test_command_executor_error_handler.py`
   next to `test_command_executor.py`) — follow that shape exactly, including relative
   `from .conftest import ...` imports and short docstrings naming sibling files. The sixth
   (`tests/integration/test_websocket_service.py`) has no sibling pattern; it becomes a new
   `tests/integration/websocket/` subpackage, matching how `tests/integration/bus/`,
   `tests/integration/web_api/`, and `tests/integration/telemetry/` are already organized as
   subpackages.
2. Before adding any new local `make_*`/`build_*` helper, check
   `src/hassette/test_utils/factories.py` and `src/hassette/test_utils/helpers.py` first per
   `.claude/rules/test-conventions.md`. Do not duplicate a shared factory under a local name.
3. Verify each split by running the affected tests before and after moving, confirming the same
   test count/IDs collect and pass. No test may be dropped, duplicated, or renamed in a way that
   changes what it covers.

## Constraints

- No changes to any file under `src/hassette/` — these are test-only moves.
- Do not change test logic, assertions, fixtures' behavior, or add new tests. This is pure
  extraction.
- Do not leave the original file behind as a stub or an empty shell — if all of its content
  moves out, delete it; if some tests remain, only the moved subset leaves.
- Do not introduce new shared helpers/fixtures unless a genuinely duplicated need across the
  split files justifies promoting one to `conftest.py` (per the directory's existing pattern).
- Each resulting file must be under 800 lines.
