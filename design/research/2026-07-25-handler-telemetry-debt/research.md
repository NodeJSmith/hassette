---
proposal: "Reduce handler UI and telemetry structural debt across 6 acceptance criteria spanning frontend components, backend models, query scaffolding, and test organization."
date: 2026-07-25
status: Draft
flexibility: Exploring
motivation: "Readability ceiling, review friction, prep for new work, completing the clean-code sweep"
constraints: "All 6 ACs must ship. As few PRs as possible. User will fix forward, not revert."
non-goals: "None stated"
depth: deep
---

# Research Brief: Issue #1410 -- Handler UI and Telemetry Structural Debt

**Initiated by**: Issue #1410 requesting consolidation of parallel stat-cell builders, prop reduction, file splits across frontend and backend, UNION query extraction, and test reorganization.

## Context

### What prompted this

Six items surfaced during clean-code sweeps: duplicated stat-cell construction logic in two frontend components, a 25-prop layout component, oversized test files, a catch-all backend model module, a catch-all test factory module, repeated UNION query scaffolding, and sprawling telemetry test files. All six contribute to review friction and a readability ceiling that slows new work.

### Current state

**Frontend stat cells (AC1)**: `buildListenerStatsCells` (listener-detail.tsx:41-70) and `buildJobStatsCells` (job-detail.tsx:71-94) each construct a `DetailStatsCell[]` array. Eight stat cells use identical label/guard/tone patterns across both files (Failed, Err%, Avg, Timed Out, Cancelled, Thread Leaked, Suppressed, Dropped). Two more differ only in label (Calls vs Runs). Each file has one unique cell (listener: Backpressure Dropped with percentage math; job: Skipped). The Last/Next timing cell differs structurally -- listeners always show "Last" unconditionally, while jobs branch between "Next" (from next_run/fire_at) and "Last" as a fallback. Both builders return `DetailStatsCell[]` consumed by `HandlerDetailLayout.statsCells`.

**HandlerDetailLayout (AC2)**: 194 lines, 25 props (not 26 as stated in the issue -- the interface at lines 26-52 has exactly 25 entries). The execution-table group alone accounts for 10 props (`executionHeading`, `executionRecords`, `executionKind`, `executionTableId`, `executionLoading`, `executionHasData`, `appKey`, `handlerKind`, `handlerId`, `instanceQs`). `executionKind` is redundant with `testIdPrefix` -- both callers always set them to the same `"handler" | "job"` value. `executionHasData` is always derived from `executions !== undefined` at both call sites. The component serves five roles: header/identity rendering, error banner, stats row, execution table, and a collapsible "Registration" footer with its own local toggle state.

**Frontend test files (AC3)**: `app-detail.test.tsx` (694 lines) has one flat `describe` with ~30 `it` blocks and no nested describes. `handlers-tab.test.tsx` (725 lines) has one flat `describe` with ~55 `it` blocks plus a single nested `describe("job detail: Run Now button")`. Both rely on shared utilities in `frontend/src/test/` (factories.ts, mock-wouter.ts, render-helpers.tsx, server.ts, query-test-utils.tsx). No frontend file-size linter exists -- `check_file_size.py` only scans Python.

**telemetry_models.py (AC4)**: 420 lines, 16 model classes. Flat hierarchy -- every class extends `BaseModel` directly (or `NamedTuple` for `AppLastError`). The only composition is `GlobalSummary` embedding `ListenerGlobalStats` + `JobGlobalStats`. 15 `src/` importers and 16 test importers, all using fully-qualified paths (`from hassette.schemas.telemetry_models import X`). Zero consumers use the package-level `from hassette.schemas import X` re-export.

**web_helpers.py (AC4)**: 627 lines, 20 public factory functions + 3 private helpers (not 24 as stated). Only 4 are re-exported at the `test_utils` package level (`make_full_snapshot`, `make_job`, `make_manifest`, `make_real_job`). Only `make_manifest` is tracked in `check_test_factories.py`'s registry. 15 test file consumers, all using direct imports from `hassette.test_utils.web_helpers`.

**execution_queries.py (AC5)**: 356 lines, `ExecutionQueriesMixin` class with 7 methods. Three use UNION: `get_app_recent_activity` (95-194), `get_per_app_activity_buckets` (196-266), `get_per_app_last_errors` (268-316). All three follow the same structural pattern: handler arm (`FROM executions e_h JOIN listeners l ON l.id = e_h.listener_id WHERE e_h.kind = 'handler'`) UNION ALL job arm (`FROM executions e_j JOIN scheduled_jobs sj ON sj.id = e_j.job_id WHERE e_j.kind = 'job'`). What varies: the SELECT column list and the outer wrapping (ORDER+LIMIT, GROUP BY+SUM, or ROW_NUMBER window). The `since_clause`/`source_tier_clause` helpers in `helpers.py` already parameterize per-arm predicate fragments; the join/kind boilerplate is what's actually repeated 3x. Only one direct importer: `query_service.py`.

**Telemetry test files (AC6)**: `test_telemetry_query_service.py` (870 lines, 8 test classes covering non-UNION methods), `test_telemetry_query_service_misc.py` (521 lines, 6 classes -- grab-bag of helper unit tests, infra tests, and the only UNION method tests for `get_app_recent_activity`). A third related file exists: `test_telemetry_query_service_aggregates.py`. Shared infrastructure: `conftest.py` (64 lines) + `helpers.py` with `insert_execution`/`insert_listener`/`insert_job` utilities. Notable gap: `get_per_app_activity_buckets` and `get_per_app_last_errors` (2 of 3 UNION methods) appear to have no dedicated tests.

### Key constraints

**Pre-commit hooks**: `check_test_factories.py` (name-based shadowing guard -- `make_manifest` is the only `web_helpers` function in its registry), `check_module_boundaries.py` (layer DAG enforcement -- `test_utils` isolation, `web-no-core`), `check_file_size.py` (800-line cap, non-blocking warning). `check_lazy_imports.py` bans function-level imports. `check_spec_tokens.py` bans leaked planning tokens (`AC#`, `WP#`) in source.

**Re-export surfaces**: `schemas/__init__.py` re-exports all 16 telemetry model names (vestigial -- zero consumers use it). `test_utils/__init__.py` re-exports 4 `web_helpers` names (load-bearing -- some test files import via the package level). `core/telemetry/__init__.py` is empty.

**Import direction**: `web_helpers.py` imports from `telemetry_models.py` (`ActivityFeedEntry`, `Execution`, `JobSummary`). `execution_queries.py` imports from `telemetry_models.py` (`ActivityFeedEntry`, `AppLastError`, `Execution`). Both are one-directional, no cycles.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| AC1: Stat-cell consolidation | 3 files (shared component + 2 callers) | Low | Low -- well-understood pattern, DetailStatsCell interface unchanged |
| AC2: Prop reduction | 3 files (layout + 2 callers) | Low | Low -- only 2 consumers, both in the same directory |
| AC3: Frontend test splits | 2 files split into ~4-6 files + possible shared setup module | Medium | Low -- no runtime impact, pure test organization |
| AC4a: telemetry_models split | 1 file -> 3-5 submodules, ~15 src importers + 16 test importers need path updates, schemas/__init__.py re-export update | Medium | Medium -- wide import blast radius, but mechanical |
| AC4b: web_helpers split | 1 file -> 3-4 submodules, ~15 test importers need path updates, test_utils/__init__.py re-export update, check_test_factories.py registry update, tests/TESTING.md update | Medium | Low -- consumers are all test files, no runtime code |
| AC5: UNION extraction | 1 file internal refactor (execution_queries.py) | Low | Low -- single importer, internal-only change, method signatures unchanged |
| AC6: Telemetry test reorg | 2 files -> 4-5 files | Low | Low -- pure test organization |

### What already supports this

- **Flat model hierarchy**: All 16 telemetry models are independent (no cross-model inheritance), so splitting into submodules creates no circular import risk within `schemas/`.
- **DetailStatsCell interface**: The shared `DetailStatsCell` type and `DetailStats` component already exist in `components/shared/detail-stats.tsx`. The stat-cell builders already return this type -- consolidation is about extracting the shared construction logic, not defining new types.
- **Existing `helpers.py` in telemetry**: `since_clause` and `source_tier_clause` already parameterize per-arm predicates with an alias parameter. The UNION arm builder is a natural extension of this pattern.
- **Zero package-level import consumers for schemas**: No production or test code uses `from hassette.schemas import X`, so the `__init__.py` re-export update is a formality, not a migration.
- **Empty `core/telemetry/__init__.py`**: No re-exports to maintain for the UNION extraction.
- **Frontend `@/` path alias**: Moving/splitting frontend files under `src/` requires no alias configuration changes.

### What works against this

- **Wide import blast radius for telemetry_models.py split**: 15 src files + 16 test files import from the current single-module path. Every one needs its import statement updated. This is mechanical but produces a large diff.
- **No existing subpackage pattern in `schemas/`**: The directory is flat (5 files). Introducing a subpackage (e.g., `telemetry_models/`) would be the first sub-package in this directory, though it follows the pattern already used in `core/telemetry/`.
- **Frontend test setup coupling**: Both oversized test files depend heavily on `vi.mock()` calls for module stubs (wouter, handlers-tab, code-tab, config-tab, etc.). These mock declarations must be duplicated or extracted to shared setup modules when splitting. `app-detail.test.tsx` explicitly comments (lines 100-101) that it uses a local `createWrapper` instead of `renderWithAppState` because "tests share a mutable AppState across beforeEach setup" -- this coupling makes naive splitting harder.
- **AC2-AC3 ordering**: Splitting `handlers-tab.test.tsx` before reducing `HandlerDetailLayout`'s props means the new test files immediately face API churn. AC2 should land before AC3.

## Options Evaluated

### Option A: Two PRs -- Backend + Frontend

Split by language boundary. Each PR is self-contained and independently reviewable.

**PR 1: Backend (AC4 + AC5 + AC6)**

Contains all Python changes:
1. Split `telemetry_models.py` into domain submodules (e.g., `listener_models.py`, `job_models.py`, `execution_models.py`, `session_models.py`, `log_models.py`, `blocking_models.py` -- or a telemetry_models package with submodules). Update all 31 importers.
2. Split `web_helpers.py` into domain-grouped factory modules (e.g., `web_helpers/manifest_factories.py`, `web_helpers/job_factories.py`, `web_helpers/execution_factories.py`, `web_helpers/system_factories.py`, `web_helpers/log_factories.py`). Update `test_utils/__init__.py` re-exports, `check_test_factories.py` registry, `tests/TESTING.md`.
3. Extract UNION arm builder in `execution_queries.py` -- a helper function like `_handler_job_union(select_cols_h, select_cols_j, extra_where_h, extra_where_j, *, since, source_tier, alias_h, alias_j)` that returns the `UNION ALL` SQL fragment + merged params. Each of the 3 methods calls this helper and wraps the result with its own outer query (ORDER+LIMIT, GROUP BY, or ROW_NUMBER).
4. Reorganize telemetry test files: split `test_telemetry_query_service.py` by domain (listener summary tests, job summary tests, misc queries), split `test_telemetry_query_service_misc.py` by concern (UNION/activity tests, infra/helper tests).

Internal ordering within this PR:
- `telemetry_models.py` split first (or atomic with `web_helpers.py` split, since `web_helpers` imports from `telemetry_models`)
- `execution_queries.py` UNION extraction is independent (no shared files with the model splits)
- Test reorg last (tests must track final import paths)

**PR 2: Frontend (AC1 + AC2 + AC3)**

Contains all TypeScript/CSS changes:
1. Extract shared stat-cell builder utilities (see AC1 analysis below for the specific approach).
2. Reduce `HandlerDetailLayout` props by consolidating redundant/derivable props and grouping the execution-table cluster.
3. Split oversized test files along natural topic boundaries.

Internal ordering within this PR:
- AC1 (stat-cell consolidation) and AC2 (prop reduction) first -- they change the component APIs
- AC3 (test splits) last -- tests must target final component interfaces

**Pros**:
- Clean language boundary -- backend and frontend reviewers can work independently
- Each PR has a coherent theme (structural cleanup for one layer)
- Natural internal ordering within each PR
- Two PRs is the minimum that respects the AC2-before-AC3 ordering constraint

**Cons**:
- Backend PR has a large diff due to 31 import-path updates for telemetry_models
- Both PRs are still substantial in size

**Effort estimate**: Medium -- mechanical import updates are the bulk of the work, not design decisions

**Dependencies**: None new. Both PRs use existing tools and patterns.

### Option B: Single PR

Everything in one PR. Maximum code co-location for review, minimum PR overhead.

**How it works**: Same implementation as Option A, just combined. Commit sequence within the PR would be: (1) telemetry_models split, (2) web_helpers split, (3) UNION extraction, (4) backend test reorg, (5) stat-cell consolidation, (6) prop reduction, (7) frontend test splits.

**Pros**:
- Absolute minimum PR count (1)
- No cross-PR dependency coordination
- User stated revert size is not a concern

**Cons**:
- Very large diff mixing two languages and six concerns
- A single reviewer comment on one AC blocks the entire PR
- Git blame becomes less useful -- all six changes share a merge date

**Effort estimate**: Same as Option A, just combined

### Option C: Three PRs -- Backend Models, Backend Queries, Frontend

Finer-grained than Option A, separating the model/helper splits (high import churn) from the query refactor (zero import churn).

**PR 1**: AC4 (telemetry_models + web_helpers splits) -- pure import-path mechanical changes
**PR 2**: AC5 + AC6 (UNION extraction + test reorg) -- behavioral refactor + test cleanup
**PR 3**: AC1 + AC2 + AC3 (all frontend) -- component consolidation + test splits

**Pros**:
- PR 1 is purely mechanical (import paths), easy to review despite large diff
- PR 2 is the only one with behavioral risk (query refactor), isolated for focused review
- PR 3 is self-contained frontend work

**Cons**:
- Three PRs when the user asked for "as few as possible"
- PR 2 depends on PR 1 (execution_queries.py imports from telemetry_models)

**Effort estimate**: Same total effort, more PR overhead

## Detailed AC Analysis

### AC1: Stat-cell consolidation approach

The shared cells between listener and job builders share a common shape but differ in field names (`total_invocations` vs `total_executions`, `last_invoked_at` vs `last_executed_at`). A single shared component is feasible if callers pass a normalized input.

**Recommended approach**: A shared `buildCommonStatCells(data: CommonStatInput)` function that takes a normalized object:

```typescript
interface CommonStatInput {
  totalLabel: string;         // "Calls" | "Runs"
  total: number;
  failed: number;
  avgDurationMs: number | null;
  lastLabel: string;          // relative-time string or dash
  // Conditional cells -- only included when > 0
  timedOut: number;
  cancelled: number;
  threadLeaked: number;
  suppressedCount: number;
  droppedCount: number;
}
```

Each caller (listener-detail, job-detail) constructs this input from its domain type and appends domain-specific cells after calling the shared builder:
- Listener appends: Backpressure Dropped (with percentage computation)
- Job appends: Skipped; and replaces the Last cell with Next/Last branching before passing to the builder (or handles it as a post-step)

This avoids a single uber-component that conditionally handles all domain logic. The shared function lives in a new file (e.g., `stat-cell-builders.ts`) alongside `detail-stats.tsx` in `components/shared/`, or co-located in the `app-detail/` directory.

### AC2: Prop reduction approach

The 25 props fall into 5 natural groups:

| Group | Props | Count | Consolidation |
|-------|-------|-------|--------------|
| Kind/identity | `testId`, `testIdPrefix`, `kindLabel`, `statusKind`, `name`, `subtitle`, `registrationSource` | 7 | Merge `testIdPrefix` and `executionKind` into a single `kind: "handler" \| "job"` prop. Derive `testId` patterns from `kind` + an `id` prop. |
| Render slots | `chips`, `extras`, `headerActions` | 3 | Keep as-is (ComponentChildren slots are inherently simple) |
| Source/code | `sourceLocation`, `onViewCode` | 2 | Keep as-is |
| Error | `error` | 1 | Keep as-is (already a grouped `ErrorInfo` object) |
| Stats | `statsCells`, `statsTestId` | 2 | Derive `statsTestId` from `kind` (e.g., `${kind}-stats`), collapsing to 1 prop |
| Execution table | `executionHeading`, `executionRecords`, `executionKind`, `executionTableId`, `executionLoading`, `executionHasData`, `appKey`, `handlerKind`, `handlerId`, `instanceQs` | 10 | Bundle into `execution: ExecutionTableProps` object. Drop `executionKind` (use `kind`). Drop `executionHasData` (derive from `executionRecords !== undefined` inside the layout). |

Net reduction: 25 -> ~19-20 props (merge testIdPrefix/executionKind, derive statsTestId, bundle execution table, drop executionHasData). The execution-table bundling alone removes 7-8 individual props from the top-level interface.

### AC4: Model split groupings

Based on the 16 classes' domain relationships and consumer patterns:

| Submodule | Classes | Line count | Primary consumers |
|-----------|---------|-----------|-------------------|
| `listener_models.py` | `ListenerSummary`, `ListenerGlobalStats`, `HandlerErrorRecord`, `SlowHandlerRecord` | ~130 lines | registration_queries, web/mappers, web/routes/telemetry |
| `job_models.py` | `JobSummary`, `JobGlobalStats`, `JobErrorRecord` | ~115 lines | registration_queries, web/routes/scheduler, cli/commands/job |
| `execution_models.py` | `Execution`, `ActivityFeedEntry`, `AppLastError` | ~100 lines | execution_queries, cli/commands/app, web_helpers |
| `summary_models.py` | `AppHealthSummary`, `GlobalSummary`, `SessionRecord`, `SessionSummary` | ~55 lines | summary_queries, helpers |
| `log_models.py` | `LogRecord`, `BlockingEvent` | ~90 lines | repository, command_executor |

`GlobalSummary` embeds `ListenerGlobalStats` and `JobGlobalStats`, so it imports from `listener_models` and `job_models` -- one-directional, no cycle risk since neither of those imports from `summary_models`. All other submodules are fully independent.

**Migration strategy**: Keep the module path `hassette.schemas.telemetry_models` as a package (rename file to directory with `__init__.py` that re-exports all 16 names). This makes the split **zero-cost for all 31 importers** -- no import path changes needed. The `__init__.py` simply re-exports from the submodules. This is the cheapest migration path.

### AC5: UNION arm builder design

The right abstraction is a **helper function that generates the two-arm UNION fragment**, not a full query builder or template method pattern. The three UNION methods differ only in:
1. SELECT column list per arm
2. Extra WHERE predicates per arm
3. Outer wrapping applied to the combined result

A function like:

```python
def _handler_job_union_arms(
    handler_select: str,
    job_select: str,
    *,
    extra_handler_where: str = "",
    extra_job_where: str = "",
    since: float | None = None,
    source_tier: QuerySourceTier = "app",
) -> tuple[str, dict[str, Any]]:
    """Build handler UNION ALL job SQL fragment with merged params."""
```

Each method calls this to get the inner UNION, then wraps it:
- `get_app_recent_activity`: `SELECT ... FROM ({union}) combined ORDER BY timestamp DESC LIMIT :limit`
- `get_per_app_activity_buckets`: `SELECT ... SUM(CASE...) FROM ({union}) combined WHERE bucket_idx ... GROUP BY ...`
- `get_per_app_last_errors`: `SELECT ... FROM (SELECT ... ROW_NUMBER() ... FROM ({union}) combined_inner) WHERE rn = 1`

This preserves each method's readability while eliminating the repeated join/kind boilerplate. The helper lives in `helpers.py` alongside the existing `since_clause`/`source_tier_clause` helpers.

## Concerns

### Technical risks

- **telemetry_models package approach**: Making `telemetry_models` a directory/package preserves all import paths, but if any importer uses `importlib` or string-based imports referencing the `.py` extension (unlikely but worth a grep), that would break. A quick `grep -rn "telemetry_models.py" src/ tests/` should confirm zero such references.
- **UNION arm builder correctness**: The builder must handle the `since`/`source_tier` parameter deduplication pattern correctly (calling clause helpers twice with different aliases but discarding the second params dict since bind names are identical). This is already documented in comments at lines 119-123 of `execution_queries.py` but could be a source of subtle bugs if the builder doesn't replicate the convention exactly.

### Complexity risks

- **Frontend shared stat-cell builder scope creep**: The listener's Backpressure Dropped cell includes percentage arithmetic and the job's Next/Last cell includes branching logic. If the shared builder tries to absorb these domain-specific cells, it becomes a worse abstraction than the current parallel builders. The builder must handle only the genuinely shared cells, with callers appending domain-specific ones.

### Maintenance risks

- **test_utils/web_helpers split maintenance**: 20 factories split across 4-5 files means new factories need to be placed in the right submodule. Without a naming convention or directory-level README, contributors may add to the wrong file. Recommend a brief comment at the top of each submodule stating its domain scope.

## Open Questions

- [ ] The issue states "26 props" for HandlerDetailLayout but the actual count is 25. Does the issue include the `ErrorInfo` sub-interface's fields in its count, or was it a miscount? (Minor -- does not affect the work.)
- [ ] The issue states "24 factory functions" for web_helpers.py but the actual count is 20 public + 3 private = 23 definitions. (Minor -- does not affect the work.)
- [ ] `get_per_app_activity_buckets` and `get_per_app_last_errors` (2 of 3 UNION methods) appear to have no dedicated test coverage. Should AC6 include writing tests for these, or is that out of scope for a structural-debt issue?
- [ ] For AC4a (telemetry_models split): should this use the zero-migration-cost package approach (directory with `__init__.py` re-exports), or should all 31 importers be updated to point at specific submodules for explicitness? The package approach is cheaper but hides the actual module structure behind re-exports.

## Recommendation

All six ACs are feasible and low-to-medium effort. The codebase is well-structured for these splits -- flat model hierarchies, clear domain boundaries, and existing helper patterns to extend.

**Recommended PR grouping: Option A (2 PRs)**. This is the minimum PR count that respects the AC2-before-AC3 ordering within the frontend. The backend and frontend streams have zero file overlap and can be developed and reviewed in parallel.

**For AC4a, use the package approach** (rename `telemetry_models.py` to `telemetry_models/__init__.py` that re-exports from submodules). This eliminates all 31 import-path updates, making the diff dramatically smaller and the review focused on the actual structural improvement rather than mechanical churn. The same approach works for `web_helpers.py` -- rename to a package, re-export the 20 public names from `__init__.py`.

**For AC5, the arm-builder helper is the right abstraction level**. A full query-builder class or template-method pattern would be over-engineering for exactly 2 fixed arm shapes (handler/job) that will not grow.

**For AC3, defer test splits to after AC1+AC2** within the same PR. The test files exercise the components being changed -- splitting them against stale APIs wastes effort.

### Suggested next steps

1. Write a design doc via `/mine-define` covering the package-vs-flat-split decision for AC4 and the shared stat-cell interface for AC1
2. Implement backend PR first (AC4 + AC5 + AC6) -- it has the wider blast radius and benefits from landing early
3. Implement frontend PR second (AC1 + AC2 + AC3) -- smaller blast radius, benefits from stable backend models

### Dependency graph

```
AC4a (telemetry_models split) ──┐
                                ├──> AC4b (web_helpers split) ──> AC6 (test reorg)
AC5 (UNION extraction) ────────┘     (imports from telemetry_models)

AC1 (stat-cell consolidation) ──┐
                                ├──> AC3 (frontend test splits)
AC2 (prop reduction) ──────────┘

Backend stream and frontend stream are fully independent.
```
