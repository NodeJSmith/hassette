# Design: Handler UI and Telemetry Structural Debt

**Date:** 2026-07-25
**Status:** archived
**Scope-mode:** hold
**Research:** design/research/2026-07-25-handler-telemetry-debt/research.md

## Problem

Oversized files and duplicated patterns across the handler UI and telemetry layers create a readability ceiling that causes AI agents to miss existing utilities and create redundant code instead of reusing what's there. Specifically: parallel stat-cell builders in two frontend components, a 25-prop layout component, several 400-800 line Python modules with flat internal structure, repeated UNION query scaffolding across three SQL methods, and oversized test files mixing unrelated concerns.

## Goals

- All acceptance criteria from issue #1410 ship in one PR on the `1410` branch (the issue's 6 ACs are expanded to 9 in this design to be individually verifiable)
- Measurable file-size reduction: every split file stays well under the 800-line guideline
- HandlerDetailLayout decomposed from a 25-prop monolith into a thin layout shell + 3 focused sub-components
- No behavior changes — all existing tests pass, no visual regressions
- Test coverage added where clearly lacking (2 untested UNION methods)

## User Scenarios

### AI Agent: Implementer

- **Goal:** find and reuse existing utilities when building or modifying handler UI or telemetry code
- **Context:** working in a worktree on a feature that touches handler stats, telemetry queries, or test factories

#### Adding a new stat cell to both handler types

1. **Searches for stat-cell construction logic**
   - Sees: a single shared builder in `stat-cell-builders.ts`, not two parallel functions in separate files
   - Decides: adds one entry to the shared builder
   - Then: both listener and job detail pages render the new cell

#### Adding a new telemetry model

1. **Searches for where telemetry models live**
   - Sees: domain-grouped files (`listener_models.py`, `execution_models.py`, etc.) with clear names
   - Decides: creates the model in the correct domain file based on the model's purpose
   - Then: imports from the specific submodule

### Developer: Reviewer

- **Goal:** review a PR touching handler detail or telemetry code
- **Context:** reading a diff in the GitHub PR review UI

#### Reviewing a handler detail change

1. **Opens the changed files**
   - Sees: HandlerDetailLayout as a thin layout shell; sub-components (`DetailHeader`, `ExecutionSection`, `RegistrationFooter`) each own exactly the props they need
   - Decides: can evaluate the change's scope by reading one sub-component, not tracing 25 flat props
   - Then: approves or requests changes with lower cognitive load

## Functional Requirements

- **FR#1** Stat-cell construction for the shared cells (Failed, Err%, Avg, Timed Out, Cancelled, Thread Leaked, Suppressed, Dropped, and the total/last cells) is defined once and reused by both listener-detail and job-detail
- **FR#2** Domain-specific stat cells (listener: Backpressure Dropped with percentage math; job: Skipped; job: Next/Last branching) remain in their respective detail components
- **FR#3** HandlerDetailLayout is decomposed into a thin layout shell (`testId` + `children` only) and three extracted sub-components: `DetailHeader`, `ExecutionSection`, `RegistrationFooter`
- **FR#4** `DetailHeader` renders the handler name, status badge, kind chip, subtitle, and header actions
- **FR#5** `ExecutionSection` renders the heading, loading spinner, and `ExecutionTable`; derives `hasData` from `records !== undefined` internally
- **FR#6** `RegistrationFooter` owns the `registrationExpanded` toggle state and renders source location, view-in-code button, and collapsible registration source
- **FR#7** `telemetry_models.py` is split into domain-grouped sibling files under `schemas/`, with all importers updated to point at the specific submodule
- **FR#8** `web_helpers.py` is split into domain-grouped sibling files under `test_utils/`, with all importers updated and `test_utils/__init__.py` re-exports preserved
- **FR#9** The three UNION query methods in `execution_queries.py` use a shared helper function for the handler/job UNION arm boilerplate
- **FR#10** `test_telemetry_query_service.py` and `test_telemetry_query_service_misc.py` are reorganized by concern into smaller files
- **FR#11** `app-detail.test.tsx` and `handlers-tab.test.tsx` are split into topic-grouped files with shared test helpers extracted
- **FR#12** Tests exist for `get_per_app_activity_buckets` and `get_per_app_last_errors` (currently untested UNION methods)

## Edge Cases

- **Import breakage**: flat split updates all 31 `telemetry_models` importers and all 16 `web_helpers` importers. Any missed import is a runtime `ImportError`. Pyright + tests catch these.
- **Re-export drift**: `test_utils/__init__.py` re-exports 4 `web_helpers` names (`make_full_snapshot`, `make_job`, `make_manifest`, `make_real_job`). These are load-bearing — some test files import via the package level. Must be updated to point at the new submodule paths.
- **Test coverage gaps from splits**: splitting test files can lose coverage if tests depend on shared setup state. The `app-detail.test.tsx` file uses a local `createWrapper()` that should be migrated to the standard `renderWithAppState()` during the split — the mutable state pattern it protects is not actually used.
- **`check_test_factories.py` registry**: only `make_manifest` is tracked (path: `hassette.test_utils.web_helpers`). Registry entry must be updated to the new submodule path.
- **`schemas/__init__.py` vestigial re-exports**: all 16 telemetry model names are re-exported from `schemas/__init__.py`, but zero consumers use `from hassette.schemas import`. These re-exports should be removed during the split to avoid maintenance burden on a dead surface.
- **GlobalSummary cross-import**: `GlobalSummary` embeds `ListenerGlobalStats` and `JobGlobalStats`. After the split, `summary_models.py` imports from `listener_models.py` and `job_models.py` — one-directional, no cycle risk.

## Acceptance Criteria

- **AC#1** `buildListenerStatsCells` and `buildJobStatsCells` share a common builder for the structurally identical cells; each caller appends only domain-specific cells (maps to FR#1, FR#2)
- **AC#2** `HandlerDetailLayout` accepts only `testId` and `children`; `DetailHeader`, `ExecutionSection`, and `RegistrationFooter` exist as separate components (maps to FR#3, FR#4, FR#5, FR#6)
- **AC#3** `frontend/src/pages/app-detail.test.tsx` and `frontend/src/components/app-detail/handlers-tab.test.tsx` are each split into 3+ topic-grouped files with shared helpers extracted (maps to FR#11)
- **AC#4** `src/hassette/schemas/telemetry_models.py` no longer exists as a single file; its contents are distributed across domain-grouped sibling files in `schemas/`; all importers compile and tests pass (maps to FR#7)
- **AC#5** `src/hassette/test_utils/web_helpers.py` no longer exists as a single file; its contents are distributed across domain-grouped sibling files in `test_utils/`; all importers compile and tests pass (maps to FR#8)
- **AC#6** The three UNION methods in `execution_queries.py` call a shared arm-builder helper; method signatures are unchanged (maps to FR#9)
- **AC#7** `test_telemetry_query_service.py` and `test_telemetry_query_service_misc.py` are reorganized into files grouped by concern; all tests pass (maps to FR#10)
- **AC#8** `get_per_app_activity_buckets` and `get_per_app_last_errors` have dedicated test coverage (maps to FR#12)
- **AC#9** `prek -a` (lint + type check) passes; `ptest -- tests/unit tests/integration -n 4` passes; frontend `npm run build && npm test` passes

## Key Constraints

- No behavior changes — this is purely structural. Any behavior change discovered during implementation (bugs, missing error handling) gets a separate commit per the bug-fix commit convention.
- Do not introduce a package-with-re-exports pattern for the splits — use flat sibling files with updated import paths (user-specified preference).
- Do not touch `tokens.css` or make visual changes.
- `test_telemetry_query_service_aggregates.py` (593 lines) is already well-organized and out of scope — do not reorganize it.

## Dependencies and Assumptions

- Assumes `prek -a` and `ptest` are available on the development machine.
- No external service dependencies — all changes are local code structure.
- The pre-push hook (`check_test_factories.py`) must be updated if `make_manifest`'s import path changes.

## Architecture

### Frontend: Shared stat-cell builder (AC#1, AC#2)

Create `frontend/src/components/app-detail/stat-cell-builders.ts` with a `buildCommonStatCells` function. It takes a normalized input object:

```typescript
interface CommonStatInput {
  totalLabel: string;        // "Calls" | "Runs"
  total: number;
  failed: number;
  avgDurationMs: number | null;
  lastLabel: string;         // relative-time string or "—"
  timedOut: number;
  cancelled: number;
  threadLeaked: number;
  suppressedCount: number;
  droppedCount: number;
}
```

Returns a `DetailStatsCell[]` with the shared cells (total, Failed, Err%, Avg, Last/Next, plus conditional warn/cancel/mute cells for timed_out/cancelled/thread_leaked/suppressed/dropped). Each caller constructs this input from its domain type and appends domain-specific cells:
- Listener appends: Backpressure Dropped (with percentage computation) at the end
- Job: passes `nextRunText` for the Last/Next cell and splices Skipped after Cancelled (not at the end — current order is `Timed Out, Cancelled, Skipped, Thread Leaked, ...`)

### Frontend: Component decomposition (AC#2)

Decompose `HandlerDetailLayout` from a 25-prop monolith into a thin layout shell + 3 extracted sub-components. This addresses the root cause (too many responsibilities) rather than the symptom (too many props).

**HandlerDetailLayout** becomes a layout shell (~15 lines):

```tsx
interface Props {
  testId: string;
  children: ComponentChildren;
}

export function HandlerDetailLayout({ testId, children }: Props) {
  return (
    <div class={styles.wrapper} data-testid={testId}>
      <div class={styles.content}>{children}</div>
    </div>
  );
}
```

**DetailHeader** (`components/app-detail/detail-header.tsx`) — renders the handler name, status badge, kind chip, subtitle, and header actions:

```tsx
interface DetailHeaderProps {
  name: string;
  kindLabel: string;
  statusKind: ChipKind;
  kind: "handler" | "job";
  subtitle?: string | null;
  headerActions?: ComponentChildren;
}
```

**ExecutionSection** (`components/app-detail/execution-section.tsx`) — renders the heading, loading state, and `ExecutionTable`. `records` is `undefined` when data hasn't loaded (shows spinner); an empty array means "loaded but empty" (shows empty table). The `?? []` coercion happens inside the component:

```tsx
interface ExecutionSectionProps {
  heading: string;
  records: ExecutionRecord[] | undefined;
  kind: "handler" | "job";
  tableId: string;
  loading: boolean;
  appKey?: string;
  handlerKind?: HandlerKind;
  handlerId?: number;
  instanceQs?: string;
}
```

**RegistrationFooter** (`components/app-detail/registration-footer.tsx`) — owns the `registrationExpanded` toggle state. Renders source location, view-in-code button, and collapsible registration source:

```tsx
interface RegistrationFooterProps {
  kind: "handler" | "job";
  testId: string;
  sourceLocation?: string | null;
  registrationSource?: string | null;
  onViewCode?: (line?: number) => void;
}
```

The callers (`ListenerDetail`, `JobDetail`) compose the sub-components directly:

```tsx
<HandlerDetailLayout testId={`listener-detail-${listener.listener_id}`}>
  <DetailHeader name={...} statusKind={listenerKind} kindLabel={kindLabel} subtitle={...} />
  <ModifierChips listener={listener} />
  {listenerKind === "err" && <ErrorBanner ... />}
  <DetailStats cells={statsCells} data-testid="handler-stats-row" />
  <ExecutionSection heading="invocations" records={executions} kind="handler" ... />
  <RegistrationFooter sourceLocation={...} registrationSource={...} onViewCode={...} kind="handler" testId={...} />
</HandlerDetailLayout>
```

This eliminates prop-bundling entirely — no intermediate objects, no derived props. Each sub-component receives exactly the props it needs. The layout shell enforces consistent CSS structure and test ID patterns across listener/job detail pages.

**CSS distribution**: `handler-detail-layout.module.css` (125 lines) must be split alongside the component decomposition. Each sub-component gets a co-located `.module.css` with only its classes:

| Class(es) | Destination |
|---|---|
| `.wrapper`, `.content` | stays in `handler-detail-layout.module.css` |
| `.header`, `.headerActions`, `.handlerName`, `.subtitle` | `detail-header.module.css` |
| `.executionsSection`, `.panelHeading` | `execution-section.module.css` |
| `.footer`, `.footerSummary`, `.footerIdentity`, `.footerLabel`, `.footerActions` + media query | `registration-footer.module.css` |
| `.runNow` | stays in `handler-detail-layout.module.css` (used by `RunNowButton` in `job-detail.tsx`) |

Note: `job-detail.tsx` currently imports `layoutStyles` from `handler-detail-layout.module.css` to use `.runNow` and `.subtitle`. After the split, it imports `.runNow` from the layout CSS and `.subtitle` from `detail-header.module.css` (or `.subtitle` moves to a shared location if the cross-import is undesirable).

### Frontend: Test splits (AC#3)

**app-detail.test.tsx** splits into:
- `app-detail.header.test.tsx` — header, subtitles, badges
- `app-detail.tabs.test.tsx` — tab rendering and selection
- `app-detail.instances.test.tsx` — instance switching, URL correction, multi-instance parent view
- `app-detail.test-helpers.ts` — `setupApi()`, `setupMultiInstanceParent()`, shared `vi.mock()` declarations

The existing `createWrapper()` pattern (local wrapper capturing a mutable `AppState`) should be replaced with `renderWithAppState()` + `stateOverrides` during the split. No test actually mutates state between renders — the `uptimeSeconds.value = 120` setup can be passed as a state override. This eliminates the custom wrapper and aligns with the rest of the test suite.

**handlers-tab.test.tsx** splits into:
- `handlers-tab.rendering.test.tsx` — basic rendering, empty states
- `handlers-tab.listener.test.tsx` — listener detail, stats, errors
- `handlers-tab.job.test.tsx` — job detail, stats, Run Now button
- `handlers-tab.navigation.test.tsx` — selection, URL handling, view-in-code
- `handlers-tab.test-helpers.ts` — `renderHandlersTab()`, all `vi.mock()` declarations

The `app-detail.test.tsx` file uses a mutable `AppState` pattern (local `createWrapper` instead of `renderWithAppState`, because tests share state across `beforeEach`). This wrapper must be extracted to the shared helper file, not duplicated.

### Backend: telemetry_models split (AC#4)

Split `src/hassette/schemas/telemetry_models.py` (420 lines, 16 classes) into flat sibling files in `schemas/`:

| New file | Classes | ~Lines |
|---|---|---|
| `schemas/listener_models.py` | ListenerSummary, ListenerGlobalStats, HandlerErrorRecord, SlowHandlerRecord | ~130 |
| `schemas/job_models.py` | JobSummary, JobGlobalStats, JobErrorRecord | ~115 |
| `schemas/execution_models.py` | Execution, ActivityFeedEntry, AppLastError | ~100 |
| `schemas/summary_models.py` | AppHealthSummary, GlobalSummary, SessionRecord, SessionSummary | ~55 |
| `schemas/log_models.py` | LogRecord, BlockingEvent | ~90 |

`summary_models.py` imports `ListenerGlobalStats` from `listener_models` and `JobGlobalStats` from `job_models` — one-directional, no cycles.

Remove the vestigial re-exports of telemetry model names from `schemas/__init__.py` (zero consumers use `from hassette.schemas import`). Keep re-exports for other modules (`app_snapshots`, `domain_models`, `live_counts`, `query_constants`).

Update all 31 importers to point at the specific submodule. The `_BlockingTier` type alias moves to `log_models.py` alongside `BlockingEvent`.

### Backend: web_helpers split (AC#5)

Split `src/hassette/test_utils/web_helpers.py` (626 lines, 20 public factories) into flat sibling files in `test_utils/`:

| New file | Factories | Primary domain |
|---|---|---|
| `test_utils/web_manifest_helpers.py` | `make_full_snapshot`, `make_manifest`, `make_manifest_response`, `make_manifest_list_response` | App manifests |
| `test_utils/web_job_helpers.py` | `make_job`, `make_real_job`, `make_job_summary` | Jobs/scheduler |
| `test_utils/web_response_helpers.py` | `make_system_status_response`, `make_telemetry_status_response`, `make_dashboard_app_grid_entry`, `make_dashboard_app_grid_response`, `make_config_schema_response`, `make_app_health_response`, `make_app_config_response`, `make_app_source_response` | API responses |
| `test_utils/web_telemetry_helpers.py` | `make_activity_feed_entry`, `make_listener_with_summary`, `make_execution`, `make_log_entry_response`, `make_logs_by_execution_response` | Telemetry data |

Private helpers (`_tally_statuses`, `_strip_none`, `_config_to_toml`) move to the file that uses them. `SYNTHETIC_TIMESTAMP` moves to whichever file imports it most, or stays in a shared constants location.

Update `test_utils/__init__.py` re-exports to point at new paths:
- `make_full_snapshot` → `web_manifest_helpers`
- `make_job` → `web_job_helpers`
- `make_manifest` → `web_manifest_helpers`
- `make_real_job` → `web_job_helpers`

Update `check_test_factories.py` registry: `make_manifest` path changes from `hassette.test_utils.web_helpers` to `hassette.test_utils.web_manifest_helpers`.

### Backend: UNION extraction (AC#6)

Add a helper function to `src/hassette/core/telemetry/helpers.py`:

```python
def handler_job_union_arms(
    handler_select: str,
    job_select: str,
    *,
    extra_handler_where: str = "",
    extra_job_where: str = "",
    since: float | None = None,
    source_tier: QuerySourceTier = "app",
    instance_index: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build handler UNION ALL job SQL fragment with merged params."""
```

Each of the 3 UNION methods calls this to get the inner UNION SQL + params, then wraps it:
- `get_app_recent_activity`: `ORDER BY timestamp DESC LIMIT :limit`
- `get_per_app_activity_buckets`: `GROUP BY app_key, bucket_idx` with SUM/CASE
- `get_per_app_last_errors`: `ROW_NUMBER() OVER (PARTITION BY app_key ...)` window

Method signatures stay unchanged. The existing `since_clause`/`source_tier_clause` helpers are called by the new function internally.

### Backend: Telemetry test reorg (AC#7)

Reorganize `test_telemetry_query_service.py` (870 lines) and `test_telemetry_query_service_misc.py` (520 lines) by concern. `test_telemetry_query_service_aggregates.py` (593 lines) stays as-is — it's already thematically cohesive.

Proposed split:
- `test_listener_queries.py` — TestGetListenerSummary and listener-specific tests
- `test_job_queries.py` — TestGetJobSummary, job-specific tests
- `test_execution_queries.py` — TestGetExecutions*, coherence checks, activity feed
- `test_session_queries.py` — session list, health checks
- `test_union_queries.py` — tests for the 3 UNION methods (including new coverage for AC#8)
- `test_query_helpers.py` — TestSourceTierClause and other helper unit tests

All files share the existing `conftest.py` and `helpers.py` (`insert_execution`/`insert_listener`/`insert_job`).

## Implementation Preferences

- Flat sibling files with updated import paths — no package-with-re-exports pattern.
- Frontend test helpers use `.test-helpers.ts` suffix (not `.test.ts` — Vitest would try to run them).
- UNION arm builder goes in `helpers.py` alongside the existing clause builders — no new module.
- `tests/TESTING.md` must be updated with the new `web_helpers` submodule paths and the factory location changes.

## Replacement Targets

| Being replaced | Replaced by | Action |
|---|---|---|
| `schemas/telemetry_models.py` | 5 domain-grouped sibling files in `schemas/` | Delete original after split |
| `test_utils/web_helpers.py` | 4 domain-grouped sibling files in `test_utils/` | Delete original after split |
| `buildListenerStatsCells` in `listener-detail.tsx` | Shared `buildCommonStatCells` + listener-specific append | Remove duplicated logic |
| `buildJobStatsCells` in `job-detail.tsx` | Shared `buildCommonStatCells` + job-specific append | Remove duplicated logic |
| Header rendering in `handler-detail-layout.tsx` | `DetailHeader` sub-component | Extracted to own file |
| Execution section in `handler-detail-layout.tsx` | `ExecutionSection` sub-component | Extracted to own file |
| Registration footer in `handler-detail-layout.tsx` | `RegistrationFooter` sub-component | Extracted to own file; owns toggle state |
| `app-detail.test.tsx` | 3 topic-grouped test files + shared helper | Delete original after split |
| `handlers-tab.test.tsx` | 4 topic-grouped test files + shared helper | Delete original after split |
| `test_telemetry_query_service.py` | 3-4 concern-grouped test files | Delete original after split |
| `test_telemetry_query_service_misc.py` | 2-3 concern-grouped test files | Delete original after split |
| Inline UNION boilerplate in 3 methods | Shared `handler_job_union_arms()` helper | Inline SQL replaced by helper call |
| Vestigial telemetry re-exports in `schemas/__init__.py` | Nothing — zero consumers | Remove dead re-exports |

## Convention Examples

### SQL clause builders

**Source:** `src/hassette/core/telemetry/helpers.py`

```python
def source_tier_clause(source_tier: QuerySourceTier, alias: str) -> tuple[str, dict[str, str]]:
    match source_tier:
        case "all":
            return ("", {})
        case "app" | "framework":
            return (f"AND {alias}.source_tier = :source_tier", {"source_tier": source_tier})
        case _ as unreachable:
            assert_never(unreachable)
```

The UNION arm builder follows this same `(fragment, params)` return pattern.

### DetailStatsCell data-driven rendering

**Source:** `frontend/src/components/shared/detail-stats.tsx`

```typescript
export interface DetailStatsCell {
  label: string;
  value: string | number;
  tone?: StatusKind;
}
```

The shared stat-cell builder produces this type. No new interface needed.

### Flat model hierarchy

**Source:** `src/hassette/schemas/telemetry_models.py`

All 16 classes extend `BaseModel` directly (or `NamedTuple` for `AppLastError`). No cross-model inheritance within the same domain group. This confirms each submodule is self-contained (except `GlobalSummary` → `ListenerGlobalStats`/`JobGlobalStats`, which is one-directional).

### test_utils re-export pattern

**Source:** `src/hassette/test_utils/__init__.py`

```python
from .web_helpers import make_full_snapshot as make_full_snapshot
from .web_helpers import make_job as make_job
from .web_helpers import make_manifest as make_manifest
from .web_helpers import make_real_job as make_real_job
```

These 4 re-exports are load-bearing and must be updated to point at the new submodule paths.

## Alternatives Considered

**Package-with-re-exports (rejected)**: Rename `telemetry_models.py` to a `telemetry_models/` directory with `__init__.py` re-exporting all names. Zero import-path changes for consumers. Rejected because the user prefers explicit imports — flat siblings with updated paths make the actual module structure visible, and AI agents benefit from seeing the specific submodule in each import statement.

**2-3 module split instead of 5 (not chosen)**: Fewer submodules means some consumers import from fewer files, but individual submodules stay larger (~200+ lines) which partially defeats the readability goal. The 5-module split produces ~80-130 line files that are immediately scannable. The cost (5 files needing 3+ submodule imports) is borne entirely by test files and the vestigial `schemas/__init__.py` — both expected patterns.

**Prop reduction via bundling (rejected)**: Reduce HandlerDetailLayout's 25 props to ~15 by deriving redundant props and bundling the execution-table cluster into an `ExecutionTableProps` object. Rejected because it treats the symptom (too many props) without addressing the root cause (too many responsibilities). The bundled object hides complexity behind a type instead of distributing it to focused sub-components.

**No shared stat-cell builder (rejected)**: Keep the parallel builders but extract only the conditional cells. This doesn't address the core duplication — 8 cells with identical label/guard/tone across both files.

## Test Strategy

### Existing Tests to Adapt

- `frontend/src/pages/app-detail.test.tsx` — split into topic-grouped files per AC#3
- `frontend/src/components/app-detail/handlers-tab.test.tsx` — split into topic-grouped files per AC#3
- `tests/integration/telemetry/test_telemetry_query_service.py` — reorganized by concern per AC#7
- `tests/integration/telemetry/test_telemetry_query_service_misc.py` — reorganized by concern per AC#7
- All 31 `telemetry_models` importers (15 source + 16 test files) — import paths updated
- All 16 `web_helpers` importers (1 source + 15 test files) — import paths updated

### New Test Coverage

- **AC#8**: Integration tests for `get_per_app_activity_buckets` — verify bucketed ok/err counts per app_key, edge cases (empty range, single bucket, cross-app). Maps to FR#12.
- **AC#8**: Integration tests for `get_per_app_last_errors` — verify most-recent-error-per-app selection, since-window filtering, source_tier filtering. Maps to FR#12.
- `DetailHeader` — unit test for conditional failing badge rendering (`statusKind === "err"`), kind chip, subtitle display. Maps to FR#4.
- `ExecutionSection` — unit test for loading/spinner vs table branching, `hasData` derivation from `records !== undefined`. Maps to FR#5.
- `RegistrationFooter` — unit test for `registrationExpanded` toggle state, conditional source-location display, view-in-code button visibility. Maps to FR#6.
- `stat-cell-builders` — unit test for shared cell construction, conditional warn/cancel/mute cells, domain-specific cell appending. Maps to FR#1.

### Tests to Remove

No tests to remove. All existing tests are preserved in their split destinations.

## Documentation Updates

- `tests/TESTING.md` — update `web_helpers` factory locations in the factory guide section; update import paths in the "Choosing a Mock Strategy" examples if they reference `web_helpers` directly.
- `.claude/rules/test-conventions.md` — update the "Canonical factories and where they live" section with the new `web_helpers` submodule paths.

## Impact

### Changed Files

**Shared/cross-cutting (higher risk):**
- modify `src/hassette/schemas/__init__.py` — remove vestigial telemetry model re-exports
- modify `src/hassette/test_utils/__init__.py` — update 4 re-export paths
- modify `tools/check_test_factories.py` — update `make_manifest` registry path
- modify `tests/TESTING.md` — update factory location documentation
- modify `.claude/rules/test-conventions.md` — update factory location documentation

**Backend creates:**
- create `src/hassette/schemas/listener_models.py`
- create `src/hassette/schemas/job_models.py`
- create `src/hassette/schemas/execution_models.py`
- create `src/hassette/schemas/summary_models.py`
- create `src/hassette/schemas/log_models.py`
- create `src/hassette/test_utils/web_manifest_helpers.py`
- create `src/hassette/test_utils/web_job_helpers.py`
- create `src/hassette/test_utils/web_response_helpers.py`
- create `src/hassette/test_utils/web_telemetry_helpers.py`
- create `tests/integration/telemetry/test_listener_queries.py`
- create `tests/integration/telemetry/test_job_queries.py`
- create `tests/integration/telemetry/test_execution_queries.py`
- create `tests/integration/telemetry/test_session_queries.py`
- create `tests/integration/telemetry/test_union_queries.py`
- create `tests/integration/telemetry/test_query_helpers.py`

**Backend deletes:**
- delete `src/hassette/schemas/telemetry_models.py`
- delete `src/hassette/test_utils/web_helpers.py`
- delete `tests/integration/telemetry/test_telemetry_query_service.py`
- delete `tests/integration/telemetry/test_telemetry_query_service_misc.py`

**Backend modifies (import path updates):**
- modify `src/hassette/core/telemetry/execution_queries.py` — import paths + UNION extraction
- modify `src/hassette/core/telemetry/helpers.py` — add `handler_job_union_arms()`, update import
- modify `src/hassette/core/telemetry/registration_queries.py` — import paths
- modify `src/hassette/core/telemetry/summary_queries.py` — import paths
- modify `src/hassette/core/telemetry/repository.py` — import paths
- modify `src/hassette/core/command_executor.py` — import paths
- modify `src/hassette/cli/commands/app.py` — import paths
- modify `src/hassette/cli/commands/job.py` — import paths
- modify `src/hassette/cli/commands/listener.py` — import paths
- modify `src/hassette/web/routes/telemetry.py` — import paths
- modify `src/hassette/web/routes/scheduler.py` — import paths
- modify `src/hassette/web/mappers.py` — import paths
- modify `src/hassette/web/utils.py` — import paths
- modify `src/hassette/test_utils/web_mocks.py` — import path for `make_full_snapshot`
- modify ~27 test files — import paths for telemetry models and/or web helpers

**Frontend creates:**
- create `frontend/src/components/app-detail/stat-cell-builders.ts`
- create `frontend/src/components/app-detail/detail-header.tsx`
- create `frontend/src/components/app-detail/detail-header.module.css`
- create `frontend/src/components/app-detail/execution-section.tsx`
- create `frontend/src/components/app-detail/execution-section.module.css`
- create `frontend/src/components/app-detail/registration-footer.tsx`
- create `frontend/src/components/app-detail/registration-footer.module.css`
- create `frontend/src/pages/app-detail.header.test.tsx`
- create `frontend/src/pages/app-detail.tabs.test.tsx`
- create `frontend/src/pages/app-detail.instances.test.tsx`
- create `frontend/src/pages/app-detail.test-helpers.ts`
- create `frontend/src/components/app-detail/handlers-tab.rendering.test.tsx`
- create `frontend/src/components/app-detail/handlers-tab.listener.test.tsx`
- create `frontend/src/components/app-detail/handlers-tab.job.test.tsx`
- create `frontend/src/components/app-detail/handlers-tab.navigation.test.tsx`
- create `frontend/src/components/app-detail/handlers-tab.test-helpers.ts`
- create `frontend/src/components/app-detail/detail-header.test.tsx`
- create `frontend/src/components/app-detail/execution-section.test.tsx`
- create `frontend/src/components/app-detail/registration-footer.test.tsx`
- create `frontend/src/components/app-detail/stat-cell-builders.test.ts`

**Frontend deletes:**
- delete `frontend/src/pages/app-detail.test.tsx`
- delete `frontend/src/components/app-detail/handlers-tab.test.tsx`

**Frontend modifies:**
- modify `frontend/src/components/app-detail/listener-detail.tsx` — use shared stat-cell builder; rewrite to compose sub-components (`DetailHeader`, `ExecutionSection`, `RegistrationFooter`) inside `HandlerDetailLayout`
- modify `frontend/src/components/app-detail/job-detail.tsx` — use shared stat-cell builder; rewrite to compose sub-components inside `HandlerDetailLayout`
- modify `frontend/src/components/app-detail/handler-detail-layout.tsx` — decompose into thin layout shell (`testId` + `children` only); extract rendering to `DetailHeader`, `ExecutionSection`, `RegistrationFooter`
- modify `frontend/src/components/app-detail/handler-detail-layout.module.css` — remove classes moved to sub-component CSS; keep `.wrapper`, `.content`, `.runNow`

### Behavioral Invariants

- All existing handler detail rendering (listener and job) must produce identical visual output
- All telemetry query method signatures and return types are unchanged
- All web API response shapes are unchanged
- The 4 `test_utils` package-level re-exports (`make_full_snapshot`, `make_job`, `make_manifest`, `make_real_job`) continue to work from `from hassette.test_utils import`

### Blast Radius

- **31 files** get import-path updates for `telemetry_models` consumers (15 source + 16 test)
- **16 files** get import-path updates for `web_helpers` consumers (1 source + 15 test)
- **Frontend build** — TypeScript compiler catches any broken imports
- **Pre-commit hooks** — `check_test_factories.py` needs a registry update; `check_module_boundaries.py` layer rules are satisfied by all proposed file locations (new files stay within their existing layer)
- No downstream services, no API consumers, no CLI behavior changes

## Open Questions

None — all blind spots investigated and resolved.
