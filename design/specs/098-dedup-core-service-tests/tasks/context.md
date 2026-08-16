# Context: Deduplicate tests/unit/core service tests

## Problem & Motivation

`tools/check_duplicate_code.py` (PMD CPD clone detector) fails on `main` today as known, tracked baseline debt (`continue-on-error: true` in CI). Issue #1616 (split from #1561) scopes cleanup to 16 named files in `tests/unit/core/` — bus service, command executor, scheduler service, and service watcher tests. A ground-truth run of the checker on 2026-08-16 confirms 35 flagged clusters touch these files.

## Key Decisions

1. Four independently-landable task groups, split by filename prefix (`command_executor`, `bus_service`, `scheduler_service`, `service_watcher`) — matches the issue's own suggested grep filter and keeps each task's Target Files disjoint from the others.
2. Two-track resolution per cluster, per the issue's own rule:
   - **Extract** (default): pull mechanical boilerplate into a shared helper/fixture, kept local to the file(s) within your own task's group. `tests/unit/core/conftest.py` already has a substantial factory catalog (`make_executor`, `make_bus_service`, `make_scheduler_service`, `make_watcher`, `make_mock_cmd_listener`, `make_execute_job_cmd`, etc — see its module docstring and this directory's `CLAUDE.md`) — check there before adding a new one, and reuse an existing factory if it already covers the shape. **Do not add a new fixture/helper to `conftest.py`.** It's a single shared write target read by all four groups running in parallel; none of the 35 flagged clusters actually pair files across two different groups, so no cluster genuinely needs a `conftest.py`-level helper. If you find one that seems to, stop and flag it rather than editing the file — that would be a real cross-group dependency the sketch didn't anticipate.
   - **Annotate**: wrap every occurrence with `# dup-ignore-start: <specific reason>` / `# dup-ignore-end` when the duplication is genuinely parallel structure that reads more clearly left alone (e.g. mirrored bus-vs-scheduler test classes covering two different command types).
3. 5 of the 35 clusters include a fragment in a file **outside** the 16-file scope (`tests/integration/test_command_executor_error_handler.py`, `tests/unit/test_source_tier_models.py`, `tests/unit/bus/test_invocation.py`, `src/hassette/test_utils/helpers.py`). The checker only suppresses a cluster once *every* fragment in it is resolved — so these clusters require touching the named out-of-scope file too. Recommended treatment for all 5: annotate both sides (comment-only edit to the out-of-scope file, no functional change) rather than merging test bodies across a unit/integration or subsystem boundary. See design.md's "Approach" section for the exact cluster list.
4. Line numbers in the cluster references below are a **snapshot as of 2026-08-16** — they will drift as earlier clusters in the same file get resolved. Always re-run the scoped grep command below to see current state before deciding a cluster is unresolved; don't trust stale line numbers past the first edit in a file.

## Constraints

- Do not modify test *behavior* — every existing assertion must still be exercised somewhere. Restructuring (extracting into a fixture, parametrizing) is fine; deleting coverage is not.
- Do not touch files outside your task's Target Files list, except the specific out-of-scope file named for a cross-scope cluster (comment-only `dup-ignore` marker addition, nothing else in that file).
- Do not invent a new shared factory if an existing one in `tests/unit/core/conftest.py` already covers the shape — check the file and its directory `CLAUDE.md` first.
- Every `dup-ignore-start`/`dup-ignore-file` marker needs a specific reason string — "intentional" or "duplicate" alone is not acceptable and the checker's `main()` doesn't enforce content quality, only presence, so this is a human/reviewer check.
- `dup-ignore-start`/`dup-ignore-end` must be balanced — an unclosed marker is a checker error (`IgnoreMarkerError`), not a silent no-op.

## Verification command (shared across all tasks)

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep -E "tests/unit/core/test_(bus_service|command_executor|scheduler_service|service_watcher)"
```

Empty output = pass. The full scan takes ~2-3 minutes (PMD CPD over the whole repo — there is no per-file mode). Run it once per task, after all clusters in that task's scope are resolved, not per-cluster.
