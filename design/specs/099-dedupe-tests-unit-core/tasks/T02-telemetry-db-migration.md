---
task_id: "T02"
title: "Deduplicate telemetry repository, manifest, migration, and log-records tests"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "AC#1", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `tests/unit/core/test_telemetry_repository.py`
- modify: `tests/unit/core/test_telemetry_repository_errors.py`
- modify: `tests/unit/core/test_manifest_repository.py`
- modify: `tests/unit/core/test_runtime_query_service.py`
- modify: `tests/unit/core/test_migration_runner.py`
- modify: `tests/unit/core/test_log_records.py`
- modify: `tests/unit/core/test_log_records_retention.py`
- modify: `tests/unit/core/test_core_coverage.py` (verify only — expected no change)
- modify: `tests/unit/core/test_database_service.py` (verify only — expected no change)
- modify: `tests/unit/core/test_param_builders.py` (verify only — expected no change)
- modify: `tests/unit/core/test_scheduler_mode_resolution.py` (verify only — expected no change)
- modify: `tests/unit/core/test_telemetry_models.py` (verify only — expected no change)
- modify: `tests/unit/core/test_telemetry_query_helpers.py` (verify only — expected no change)
- modify: `tests/unit/core/test_web_ui_watcher.py` (verify only — expected no change)
- modify: `tests/unit/core/conftest.py` (touch only if the one cluster below needs it)
- modify: `tests/unit/test_schema_migration.py` (dup-ignore marker only)
- modify: `tests/unit/test_migration_002.py` (dup-ignore marker only)
- modify: `tests/integration/database/test_database_service_migrations.py` (dup-ignore marker only)
- modify: `src/hassette/core/database_service.py` (dup-ignore marker only)
- modify: `src/hassette/core/telemetry/repository.py` (dup-ignore marker only)
- modify: `src/hassette/web/mappers.py` (dup-ignore marker only)
- modify: `tests/e2e/mock_fixtures.py` (dup-ignore marker only)
- modify: `tests/unit/test_model_types.py` (dup-ignore marker only)
- modify: `tests/integration/test_command_executor.py` (dup-ignore marker only, disjoint lines from T01's marker in the same file — see note below)

## Prompt

Resolve every PMD-CPD duplicate-code cluster touching this group's files. Read the design doc at
`design/specs/099-dedupe-tests-unit-core/design.md` (Approach section, Group B row, and the
"Extract vs. annotate" section's worked example about `test_manifest_repository.py` vs.
`src/hassette/core/telemetry/repository.py`/`src/hassette/web/mappers.py`) before starting — it's
the most instructive cluster in this group for the extract/annotate call.

**Important — do not grep for cross-scope filenames.** Every cross-scope file below (the schema
migration tests, `test_database_service_migrations.py`, `database_service.py`,
`telemetry/repository.py`, `mappers.py`, `mock_fixtures.py`, `test_model_types.py`,
`test_command_executor.py`) has plenty of *other* duplicate-code clusters that have nothing to do
with this group (pre-existing, out-of-scope debt — e.g. `test_model_types.py` alone has 5 unrelated
clusters, `test_command_executor.py` has clusters shared with T01 and with files outside this
issue's scope entirely). Grepping for those filenames directly will surface clusters you cannot and
should not resolve. Only the 20 clusters listed below are this task's scope.

1. Run the unfiltered checker once and save it, so you can look up each cluster by line range
   below without re-running the ~3-minute full scan repeatedly:
   ```bash
   uv run python tools/check_duplicate_code.py > /tmp/dup-check-t02.txt 2>&1
   ```
   (The tool's raw output blank-line-separates clusters — `grep` on a filtered pattern will drop
   those blank lines and flatten everything into one list, so read the saved file directly with
   `Read`/`Grep -B/-A`, not a re-filtered grep, when you need to see a cluster's full fragment set.)

2. At sketch time (HEAD `2bf23966`) these were the 20 clusters touching this group's files — line
   numbers will have drifted since, so treat this as a checklist of *what* to resolve, and
   re-derive current line numbers from your saved output each time:
   - **Self-contained** (all fragments within this group's own files, no cross-scope touch needed):
     - `test_telemetry_repository.py` alone — 4 clusters
     - `test_telemetry_repository_errors.py` alone — 1 cluster
     - `test_telemetry_repository.py` + `test_telemetry_repository_errors.py` paired — 2 clusters
     - `test_runtime_query_service.py` alone — 1 cluster
     - `test_log_records_retention.py` alone — 1 cluster
     - `test_manifest_repository.py` alone — 1 cluster
   - **Cross-scope** (require a marker-only touch in the named file too):
     - `test_migration_runner.py` + `tests/unit/test_schema_migration.py` — 3 separate clusters
       (2-fragment, 8-fragment, and 5-fragment)
     - `test_migration_runner.py` + `tests/unit/test_migration_002.py` + `tests/unit/test_schema_migration.py`
       — 1 cluster (9 fragments total)
     - `test_log_records.py` + `tests/integration/database/test_database_service_migrations.py` — 1 cluster
     - `test_log_records.py` + `src/hassette/core/database_service.py` + `tests/integration/database/test_database_service_migrations.py` — 1 cluster (3-way)
     - `test_telemetry_repository.py` + `tests/unit/core/conftest.py` — 1 cluster (the one
       `conftest.py` touch authorized for this task — check its exact current location; at sketch
       time it was around `conftest.py:541-546`)
     - `test_manifest_repository.py` + `src/hassette/core/telemetry/repository.py` + `src/hassette/web/mappers.py`
       — 1 cluster (the worked example in the design doc — this is the clearest "annotate" case in
       the whole group)
     - `test_telemetry_repository.py` + `tests/integration/test_command_executor.py` — 1 cluster
       (disjoint lines from T01's cluster in the same file — see coordination note below)
     - `test_runtime_query_service.py` + `tests/e2e/mock_fixtures.py` + `tests/unit/test_model_types.py`
       — 1 cluster (7 fragments total)

3. For each cluster, inspect the actual fragments and decide extract vs. annotate:
   - **Extract** (default) for mechanical boilerplate, when every fragment sits in this group's own
     files — e.g. the repeated "assert dispatched query params" shapes in the self-contained
     `test_telemetry_repository.py`/`test_manifest_repository.py` clusters listed above. Extract to
     a local helper. Note: the "insert a session + listener row to satisfy FK constraints" setup in
     `test_migration_runner.py` looks like this same kind of boilerplate, but every occurrence of
     it in this task's scope pairs with `tests/unit/test_schema_migration.py` and/or
     `tests/unit/test_migration_002.py` (see the cross-scope list above) — so it belongs under
     Annotate below, not here. Do **not** add a new fixture to
     `tests/unit/core/conftest.py` unless the cluster's own fragment is physically inside
     `conftest.py` (there is exactly one such cluster in this group, around
     `tests/unit/core/conftest.py:541-546` at sketch time — check its current location).
   - **Annotate** when a fragment crosses into `tests/unit/test_schema_migration.py`,
     `tests/unit/test_migration_002.py`, `tests/integration/database/test_database_service_migrations.py`,
     `tests/e2e/mock_fixtures.py`, or `tests/unit/test_model_types.py` (different test tier or
     directory — don't merge test bodies across those boundaries), or into
     `src/hassette/core/database_service.py`, `src/hassette/core/telemetry/repository.py`, or
     `src/hassette/web/mappers.py` (production source — a test asserting against production output
     coincidentally sharing shape with an unrelated production function is not real duplication;
     see the design doc's worked example). Every occurrence in the cluster needs its own
     `# dup-ignore-start: <specific reason>` / `# dup-ignore-end` pair — including the production
     file's occurrence, which is a comment-only addition, never a functional change to that file's
     logic.

4. **Coordination note**: `tests/integration/test_command_executor.py` is also touched by T01
   (a different task, different cluster, disjoint line ranges — T01 handles
   `test_execution_timeout.py`'s pairing at that file; you handle `test_telemetry_repository.py`'s).
   If you see a `dup-ignore` marker already present when you get there, it's T01's — do not remove
   or modify it, only add your own pair around your own cluster's lines.

5. After resolving all clusters, verify with the same narrow grep the design doc's AC#1 uses —
   scoped to only this group's own in-scope filenames (no cross-scope filenames in the pattern).
   A cluster is only suppressed once *every* fragment across the whole repo is resolved, so if you
   forgot to mark a cross-scope fragment, the in-scope side of that same cluster will still show up
   here — this narrow grep going quiet is sufficient proof every cluster (including its cross-scope
   fragments) is resolved:
   ```bash
   uv run python tools/check_duplicate_code.py 2>&1 | grep -E "tests/unit/core/test_(telemetry_repository|telemetry_repository_errors|manifest_repository|runtime_query_service|migration_runner|log_records|log_records_retention|core_coverage|database_service|param_builders|scheduler_mode_resolution|telemetry_models|telemetry_query_helpers|web_ui_watcher)\.py"
   ```
   Confirm no output.

6. Run the affected tests:
   ```bash
   uv run pytest tests/unit/core/test_telemetry_repository.py tests/unit/core/test_telemetry_repository_errors.py \
     tests/unit/core/test_manifest_repository.py tests/unit/core/test_runtime_query_service.py \
     tests/unit/core/test_migration_runner.py tests/unit/core/test_log_records.py \
     tests/unit/core/test_log_records_retention.py tests/unit/core/test_core_coverage.py \
     tests/unit/core/test_database_service.py tests/unit/core/test_param_builders.py \
     tests/unit/core/test_scheduler_mode_resolution.py tests/unit/core/test_telemetry_models.py \
     tests/unit/core/test_telemetry_query_helpers.py tests/unit/core/test_web_ui_watcher.py -v
   uv run pytest tests/unit/test_schema_migration.py tests/unit/test_migration_002.py \
     tests/integration/database/test_database_service_migrations.py tests/e2e/mock_fixtures.py \
     tests/unit/test_model_types.py tests/integration/test_command_executor.py -v
   ```

7. Run `prek -a` on every changed file and fix any lint/type findings.

## Verify

- [ ] FR#1/FR#2: the narrow grep from step 5 produces no output.
- [ ] FR#3: before extracting any new local helper/fixture, check `tests/unit/core/conftest.py`'s existing catalog (module docstring + directory `CLAUDE.md`) for one that already does the job. No new fixture added to `conftest.py` itself, other than resolving the one cluster whose fragment already lives there.
- [ ] AC#1: scoped grep from the design doc's AC#1 (filtered to this group's files) is clean.
- [ ] AC#2: all listed pytest commands pass with 0 failures.
- [ ] AC#3: `prek -a` clean on every changed file.
- [ ] AC#4: every `dup-ignore` marker has a specific, non-generic reason.
