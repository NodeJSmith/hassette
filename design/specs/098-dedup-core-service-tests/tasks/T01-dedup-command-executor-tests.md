---
task_id: "T01"
title: "Deduplicate command_executor test files flagged by tools/check_duplicate_code.py"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "AC#1", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `tests/unit/core/test_command_executor.py`
- modify: `tests/unit/core/test_command_executor_error_handler.py`
- modify: `tests/unit/core/test_command_executor_execution_id.py`
- modify: `tests/unit/core/test_command_executor_pipeline.py`
- modify: `tests/integration/test_command_executor_error_handler.py` (dup-ignore marker only — see cluster #12 below)
- modify: `tests/unit/test_source_tier_models.py` (dup-ignore marker only — see cluster #23 below)

## Prompt

Read `design/specs/098-dedup-core-service-tests/design.md` (Approach section) and `design/specs/098-dedup-core-service-tests/tasks/context.md` first — they explain the two-track (extract vs. annotate) decision framework, the existing `tests/unit/core/conftest.py` factory catalog, and why 2 of these clusters require touching a file outside this group's core list.

`tools/check_duplicate_code.py` (PMD CPD clone detector) currently flags 24 duplicate clusters across these 4 files (ground truth as of 2026-08-16 — re-run the command below for current line numbers, since earlier edits in the same file shift later line ranges):

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep -A3 "test_command_executor"
```

Snapshot of the 24 clusters (file:start-end), for orientation:

1. `test_command_executor_error_handler.py:186-195,205-211,221-228,247-254,284-291`
2. `test_command_executor_error_handler.py:75-82,92-99,110-117`
3. `test_command_executor_pipeline.py:244-254,588-598,618-628`
4. `test_command_executor_pipeline.py:219-227,590-598,620-628`
5. `test_command_executor.py:38-46,56-64,72-80,91-99,121-129`
6. `test_command_executor_pipeline.py:220-229,247-258,274-283`
7. `test_command_executor_pipeline.py:642-648,683-688,720-725`
8. `test_command_executor_pipeline.py:816-820,828-832,842-846`
9. `test_command_executor_error_handler.py:37-42,61-66,306-311,329-334`
10. `test_command_executor_execution_id.py:194-199,205-210,216-221,227-232,238-243`
11. `test_command_executor_execution_id.py:204-210,215-221,226-232,237-243`
12. **Cross-scope**: `test_command_executor_error_handler.py:27-31,47-51` + `tests/integration/test_command_executor_error_handler.py:43-47,175-179`
13. `test_command_executor_pipeline.py:200-208,224-232,312-320`
14. `test_command_executor_pipeline.py:269-274,586-591,617-621`
15. `test_command_executor_pipeline.py:274-281,591-598,621-628`
16. `test_command_executor_pipeline.py:664-671,707-714,744-750`
17. `test_command_executor_pipeline.py:200-205,251-258,278-283,312-317`
18. `test_command_executor_error_handler.py:34-40,82-88,117-123,187-195,206-211,222-228,248-254,285-291`
19. `test_command_executor.py:139-143` + `test_command_executor_pipeline.py:342-346,407-411`
20. `test_command_executor.py:34-38,52-56,117-121`
21. `test_command_executor_error_handler.py:35-40,83-88,118-123,188-195,207-211,223-228,249-254,286-291` + `test_command_executor_execution_id.py:404-409`
22. `test_command_executor_error_handler.py:34-38,82-86,265-269,285-289`
23. **Cross-scope**: `test_command_executor_pipeline.py:328-334,361-367,392-398` + `tests/unit/test_source_tier_models.py:42-48`
24. `test_command_executor_pipeline.py:336-341,369-374,400-406`

Known concrete patterns already spotted in `test_command_executor_pipeline.py` (informs several of the clusters above):
- An inline `async def direct_submit(coro): return await coro` assigned to `executor.hassette.database_service.submit` repeats 7 times, always paired with a `fail_persist`/similar function raising an exception and a call to `CommandExecutor.persist_batch(executor, ...)`. This is the textbook extract case — a shared helper (e.g. `direct_submit(coro)` as a module-level async function in the file, since it's specific to this file's pattern) removes the repetition without losing per-test readability.
- `test_command_executor_error_handler.py` has two near-mirror test classes, `TestBusErrorHandlerInvocation` and `TestSchedulerErrorHandlerInvocation` — same test names, same shape, differing only in `make_invoke_handler_cmd`/`executor.execute_handler`/`BusErrorContext` vs. `make_execute_job_cmd`/`executor.execute_job`/`SchedulerErrorContext`. This is the textbook annotate case per design.md's Approach section — forcing a single parametrized test across two different command types would trade a currently-obvious 1:1 mapping for indirection with no second consumer. Wrap each mirrored pair with `dup-ignore-start`/`dup-ignore-end` and a reason naming the two command types being mirrored.

For clusters 12 and 23 (cross-scope): the out-of-scope fragment (`tests/integration/test_command_executor_error_handler.py`, `tests/unit/test_source_tier_models.py`) needs the matching `dup-ignore` marker too, or the cluster stays flagged. Add a comment-only marker there — do not restructure those files' test bodies.

Work through the clusters, applying extract or annotate per design.md's framework. For extraction, check `tests/unit/core/conftest.py` (and its directory `CLAUDE.md`) first — do not add a second copy of an existing factory. **Do not add a new fixture/helper to `conftest.py`** — it's a shared write target across all four parallel tasks, and none of these clusters require a `conftest.py`-level helper. Keep any new helper local to the file it's extracted from, or shared via an in-file/in-group import if a cluster pairs two files in this group (e.g. `test_command_executor_error_handler.py` and `test_command_executor_execution_id.py`).

This is the largest group (24 of 35 total clusters, `test_command_executor_pipeline.py` alone accounts for 13). If useful, work through it in sub-passes (e.g. `test_command_executor_pipeline.py` first, then the other three files), but land it as one task — several clusters pair `test_command_executor_pipeline.py` fragments with fragments in `test_command_executor.py`, so resolving one file without the other can leave a cluster half-fixed.

## Verify

- [ ] FR#1, FR#2, FR#3, AC#1 (this task's slice): `uv run python tools/check_duplicate_code.py 2>&1 | grep -E "tests/unit/core/test_(bus_service|command_executor|scheduler_service|service_watcher)"` — must include no lines from any of this task's files (empty overall isn't required yet since other tasks' files may still be flagged; check specifically that none of `test_command_executor*.py`, `tests/integration/test_command_executor_error_handler.py`, or `tests/unit/test_source_tier_models.py` appear).
- [ ] AC#2: `uv run pytest tests/unit/core/test_command_executor*.py tests/integration/test_command_executor_error_handler.py tests/unit/test_source_tier_models.py -v` passes with the same test count as before your changes (no coverage silently dropped).
- [ ] AC#3: `prek -a` clean on every file you touched.
- [ ] AC#4: every `dup-ignore-start`/`dup-ignore-file` marker you added has a specific reason (not "intentional" alone).
