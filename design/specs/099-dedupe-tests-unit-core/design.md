# Design: Deduplicate tests/unit/core infra and remaining tests

**Date:** 2026-08-17
**Status:** draft
**Mode:** sketch

## Problem

`tools/check_duplicate_code.py` (PMD CPD-based clone detection) fails on `main` today — known,
non-blocking baseline debt (`continue-on-error: true`; see CLAUDE.md's "Known-failing lint
checks"). Issue #1618 is the third of three splits from #1561 (which covered all of
`tests/unit/core/`): #1616/#1633 already resolved the service-test group (`bus_service`,
`command_executor`, `scheduler_service`, `service_watcher`), #1617 covers app & lifecycle tests,
and #1618 covers the 25 remaining named files — core infra (loop watchdog, blocking-IO guard,
execution timeout), telemetry/DB (repository, manifest, migration runner, log records), logging
service, and standalone files (`test_main.py`, `test_web_api_service.py`,
`test_unified_execution.py`).

A ground-truth run of the checker (2026-08-17, this session, HEAD `2bf23966`) confirms **59
flagged clusters** touch the 25 scoped files — 15 of the 25 files have at least one cluster; the
other 10 (`test_blocking_io_marker_spike.py`, `test_bus_dispatch_semaphore.py`,
`test_core_coverage.py`, `test_database_service.py`, `test_event_filter.py`,
`test_param_builders.py`, `test_scheduler_mode_resolution.py`, `test_telemetry_models.py`,
`test_telemetry_query_helpers.py`, `test_web_ui_watcher.py`) currently report zero clusters and
need no changes — only verification that they stay clean.

## Goals

- Zero un-annotated duplicate clusters reported for the 25 scoped files.
- Preserve all existing behavior coverage — tests may be restructured, but nothing they verify
  becomes untested.
- Every `dup-ignore` annotation carries a specific, non-generic reason.

## Functional Requirements

- **FR#1** For each of the 59 flagged clusters touching the 25 scoped files, either extract the
  repeated pattern into a shared fixture/helper/parametrized test, or wrap every occurrence in the
  cluster with a `# dup-ignore-start: <reason>` / `# dup-ignore-end` pair.
- **FR#2** For clusters that include a fragment in a file outside the 25-file scope (listed per
  group in Approach below), every occurrence — including the out-of-scope fragment — must be
  resolved, since the checker only suppresses a cluster once *all* its fragments are clear.
- **FR#3** Extraction targets reuse the existing `tests/unit/core/conftest.py` factories/fixtures
  catalog (see its module docstring and directory `CLAUDE.md`) rather than duplicating a second
  copy of an existing helper. Per the "Task split and ordering" section below, no task promotes a
  *new* helper into `conftest.py` — a helper shared within a group's own files stays local to that
  group.

## Acceptance Criteria

- **AC#1** The issue's own verification command produces no output:
  ```bash
  uv run python tools/check_duplicate_code.py 2>&1 | grep -E "tests/unit/core/test_(block_io|blocking_io|bus_dispatch|core_coverage|database_service|event_filter|execution_timeout|log_records|logging_service|loop_watchdog|main|manifest_repository|migration_runner|param_builders|protect_loop|runtime_query|scheduler_mode|telemetry_|unified_execution|web_api_service|web_ui_watcher)"
  ```
- **AC#2** The affected test files still pass:
  ```bash
  uv run pytest tests/unit/core/test_block_io_guard.py tests/unit/core/test_blocking_io_marker_spike.py \
    tests/unit/core/test_bus_dispatch_semaphore.py tests/unit/core/test_core_coverage.py \
    tests/unit/core/test_database_service.py tests/unit/core/test_event_filter.py \
    tests/unit/core/test_execution_timeout.py tests/unit/core/test_log_records.py \
    tests/unit/core/test_log_records_retention.py tests/unit/core/test_logging_service.py \
    tests/unit/core/test_loop_watchdog.py tests/unit/core/test_main.py \
    tests/unit/core/test_manifest_repository.py tests/unit/core/test_migration_runner.py \
    tests/unit/core/test_param_builders.py tests/unit/core/test_protect_loop_monkeypatch.py \
    tests/unit/core/test_runtime_query_service.py tests/unit/core/test_scheduler_mode_resolution.py \
    tests/unit/core/test_telemetry_models.py tests/unit/core/test_telemetry_query_helpers.py \
    tests/unit/core/test_telemetry_repository.py tests/unit/core/test_telemetry_repository_errors.py \
    tests/unit/core/test_unified_execution.py tests/unit/core/test_web_api_service.py \
    tests/unit/core/test_web_ui_watcher.py -v
  ```
  Plus every out-of-scope file touched for a marker-only edit (per group, below) — run its own
  test file too, to prove a comment-only change didn't break collection.
- **AC#3** `prek -a` (ruff + pyright + other hooks) is clean on every changed file.
- **AC#4** Every `dup-ignore-start`/`dup-ignore-file` marker added has a specific reason (not
  "intentional" or "duplicate" alone).

## Approach

### Ground truth, not the issue's own stale line-count

The issue's own suggested verification command was run for real (PMD CPD, full-repo scan, ~3
min). Result: **59 clusters**, which split cleanly into five disjoint file groups — no cluster's
fragments span two of these groups, only within-group or into a genuinely external file (verified
by cross-referencing every cluster's file set against each group's own file list).

| Group | Files | Clusters | Cross-scope files |
|---|---|---:|---|
| **A — loop/blocking-IO** | `test_block_io_guard.py`, `test_loop_watchdog.py`, `test_protect_loop_monkeypatch.py`, `test_execution_timeout.py` | 21 | `tests/integration/test_command_executor.py`, `tests/integration/test_thread_leaked_observability.py` |
| **B — telemetry/DB/migration** | `test_telemetry_repository.py`, `test_telemetry_repository_errors.py`, `test_manifest_repository.py`, `test_runtime_query_service.py`, `test_migration_runner.py`, `test_log_records.py`, `test_log_records_retention.py` | 20 | `tests/unit/test_schema_migration.py`, `tests/unit/test_migration_002.py`, `tests/integration/database/test_database_service_migrations.py`, `src/hassette/core/database_service.py`, `tests/unit/core/conftest.py`, `src/hassette/core/telemetry/repository.py`, `src/hassette/web/mappers.py`, `tests/integration/test_command_executor.py`, `tests/e2e/mock_fixtures.py`, `tests/unit/test_model_types.py` |
| **C — logging_service** | `test_logging_service.py` | 4 | none |
| **D — main/web_api_service** | `test_main.py`, `test_web_api_service.py` | 4 | none |
| **E — unified_execution** | `test_unified_execution.py` | 10 | none |

**Zero-finding files** (verify only, no changes expected): `test_blocking_io_marker_spike.py`,
`test_bus_dispatch_semaphore.py`, `test_core_coverage.py`, `test_database_service.py`,
`test_event_filter.py`, `test_param_builders.py`, `test_scheduler_mode_resolution.py`,
`test_telemetry_models.py`, `test_telemetry_query_helpers.py`, `test_web_ui_watcher.py`. Assign to
Group A/B by directory proximity for the verification pass (Group A covers the loop/IO-adjacent
ones: `test_blocking_io_marker_spike.py`, `test_bus_dispatch_semaphore.py`,
`test_event_filter.py`; Group B covers the DB/telemetry-adjacent ones: `test_core_coverage.py`,
`test_database_service.py`, `test_param_builders.py`, `test_scheduler_mode_resolution.py`,
`test_telemetry_models.py`, `test_telemetry_query_helpers.py`, `test_web_ui_watcher.py`) — each
task's own scoped grep must show these files produce no output, same as the ones with real
clusters.

### Shared external file between Group A and Group B (coordination note)

`tests/integration/test_command_executor.py` appears in both Group A (cluster touching
`test_execution_timeout.py:28-33,40-45` + `test_command_executor.py:242-247`) and Group B (cluster
touching `test_telemetry_repository.py:465-469` + `test_command_executor.py:83-87,311-315,450-455,586-590`).
The two clusters sit at disjoint line ranges in that file, so each task adds its own
`dup-ignore-start/end` pair without touching the other's lines — no functional overlap — but both
task prompts call this out explicitly so neither executor is surprised by an unfamiliar marker
already present in the file when it gets there.

### Extract vs. annotate

Same two-track rule as the issue body and as established by #1633/#1638
(`design/specs/098-dedup-core-service-tests/design.md`):

- **Extract** (default) for mechanical boilerplate with no reader value staying inline, when every
  fragment sits inside the group's own files — e.g. repeated watchdog/timeout assertion shapes
  within a single file. Extract to a helper/fixture local to the file, or shared within the group's
  own files if a cluster pairs two of them. **Never promoted to `tests/unit/core/conftest.py`**
  (see "Task split and ordering").
- **Annotate** (also the default, whenever a fragment crosses outside the group's own files) — when
  duplication is genuinely parallel structure, or when the "duplication" crosses a real module or
  directory boundary that shouldn't be coupled just to satisfy the checker. Two confirmed examples
  from sketch investigation:
  - The repeated "insert a session + listener row to satisfy FK constraints before testing a CHECK
    constraint" setup that appears in both `test_migration_runner.py` (Group B) and
    `tests/unit/test_schema_migration.py` (a different directory, out of scope). Even though the
    pattern itself is mechanical boilerplate that would be a clear Extract case if both occurrences
    lived in Group B's own files, the cross-directory pairing means extraction would require a
    shared helper module spanning two independent test directories — not "local to the file" or
    "shared within the group's own files" per the Extract rule above. Annotate both occurrences
    instead.
  - The cluster pairing `test_manifest_repository.py:47-52` with
    `src/hassette/core/telemetry/repository.py` (the production `manifest_insert_params()` this
    test asserts against) and `src/hassette/web/mappers.py` (an unrelated API-response
    dict-builder with a similarly-shaped-but-different field set) — the test's assertion literal
    is *supposed* to mirror `manifest_insert_params()`'s output exactly, and `mappers.py` shares
    field names by coincidence (same source model, different consumer/field subset). Extracting a
    shared dict-builder between the DB-params layer and the API-response layer would wrongly
    couple two layers this codebase keeps separate.

  Treat any cluster pairing a test assertion with the production function it's asserting against,
  or with an unrelated production module or a different test directory/tier, as an annotate case
  by default — investigate the specific fragments before deciding, don't assume.

Each task instructs the executor to run the checker scoped to its own group (grep filtered to its
filenames plus its group's cross-scope files), inspect the exact current fragments (line numbers
drift as earlier clusters in the same file get resolved — rerun rather than trust stale numbers
after each edit), and make the call per-cluster using the framework above.

### Task split and ordering

Five tasks, one per group, independently landable (disjoint file sets for the four in-scope-only
groups; Group A and B share only comment-only edits at disjoint lines in one external file, per
the coordination note above — not a real write-target conflict). `tests/unit/core/conftest.py` is
out of scope for extraction targets in every task — the one cluster that touches it (Group B,
`test_telemetry_repository.py` + `conftest.py:541-546`) gets resolved as a marker-only or
local-fixture-adjustment edit, not a new shared helper promoted for other groups' benefit, since no
other group's clusters need a `conftest.py`-level fixture.

No task depends on another — all five can run without serialization on a shared write target
(only the disjoint-line-range exception noted above, which orchestrate's task-by-task execution
already avoids since tasks don't literally run concurrently).

## Dependencies and Assumptions

None — self-contained test restructuring with no external dependency and no verification gap. The
PMD CPD checker needs Java 21+ on PATH; already verified present on this machine (this session ran
it successfully).

## Changed Files

- modify: `tests/unit/core/test_block_io_guard.py`
- modify: `tests/unit/core/test_loop_watchdog.py`
- modify: `tests/unit/core/test_protect_loop_monkeypatch.py`
- modify: `tests/unit/core/test_execution_timeout.py`
- modify: `tests/unit/core/test_blocking_io_marker_spike.py` (verify only, likely no change)
- modify: `tests/unit/core/test_bus_dispatch_semaphore.py` (verify only, likely no change)
- modify: `tests/unit/core/test_event_filter.py` (verify only, likely no change)
- modify: `tests/integration/test_command_executor.py` (dup-ignore marker only)
- modify: `tests/integration/test_thread_leaked_observability.py` (dup-ignore marker only)
- modify: `tests/unit/core/test_telemetry_repository.py`
- modify: `tests/unit/core/test_telemetry_repository_errors.py`
- modify: `tests/unit/core/test_manifest_repository.py`
- modify: `tests/unit/core/test_runtime_query_service.py`
- modify: `tests/unit/core/test_migration_runner.py`
- modify: `tests/unit/core/test_log_records.py`
- modify: `tests/unit/core/test_log_records_retention.py`
- modify: `tests/unit/core/test_core_coverage.py` (verify only, likely no change)
- modify: `tests/unit/core/test_database_service.py` (verify only, likely no change)
- modify: `tests/unit/core/test_param_builders.py` (verify only, likely no change)
- modify: `tests/unit/core/test_scheduler_mode_resolution.py` (verify only, likely no change)
- modify: `tests/unit/core/test_telemetry_models.py` (verify only, likely no change)
- modify: `tests/unit/core/test_telemetry_query_helpers.py` (verify only, likely no change)
- modify: `tests/unit/core/test_web_ui_watcher.py` (verify only, likely no change)
- modify: `tests/unit/core/conftest.py` (touch only if Group B's one cluster needs it)
- modify: `tests/unit/test_schema_migration.py` (dup-ignore marker only)
- modify: `tests/unit/test_migration_002.py` (dup-ignore marker only)
- modify: `tests/integration/database/test_database_service_migrations.py` (dup-ignore marker only)
- modify: `src/hassette/core/database_service.py` (dup-ignore marker only)
- modify: `src/hassette/core/telemetry/repository.py` (dup-ignore marker only)
- modify: `src/hassette/web/mappers.py` (dup-ignore marker only)
- modify: `tests/e2e/mock_fixtures.py` (dup-ignore marker only)
- modify: `tests/unit/test_model_types.py` (dup-ignore marker only)
- modify: `tests/unit/core/test_logging_service.py`
- modify: `tests/unit/core/test_main.py`
- modify: `tests/unit/core/test_web_api_service.py`
- modify: `tests/unit/core/test_unified_execution.py`
