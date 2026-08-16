# Design: Deduplicate tests/unit/core service tests

**Date:** 2026-08-16
**Status:** archived
**Mode:** sketch

## Problem

`tools/check_duplicate_code.py` (PMD CPD-based clone detection) fails on `main` today. This is known, non-blocking baseline debt (`continue-on-error: true` in CI) — CLAUDE.md's "Known-failing lint checks" note documents this pattern for the `duplicate-code` job generally (citing its own tracking example, #1573), and issue #1616 is itself split from #1561, the original all-of-`tests/unit/core/` cleanup issue. Issue #1616 scopes cleanup to the 16 named files in `tests/unit/core/` covering bus service, command executor, scheduler service, and service watcher tests. A ground-truth run of the checker (2026-08-16, this session) confirms **35 flagged clusters** touch these 16 files — 30 entirely self-contained within the 16 files, 5 that also include a fragment in a file outside the named scope.

## Goals

- Zero un-annotated duplicate clusters reported for the 16 scoped files.
- Preserve all existing behavior coverage — tests may be restructured, but nothing they verify becomes untested.
- Every `dup-ignore` annotation carries a specific, non-generic reason.

## Functional Requirements

- **FR#1** For each of the 35 flagged clusters touching the 16 scoped files, either extract the repeated pattern into a shared fixture/helper/parametrized test, or wrap every occurrence in the cluster with a `# dup-ignore-start: <reason>` / `# dup-ignore-end` pair.
- **FR#2** For the 5 clusters that include a fragment in a file outside the 16-file scope (listed in Approach below), every occurrence — including the out-of-scope fragment — must be resolved (extracted or annotated), since the checker only suppresses a cluster once *all* its fragments are clear.
- **FR#3** Extraction targets reuse the existing `tests/unit/core/conftest.py` factories/fixtures catalog (see its module docstring and directory `CLAUDE.md`) rather than duplicating a second copy of an existing helper.

## Acceptance Criteria

- **AC#1** `uv run python tools/check_duplicate_code.py 2>&1 | grep -E "tests/unit/core/test_(bus_service|command_executor|scheduler_service|service_watcher)"` (the exact command the issue specifies) produces no output.
- **AC#2** The affected test files still pass: `uv run pytest tests/unit/core/test_bus_service_*.py tests/unit/core/test_command_executor*.py tests/unit/core/test_scheduler_service_*.py tests/unit/core/test_service_watcher_*.py -v`.
- **AC#3** `prek -a` (ruff + pyright + other hooks) is clean on every changed file.
- **AC#4** Every `dup-ignore-start`/`dup-ignore-file` marker added has a specific reason (not "intentional" or "duplicate" alone).

## Approach

### Ground truth, not the issue's stale estimate

The issue's own suggested verification command was run for real (PMD CPD, full-repo scan, ~3 min). Result: **35 clusters**, grouped by the four sub-areas the issue's filename prefixes imply:

| Group | Files | Clusters | Cross-scope clusters |
|---|---|---:|---:|
| `command_executor` | `test_command_executor.py`, `test_command_executor_error_handler.py`, `test_command_executor_execution_id.py`, `test_command_executor_pipeline.py` | 24 | 2 |
| `bus_service` | `test_bus_service_error_handler.py`, `test_bus_service_public_accessors.py`, `test_bus_service_timeout.py` (config_hot_reload and predicate_failure have zero findings) | 5 | 2 |
| `scheduler_service` | `test_scheduler_service_error_handler.py`, `test_scheduler_service_reschedule.py`, `test_scheduler_service_timeout.py`, `test_scheduler_service_trigger.py` (dequeue has zero findings) | 5 | 0 |
| `service_watcher` | `test_service_watcher_coverage.py` (exhausted has zero findings) | 1 | 1 |

This becomes the four task groups — same split proposed in the originating issue triage, now backed by an actual cluster count instead of a fragment-line estimate (the issue's 137-line figure is PMD's raw pairwise fragment count pre-clustering; 35 is the real unit of work — one cluster = one decision to make).

### The 5 cross-scope clusters (FR#2)

These clusters have at least one fragment in a file **outside** the named 16, so resolving only the in-scope side leaves the cluster (and therefore the AC#1 grep) still failing:

1. `command_executor` group: `tests/unit/core/test_command_executor_error_handler.py:27-31,47-51` clusters with `tests/integration/test_command_executor_error_handler.py:43-47,175-179`.
2. `command_executor` group: `tests/unit/core/test_command_executor_pipeline.py:328-334,361-367,392-398` clusters with `tests/unit/test_source_tier_models.py:42-48`.
3. `bus_service` group: `tests/unit/core/test_bus_service_error_handler.py` + `test_bus_service_timeout.py` (3 fragments each) cluster with `tests/unit/bus/test_invocation.py:146-150`.
4. `bus_service` group: same file pair, different line ranges, clusters with `tests/unit/bus/test_invocation.py:47-51`.
5. `service_watcher` group: `tests/unit/core/test_service_watcher_coverage.py:314-318,338-342` clusters with `src/hassette/test_utils/helpers.py:517-521`.

Recommended treatment for all 5: **annotate**, not extract. Each pairs a `tests/unit/core/` file with a file in a different test tier (`tests/integration/`) or different subsystem (`tests/unit/bus/`, `src/hassette/test_utils/helpers.py`) — unit vs. integration test bodies for the same feature are intentionally parallel (different fixtures, different mock depth; see `tests/TESTING.md`'s mock-strategy split), and merging a unit-test helper with a bus-subsystem test or a `test_utils` production helper would cross a module boundary this codebase deliberately keeps separate. Each task below authorizes touching the specific named out-of-scope file to add the matching `dup-ignore` marker pair — this is a comment-only edit, not a functional change, so it stays inside "the smallest change that solves the problem" (`rules/common/laziness-protocol.md`) without expanding into an unrelated file's logic.

### Extract vs. annotate, in general

`tests/unit/core/conftest.py` already carries a substantial shared-factory catalog (`make_executor`, `make_bus_service`, `make_scheduler_service`, `make_watcher`, `make_mock_cmd_listener`, `make_execute_job_cmd`, etc. — see its module docstring and the directory's `CLAUDE.md`). The flagged duplication in these files is **not** missing setup fixtures — it's repeated *test-body* shape: e.g. `test_command_executor_pipeline.py` repeats an inline

```python
async def direct_submit(coro):
    return await coro
executor.hassette.database_service.submit = direct_submit
```

pair across 7 tests (visible directly in the file at the read-out lines cited in the cluster table), and `test_command_executor_error_handler.py` has two near-mirror test classes, `TestBusErrorHandlerInvocation` and `TestSchedulerErrorHandlerInvocation`, whose bodies differ only in `make_invoke_handler_cmd`/`execute_handler`/`BusErrorContext` vs. `make_execute_job_cmd`/`execute_job`/`SchedulerErrorContext`. Per each task's own investigation of its flagged fragments, apply the issue's own two-track rule:

- **Extract** (default) when the repeated block is mechanical boilerplate with no reader value in staying inline — e.g. the `direct_submit` pattern → a shared `direct_submit(coro)` async helper local to the file (or shared within the group's own files if a cluster pairs two of them — never promoted to `conftest.py`; see "Task split and ordering" below), or a small `raising_persist(exc)` factory for the repeated "raise sqlite3.OperationalError, then persist_batch" setup.
- **Annotate** when duplication is genuinely parallel structure that reads more clearly left alone — e.g. the Bus/Scheduler error-handler test-class mirror, where forcing a single parametrized test across two different command types (`InvokeHandler` vs `ExecuteJob`) would trade a currently-obvious 1:1 mapping for an indirection with no second consumer (`rules/common/reader-load.md`). This matches the checker's own module docstring precedent (the "Shape B delegate" convention already gets this treatment elsewhere in the codebase).

Each task instructs the executor to run the checker scoped to its own group (`grep` filtered to its filenames), inspect the exact current fragments (line numbers will drift as earlier clusters in the same file get resolved — this is expected; rerun rather than trust stale line numbers), and make the call per-cluster using the framework above.

### Task split and ordering

Four tasks, one per group, independently landable (disjoint file sets — no task's Target Files overlaps another's, so orchestrate can run them without serialization on a shared write target). `command_executor` is by far the largest (24 of 35 clusters); if it proves too large for one pass, the task prompt allows splitting `test_command_executor_pipeline.py` (13 of the 24) from the other three `command_executor` files as an internal sub-sequence, but they still land as one task since PMD's clone graph pairs pipeline fragments with fragments in the sibling `command_executor` files in several clusters (see the `test_command_executor.py:139-143` / `test_command_executor_pipeline.py:342-346,407-411` cluster, for example) — splitting across two tasks would let one task's fix half-resolve a cluster the other task also needs to touch.

No task depends on another — all four run in parallel. **`tests/unit/core/conftest.py` is explicitly out of scope for all four tasks.** None of the 35 flagged clusters pair files across two different groups (every cluster's fragments sit either entirely within one group or reach outside the 16-file scope entirely — never into a sibling group), so no cluster's fix genuinely requires a `conftest.py`-level shared helper. Since `conftest.py` is a single shared write target read by all four groups, tasks must not promote a new helper there — a helper shared within a group stays local to that group's own files. This removes the one shared-mutable-state risk the four parallel tasks would otherwise have (`rules/common/decomposition-discipline.md` — split the write target rather than serialize when sharing isn't a real invariant).

## Dependencies and Assumptions

None — this is self-contained test restructuring with no external dependency and no verification gap. The PMD CPD checker needs Java 21+ on PATH; already verified present on this machine.

## Changed Files

- modify: `tests/unit/core/test_command_executor.py`
- modify: `tests/unit/core/test_command_executor_error_handler.py`
- modify: `tests/unit/core/test_command_executor_execution_id.py`
- modify: `tests/unit/core/test_command_executor_pipeline.py`
- modify: `tests/integration/test_command_executor_error_handler.py` (dup-ignore marker only)
- modify: `tests/unit/test_source_tier_models.py` (dup-ignore marker only)
- modify: `tests/unit/core/test_bus_service_error_handler.py`
- modify: `tests/unit/core/test_bus_service_public_accessors.py`
- modify: `tests/unit/core/test_bus_service_timeout.py`
- modify: `tests/unit/bus/test_invocation.py` (dup-ignore marker only)
- modify: `tests/unit/core/test_scheduler_service_error_handler.py`
- modify: `tests/unit/core/test_scheduler_service_reschedule.py`
- modify: `tests/unit/core/test_scheduler_service_timeout.py`
- modify: `tests/unit/core/test_scheduler_service_trigger.py`
- modify: `tests/unit/core/test_service_watcher_coverage.py`
- modify: `src/hassette/test_utils/helpers.py` (dup-ignore marker only)
