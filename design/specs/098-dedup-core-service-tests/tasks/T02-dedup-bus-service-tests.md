---
task_id: "T02"
title: "Deduplicate bus_service test files flagged by tools/check_duplicate_code.py"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "AC#1", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `tests/unit/core/test_bus_service_error_handler.py`
- modify: `tests/unit/core/test_bus_service_public_accessors.py`
- modify: `tests/unit/core/test_bus_service_timeout.py`
- modify: `tests/unit/bus/test_invocation.py` (dup-ignore marker only — see cross-scope clusters below)

Note: `tests/unit/core/test_bus_service_config_hot_reload.py` and `tests/unit/core/test_bus_service_predicate_failure.py` are in the issue's named scope but currently have **zero** flagged clusters — confirm that during verification (they should already pass the grep check) but no changes are expected there.

## Prompt

Read `design/specs/098-dedup-core-service-tests/design.md` (Approach section) and `design/specs/098-dedup-core-service-tests/tasks/context.md` first — they explain the two-track (extract vs. annotate) decision framework and the existing `tests/unit/core/conftest.py` factory catalog.

`tools/check_duplicate_code.py` (PMD CPD clone detector) currently flags 5 duplicate clusters across these files (ground truth as of 2026-08-16 — re-run for current line numbers):

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep -A3 "test_bus_service\|test_invocation"
```

Snapshot of the 5 clusters (file:start-end):

1. `test_bus_service_timeout.py:18-26,32-40,46-54`
2. `test_bus_service_error_handler.py:18-25,32-39,46-53`
3. `test_bus_service_public_accessors.py:114-119,126-131,138-143`
4. **Cross-scope**: `tests/unit/bus/test_invocation.py:146-150` + `test_bus_service_error_handler.py:21-25,35-39,49-53` + `test_bus_service_timeout.py:22-26,36-40,50-54`
5. **Cross-scope**: `tests/unit/bus/test_invocation.py:47-51` + `test_bus_service_error_handler.py:20-24,34-38,48-52` + `test_bus_service_timeout.py:21-25,35-39,49-53`

Clusters 4 and 5 span three files across two different test areas (`tests/unit/core/` and `tests/unit/bus/`) — per design.md's Approach section, the recommended treatment is **annotate**, not extract: `test_invocation.py` covers the Bus subsystem's own invocation path while `test_bus_service_error_handler.py`/`test_bus_service_timeout.py` cover the BusService layer — these are intentionally parallel tests at different layers, not one accidentally copy-pasted three times. Wrap all fragments in each cluster (including the `test_invocation.py` side) with `dup-ignore-start: <reason naming both layers>` / `dup-ignore-end`. This means editing `test_invocation.py` — a comment-only addition, not a restructure of that file's test bodies.

For clusters 1-3 (self-contained within this group), apply the extract-or-annotate decision from design.md's Approach section based on what you find in the flagged ranges. Check `tests/unit/core/conftest.py` first before adding any new shared helper — but **do not add a new fixture/helper to `conftest.py` itself**; it's a shared write target across all four parallel tasks, and none of these clusters require a `conftest.py`-level helper. Keep any new helper local to the file it's extracted from, or shared within this group's own files.

## Verify

- [ ] FR#1, FR#2, FR#3, AC#1 (this task's slice): `uv run python tools/check_duplicate_code.py 2>&1 | grep -E "tests/unit/core/test_(bus_service|command_executor|scheduler_service|service_watcher)"` — must include no lines from `test_bus_service_error_handler.py`, `test_bus_service_public_accessors.py`, or `test_bus_service_timeout.py`.
- [ ] Confirm `test_bus_service_config_hot_reload.py` and `test_bus_service_predicate_failure.py` still produce zero findings (no action needed, just verify the assumption holds).
- [ ] AC#2: `uv run pytest tests/unit/core/test_bus_service_*.py tests/unit/bus/test_invocation.py -v` passes with the same test count as before your changes.
- [ ] AC#3: `prek -a` clean on every file you touched.
- [ ] AC#4: every `dup-ignore-start`/`dup-ignore-file` marker you added has a specific reason.
