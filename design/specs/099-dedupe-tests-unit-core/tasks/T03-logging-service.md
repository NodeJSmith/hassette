---
task_id: "T03"
title: "Deduplicate logging service tests"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#3", "AC#1", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `tests/unit/core/test_logging_service.py`

## Prompt

Resolve every PMD-CPD duplicate-code cluster in `tests/unit/core/test_logging_service.py`. Read
`design/specs/099-dedupe-tests-unit-core/design.md` (Approach section, Group C row) for context —
this group is self-contained: all clusters live entirely within this one file, no cross-scope
files involved.

1. Run the scoped check (line numbers drift as you resolve earlier clusters — always trust a fresh run):
   ```bash
   uv run python tools/check_duplicate_code.py 2>&1 | grep "tests/unit/core/test_logging_service\.py"
   ```
   Expect ~4 clusters at sketch time.

2. For each cluster, inspect the actual fragments and decide extract vs. annotate per the
   framework in the design doc's "Extract vs. annotate" section. Prefer extraction here — a
   single-file cluster with no cross-boundary fragments is the clearest case for pulling repeated
   setup/assertion shapes into a local helper or fixture. Only annotate if a specific pair of tests
   is genuinely clearer left as parallel, explicit code (name why in the marker's reason). Before
   adding any new local helper/fixture, check `tests/unit/core/conftest.py`'s existing catalog
   (module docstring + directory `CLAUDE.md`) for one that already does the job — don't duplicate
   an existing fixture (FR#3).

3. After resolving all clusters, re-run the grep command from step 1 and confirm no output.

4. Run the tests: `uv run pytest tests/unit/core/test_logging_service.py -v`

5. Run `prek -a` on the changed file and fix any lint/type findings.

## Verify

- [ ] FR#1: grep from step 1 produces no output.
- [ ] FR#3: no new helper/fixture duplicates one already in `tests/unit/core/conftest.py`.
- [ ] AC#1: scoped grep from the design doc's AC#1 for this file is clean.
- [ ] AC#2: `uv run pytest tests/unit/core/test_logging_service.py -v` passes with 0 failures.
- [ ] AC#3: `prek -a` clean.
- [ ] AC#4: every `dup-ignore` marker (if any used) has a specific, non-generic reason.
