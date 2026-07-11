---
task_id: "T05"
title: "Add CI lint enforcing coordinator-internal annotations"
status: "planned"
depends_on: ["T02", "T03", "T04"]
implements: ["FR#8", "AC#3", "AC#4", "AC#5", "AC#6", "AC#7"]
---

## Summary
Add a CI lint script that enforces `# coordinator-internal` annotations on private-attribute accesses in the 3 affected test files. Model it on `tools/check_internal_patches.py` which already does AST-based annotation enforcement for a structurally identical problem. Run the full test suite and linter to verify everything passes.

## Target Files
- create: `tools/check_coordinator_internal.py`
- modify: `.github/workflows/lint.yml`
- read: `tools/check_internal_patches.py`

## Prompt
Create `tools/check_coordinator_internal.py` — an AST-based CI guard that scans `tests/integration/test_core.py`, `tests/integration/test_fatal_shutdown.py`, and `tests/integration/test_resource_deps.py` for private-attribute accesses on `hassette_instance` (or on variables assigned from `hassette_instance.<property>` like `sm = hassette_instance.session_manager`) that lack a `# coordinator-internal` annotation.

Study `tools/check_internal_patches.py` for the pattern:
- AST-based detection of attribute access on specific receivers
- `tokenize`-derived comment token matching on the flagged statement's own physical lines
- Exit code 0 for clean, non-zero for violations
- Clear output: file:line, the offending access, and what annotation is expected

The script should:
1. Parse each in-scope file's AST
2. Find `ast.Attribute` nodes where the `attr` starts with `_` (private access)
3. Filter to accesses on known receiver names: `hassette_instance`, `sm` (or any local assigned from `hassette_instance.session_manager`)
4. For each flagged access, check if the statement's physical lines contain `# coordinator-internal`
5. Report violations and exit non-zero if any found

Wire it into `.github/workflows/lint.yml` as a CI step (same pattern as the existing `check_internal_patches` step at line 113: `run: uv run python tools/check_coordinator_internal.py`). Place it adjacent to the existing check.

After creating the script and wiring the hook, run the full verification:
1. `uv run nox -s dev` — all tests pass
2. `prek -a` — all linters and type checks pass
3. Run the new script directly to verify it passes with the annotations from T02/T03

## Focus
- `check_internal_patches.py` uses `extract_comments` from `tools/lint_helpers.py` for tokenize-based comment matching (the `is_exempt` function at ~line 245). This avoids false positives from annotation text inside string literals. Replicate this approach.
- The receiver-name heuristic in `check_internal_patches.py` (lines 27-30) prevents false positives from other objects that happen to have `_`-prefixed attributes. Use the same heuristic with `hassette_instance` and derived locals.
- The existing lint CI step in `.github/workflows/lint.yml:113` uses `run: uv run python tools/check_internal_patches.py`. Match this pattern for the new script.
- This script should be executable (`chmod +x`).

## Verify
- [ ] FR#8: Script detects unannotated private-attr access and fails; annotated accesses pass
- [ ] AC#3: Fixture teardown in conftest.py has no inline private-attr access (verified by T01; conftest.py is not in the lint's scan scope — the lint covers the 3 test files only)
- [ ] AC#4: All `# coordinator-internal` annotations in T02/T03 are recognized by the lint
- [ ] AC#5: `uv run nox -s dev` passes — all 34 tests still pass with no behavior change
- [ ] AC#6: `prek -a` passes — lint + type check clean
- [ ] AC#7: `git diff` shows no changes to `src/hassette/test_utils/harness.py` — HassetteHarness is unchanged
