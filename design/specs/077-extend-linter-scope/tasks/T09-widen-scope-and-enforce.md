---
task_id: "T09"
title: "Widen SCAN_DIRS, hook patterns, and CI filter; update docs"
status: "done"
depends_on: ["T01", "T02", "T03", "T04", "T05", "T06", "T07", "T08"]
implements: ["FR#1", "FR#2", "FR#9", "FR#10", "FR#11", "FR#12", "AC#1", "AC#2", "AC#8", "AC#9", "AC#11", "AC#12"]
---

## Summary
The flip and final GREEN checkpoint. Now that every violation is cleaned and the two files renamed, widen `SCAN_DIRS` in all three checkers to scan `tests/`, `scripts/`, `tools/`, `codegen/`, `docs/`, and `examples/`; update the checker tests' `test_real_src_files_pass` naming/docstrings; widen the three pre-push hooks' `files:` patterns and reword their `name:` fields; add `codegen/**`, `docs/**`, and `scripts/**` to the CI `python` paths-filter (`examples/**` is already in it); and update scope wording in `CLAUDE.md` and any rule/doc that calls these `src/`-only. Success is all three checkers exiting 0 over the widened scope and a clean full pre-push run.

## Target Files
- modify: `tools/check_spec_tokens.py` — `SCAN_DIRS = ["src", "tests", "scripts", "tools", "codegen", "docs", "examples"]`.
- modify: `tools/check_llm_cruft.py` — same `SCAN_DIRS`.
- modify: `tools/check_lazy_imports.py` — same `SCAN_DIRS`.
- modify: `tests/unit/tools/test_check_spec_tokens.py` — rename `test_real_src_files_pass` → scope-agnostic name; update its docstring (it scans more than src now).
- modify: `tests/unit/tools/test_check_llm_cruft.py` — same test rename/docstring.
- modify: `tests/unit/tools/test_check_lazy_imports.py` — same test rename/docstring.
- modify: `.pre-commit-config.yaml` — widen `files:` to `^(src|tests|scripts|tools|codegen|docs|examples)/.*\.py$` on `check-lazy-imports`, `check-spec-tokens`, `check-llm-cruft`; reword their `name:` fields to drop "in src".
- modify: `.github/workflows/lint.yml` — add `codegen/**`, `docs/**`, `scripts/**` to the `python` paths-filter (lines ~29–41).
- modify: `CLAUDE.md` — update any text describing these checkers as `src/`-scoped.
- read: `tools/lint_helpers.py` — `iter_py_files` (no change).

## Prompt
Perform the scope flip per the design doc (`design/specs/077-extend-linter-scope/design.md`, `## Architecture` layers 1 and 3, FR#1/FR#2/FR#9/FR#10/FR#11).

1. **Widen `SCAN_DIRS`** in all three checkers to `["src", "tests", "scripts", "tools", "codegen", "docs", "examples"]`. No other logic change — `iter_py_files` already `rglob`s each dir.

1b. **Tighten `TOKEN_RE`** in `tools/check_spec_tokens.py` (FR#12) to close two blind spots review found:
   - Clock guard: change `\bT\d{2,}\b(?!:)` to `\bT\d{2,}\b(?!:\d)` so `T05: Saturation` (planning, colon+non-digit) is caught while `T05:30` (real time, colon+digit) is still skipped.
   - Sub-criterion letter: change `\b(?:AC|FR|NFR|WP)#?\d+\b` to `\b(?:AC|FR|NFR|WP)#?\d+[a-z]?\b` so `AC#6a`/`FR#3b` are caught (the trailing letter no longer breaks the word boundary).
   Keep the rest of `TOKEN_RE` and its case-sensitivity unchanged. Update the regex's explanatory comment to describe the new forms. Add a unit test in `tests/unit/tools/test_check_spec_tokens.py` asserting: a comment `# T05: foo` is flagged; a comment/docstring with `AC#6a` is flagged; a data/string line with a real time `"T05:30:00"` is NOT flagged (the existing clock-time case); the content case-sensitivity is unchanged.
   IMPORTANT: after tightening, re-scan the ALREADY-cleaned dirs — the tightened regex may surface residuals the prior tasks' checker missed. Run `check_spec_tokens` over the full widened scope (step 6) and clean any new hit it now reports (reword per FR#8). The 5 known residuals from earlier review were already cleaned manually, so expect few or none.

2. **Update the checker tests** `test_real_src_files_pass` in all three `tests/unit/tools/test_check_*.py` files: rename to a scope-agnostic name (e.g. `test_real_repo_files_pass`) and update the `"""The guard must stay green on the actual repo files it polices."""`-style docstrings so they don't say "src". These tests are parametrized over `iter_paths()`, so widening `SCAN_DIRS` makes them assert every file in the new dirs is clean — they are the oracle for this task.

3. **Widen the pre-push hooks** in `.pre-commit-config.yaml`: change `files: ^src/.*\.py$` to `files: ^(src|tests|scripts|tools|codegen|docs|examples)/.*\.py$` on the three hooks `check-lazy-imports`, `check-spec-tokens`, `check-llm-cruft` (leave `check-module-boundaries` as-is — out of scope). Reword each hook's `name:` to drop the "in src" phrasing (e.g. "Ban lazy imports (use '# lazy-import:' ...)").

4. **Add to the CI `python` paths-filter** in `.github/workflows/lint.yml` (the `filter` step, ~lines 29–41): add `'codegen/**'`, `'docs/**'`, and `'scripts/**'` to the `python:` list. `'tests/**'`, `'tools/**'`, and `'examples/**'` are already present — do not duplicate.

5. **Update docs/scope wording**: in `CLAUDE.md`, update any sentence describing these three checkers as guarding only `src/`. Grep `CLAUDE.md`, `.claude/rules/`, and `CONTRIBUTING.md` for scope claims about these checkers and correct them. Do NOT edit `design/` historical records or `CHANGELOG.md`.

6. **Verify the GREEN checkpoint:**
   - Run each checker from the repo root: `uv run python tools/check_spec_tokens.py`, `uv run python tools/check_llm_cruft.py`, `uv run python tools/check_lazy_imports.py` — each must print `OK` and exit 0.
   - Run the checker unit tests: `uv run pytest tests/unit/tools/ -q`.
   - Run the full pre-push hook set: `SKIP=eslint,tsc,prettier prek run --all-files --hook-stage pre-push` (mirrors CI line 88) — must pass.

If any checker reports residual violations, those are stragglers the cleanup tasks missed — fix them (reword/remove/annotate per the same rules) before this task is done; this is the intended place to catch them.

## Focus
- `SCAN_DIRS` literals: `tools/check_spec_tokens.py:45`, `tools/check_llm_cruft.py:38`, `tools/check_lazy_imports.py:42`.
- The `test_real_src_files_pass` definitions: `test_check_spec_tokens.py:102-105`, `test_check_llm_cruft.py:88`, `test_check_lazy_imports.py:127`. Each is `@pytest.mark.parametrize("path", iter_paths(), ...)` — parametrization happens at collection time, so a widened `SCAN_DIRS` immediately expands these.
- The three pre-push hooks are at `.pre-commit-config.yaml:167-192`; `check-module-boundaries` (line 194) is intentionally left at `^src/.*\.py$`.
- The CI `python` paths-filter is at `.github/workflows/lint.yml:29-41`; the prek-runs-checkers step is line 88 (no edit needed there — widening `SCAN_DIRS` makes it cover the new dirs).
- `CLAUDE.md` memory/notes describe these as `src/`-scoped pre-push linters — update that wording.
- This task depends on all cleanup tasks; if it goes red, the cause is a missed violation, not a flaw in the flip.

## Verify
- [ ] FR#1 / AC#2: `SCAN_DIRS` in all three checkers equals `["src","tests","scripts","tools","codegen","docs","examples"]` and `iter_paths()` resolves files under each.
- [ ] FR#2 / AC#1: each of the three checkers run from the repo root prints `OK` and exits 0.
- [ ] FR#12 / AC#12: `TOKEN_RE` is `\bT\d{2,}\b(?!:\d)` for the clock guard and `\d+[a-z]?` for the criterion suffix; a unit test asserts `# T05: foo` and `AC#6a` are flagged while a real time `T05:30:00` is not; the tightened checker still reports 0 across the full widened scope.
- [ ] FR#9 / AC#8: the three hooks' `files:` regex is `^(src|tests|scripts|tools|codegen|docs|examples)/.*\.py$`, so a push touching only a `tests/` file triggers them.
- [ ] FR#10 / AC#9: the CI `python` paths-filter includes `codegen/**`, `docs/**`, and `scripts/**`.
- [ ] FR#11: the `test_real_src_files_pass` tests are renamed scope-agnostically with updated docstrings; `CLAUDE.md` no longer describes the checkers as `src/`-only; and grepping the three `tools/check_*.py` files finds no residual `in src/`/`under src` scope wording in output strings or docstrings (the literal fixes from T01/AC#10 are present — this re-confirms them at the flip).
- [ ] AC#11: `SKIP=eslint,tsc,prettier prek run --all-files --hook-stage pre-push` passes; `uv run pytest tests/unit/tools/ -q` passes.
