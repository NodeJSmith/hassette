---
task_id: "T05"
title: "Deduplicate unified execution tests"
status: "done"
depends_on: []
implements: ["FR#1", "FR#3", "AC#1", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `tests/unit/core/test_unified_execution.py`

## Prompt

Resolve every PMD-CPD duplicate-code cluster in `tests/unit/core/test_unified_execution.py`. Read
`design/specs/099-dedupe-tests-unit-core/design.md` (Approach section, Group E row) for context —
this is the heaviest single-file group (10 clusters at sketch time, all self-contained to this
file — no cross-scope files involved).

1. Run the scoped check (line numbers drift as you resolve earlier clusters — always trust a fresh run):
   ```bash
   uv run python tools/check_duplicate_code.py 2>&1 | grep "tests/unit/core/test_unified_execution\.py"
   ```
   Expect ~10 clusters at sketch time, several overlapping/nested (the same lines appearing in
   multiple reported clusters as PMD's pairwise matching finds different-length matches over the
   same region) — resolving the underlying repeated pattern once typically collapses several
   reported clusters at once. Work from the largest/most-repeated pattern down.

2. For each cluster, inspect the actual fragments and decide extract vs. annotate per the
   framework in the design doc's "Extract vs. annotate" section. Given the volume and that this is
   a single cohesive test file, expect extraction (shared result-construction helpers, parametrized
   cases) to resolve most of these — this file likely repeats a small number of
   "build an ExecutionResult/invoke a handler and assert its shape" patterns across many test
   functions. Before adding any new local helper/fixture, check `tests/unit/core/conftest.py`'s
   existing catalog (module docstring + directory `CLAUDE.md`) for one that already does the job —
   don't duplicate an existing fixture (FR#3).

3. After resolving all clusters, re-run the grep command from step 1 and confirm no output.

4. Run the tests: `uv run pytest tests/unit/core/test_unified_execution.py -v`

5. Run `prek -a` on the changed file and fix any lint/type findings.

## Verify

- [ ] FR#1: grep from step 1 produces no output.
- [ ] FR#3: no new helper/fixture duplicates one already in `tests/unit/core/conftest.py`.
- [ ] AC#1: scoped grep from the design doc's AC#1 for this file is clean.
- [ ] AC#2: `uv run pytest tests/unit/core/test_unified_execution.py -v` passes with 0 failures.
- [ ] AC#3: `prek -a` clean.
- [ ] AC#4: every `dup-ignore` marker (if any used) has a specific, non-generic reason.
