---
task_id: "T04"
title: "Deduplicate main and web_api_service tests"
status: "done"
depends_on: []
implements: ["FR#1", "FR#3", "AC#1", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `tests/unit/core/test_main.py`
- modify: `tests/unit/core/test_web_api_service.py`

## Prompt

Resolve every PMD-CPD duplicate-code cluster touching `tests/unit/core/test_main.py` and
`tests/unit/core/test_web_api_service.py`. Read
`design/specs/099-dedupe-tests-unit-core/design.md` (Approach section, Group D row) for context —
this group is self-contained: all clusters live entirely within these two files (no clusters pair
across the two files with each other in this group; each file's clusters are self-contained to
that file), no cross-scope files involved.

1. Run the scoped check (line numbers drift as you resolve earlier clusters — always trust a fresh run):
   ```bash
   uv run python tools/check_duplicate_code.py 2>&1 | grep -E "tests/unit/core/test_(main|web_api_service)\.py"
   ```
   Expect ~4 clusters at sketch time (2 in each file).

2. For each cluster, inspect the actual fragments and decide extract vs. annotate per the
   framework in the design doc's "Extract vs. annotate" section. Prefer extraction for mechanical
   boilerplate. Before adding any new local helper/fixture, check `tests/unit/core/conftest.py`'s
   existing catalog (module docstring + directory `CLAUDE.md`) for one that already does the job —
   don't duplicate an existing fixture (FR#3).

3. After resolving all clusters, re-run the grep command from step 1 and confirm no output.

4. Run the tests:
   ```bash
   uv run pytest tests/unit/core/test_main.py tests/unit/core/test_web_api_service.py -v
   ```

5. Run `prek -a` on the changed files and fix any lint/type findings.

## Verify

- [ ] FR#1: grep from step 1 produces no output.
- [ ] FR#3: no new helper/fixture duplicates one already in `tests/unit/core/conftest.py`.
- [ ] AC#1: scoped grep from the design doc's AC#1 for these files is clean.
- [ ] AC#2: pytest command passes with 0 failures.
- [ ] AC#3: `prek -a` clean.
- [ ] AC#4: every `dup-ignore` marker (if any used) has a specific, non-generic reason.
