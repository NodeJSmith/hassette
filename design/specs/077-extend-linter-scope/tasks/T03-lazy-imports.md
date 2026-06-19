---
task_id: "T03"
title: "Resolve lazy imports across non-src dirs (hoist or annotate)"
status: "done"
depends_on: ["T02"]
implements: ["FR#6", "AC#5"]
---

## Summary
Resolve all ~34 lazy imports (imports inside function bodies) in `tests/`, `scripts/`, `tools/`, and `codegen/` case-by-case: hoist to module top where that is behavior-preserving; annotate `# lazy-import: <reason>` where the deferred import is deliberate (patching, import-timing tests, cycle-breaking in standalone scripts). No blanket relaxation.

## Target Files
Run `check_lazy_imports.check_file` over the four dirs for the live list. Reconnaissance shows these sites:
- modify: `tests/unit/test_sync_executor_service.py` — 11 sites (largest cluster).
- modify: `tests/unit/scheduler/` — 5 sites (in `test_scheduler_coroutine_conversion.py`).
- modify: `scripts/export_schemas.py` — 3 sites.
- modify: `tools/check_schemas_fresh.py` — 3 sites.
- modify: `codegen/` — 2 sites (2 files).
- modify: `tests/unit/bus/` — 2 sites.
- modify: `tests/unit/cli/` — 2 sites (2 files).
- modify: `tests/unit/test_forgotten_await_completeness.py` — 2 sites (likely deliberate — imports are the test subject).
- modify: `tests/conftest.py` — 1 site.
- modify: `tests/integration/test_command_executor.py` — 1 site.
- modify: `tests/unit/core/` — 1 site.
- modify: `tests/unit/test_schema_migration.py` — 1 site.
- read: `tools/check_lazy_imports.py` — the `# lazy-import:` annotation contract.

## Prompt
Resolve every lazy import outside `src/` per the design doc (`design/specs/077-extend-linter-scope/design.md`, `## Functional Requirements` FR#6, `## Edge Cases`, and `## Key Constraints`).

For each site reported by `check_lazy_imports.check_file` over `tests/`, `scripts/`, `tools/`, `codegen/`:

1. **Read the surrounding function** and decide:
   - **Hoist** to the top of the file if moving the import there is behavior-preserving — no patch target depends on the import being deferred, no import cycle is being broken, the import is not the thing under test, and import side effects don't matter for timing.
   - **Annotate** `# lazy-import: <reason>` (reason required, non-empty) if the import is deliberately deferred:
     - the test patches the imported module/object and needs the import to happen at call time after the patch is installed;
     - the import *is* the subject of the test (e.g. `tests/unit/test_forgotten_await_completeness.py` imports inside functions to exercise import behavior);
     - a standalone script (`scripts/export_schemas.py`, `tools/check_schemas_fresh.py`) defers a heavy or cycle-prone import to call time.

2. When hoisting, place the import with the other top-of-file imports, respecting the repo's import ordering (stdlib / third-party / first-party), and confirm nothing breaks.

3. The annotation may sit on the import's own line, on any continuation line of a parenthesized import, or on the comment-only line immediately above it (no blank line between). Canonical form: `# lazy-import: break circular import with <module>` — but write the *real* reason for each site.

4. Verify: import `check_lazy_imports.check_file` and run it over `["tests","scripts","tools","codegen"]` — it must report zero un-annotated lazy imports. Then run the affected test files (at minimum `uv run pytest tests/unit/test_sync_executor_service.py tests/unit/scheduler/ tests/unit/test_forgotten_await_completeness.py -q`) to confirm hoists didn't break patching or import-timing behavior.

Production `SCAN_DIRS` stays `["src"]` here — verification is via the imported `check_file`. Widening happens in T09.

## Focus
- The annotation contract is documented in `tools/check_lazy_imports.py:14-26` and matched by `ANNOTATION_RE` (`#\s*lazy-import:\s*\S`) — an empty reason does NOT exempt.
- **Highest-risk hoists are the patching tests.** `tests/unit/test_sync_executor_service.py` (11 sites) and `tests/unit/scheduler/test_scheduler_coroutine_conversion.py` (5) are the clusters — read each carefully; if the import is inside a test that then patches that module, annotate rather than hoist (hoisting would bind the name before the patch and break the test). This is the per-`Mock at Boundaries` / behavior-preserving rule.
- `tests/unit/test_forgotten_await_completeness.py` imports inside functions on purpose — almost certainly annotate, not hoist.
- `scripts/export_schemas.py` and `tools/check_schemas_fresh.py` may defer imports to avoid a heavy import at module load — check whether hoisting changes script startup behavior; annotate if it does.
- This task depends on T02 (dividers) so the divider pass and the lazy-import pass don't both rewrite the same files concurrently; orchestrate runs them in order.
- Do not touch `src/` — it is already clean and out of this task's scope.

## Verify
- [ ] FR#6: each remaining in-function import in the covered scope is justified — hoisted where clean, or carrying a non-empty `# lazy-import:` reason where deliberate.
- [ ] AC#5: importing `check_lazy_imports.check_file` and running it over `["tests","scripts","tools","codegen"]` reports zero un-annotated lazy imports; the affected patching/import-timing test files still pass.
