---
task_id: "T04"
title: "Deduplicate service_watcher test files flagged by tools/check_duplicate_code.py"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "AC#1", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `tests/unit/core/test_service_watcher_coverage.py`
- modify: `src/hassette/test_utils/helpers.py` (dup-ignore marker only — see cross-scope cluster below)

Note: `tests/unit/core/test_service_watcher_exhausted.py` is in the issue's named scope but currently has **zero** flagged clusters — confirm that during verification but no changes are expected there.

## Prompt

Read `design/specs/098-dedup-core-service-tests/design.md` (Approach section) and `design/specs/098-dedup-core-service-tests/tasks/context.md` first — they explain the two-track (extract vs. annotate) decision framework.

`tools/check_duplicate_code.py` (PMD CPD clone detector) currently flags exactly 1 duplicate cluster in this group (ground truth as of 2026-08-16 — re-run for current line numbers):

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep -A3 "test_service_watcher\|helpers.py"
```

The one cluster (**cross-scope**): `src/hassette/test_utils/helpers.py:517-521` + `test_service_watcher_coverage.py:314-318,338-342`.

`src/hassette/test_utils/helpers.py` is shared test infrastructure (see `tests/TESTING.md` and `.claude/rules/test-conventions.md`) — not a test file itself, but a production-adjacent helper module imported by tests across the repo. Per design.md's Approach section, the recommended treatment is **annotate**: this file's line 517-521 is presumably a helper function body, and the two occurrences in `test_service_watcher_coverage.py` are call-site usages or a locally-duplicated inline version of the same logic — read both sides before deciding. If `test_service_watcher_coverage.py`'s two occurrences are actually reimplementing something `helpers.py` already provides (rather than a third independent pattern), the fix might be **extract**: call the existing `helpers.py` function instead of duplicating its body inline in the test file. Only fall back to a `dup-ignore` pair (with a specific reason on all three occurrences, including the `helpers.py` side) if the two are genuinely separate concerns.

## Verify

- [ ] FR#1, FR#2, FR#3, AC#1 (this task's slice): `uv run python tools/check_duplicate_code.py 2>&1 | grep -E "tests/unit/core/test_(bus_service|command_executor|scheduler_service|service_watcher)"` — must include no lines from `test_service_watcher_coverage.py`.
- [ ] Confirm `test_service_watcher_exhausted.py` still produces zero findings (no action needed, just verify the assumption holds).
- [ ] AC#2: `uv run pytest tests/unit/core/test_service_watcher_*.py -v` passes with the same test count as before your changes. Also run any test files that import the touched `helpers.py` function, if you changed its body rather than just adding a marker (grep for its usage first).
- [ ] AC#3: `prek -a` clean on every file you touched.
- [ ] AC#4: every `dup-ignore-start`/`dup-ignore-file` marker you added has a specific reason.
