---
proposal: "Audit exhaustive status handling across hassette and establish compile-time enforcement to prevent new enum variants from silently slipping through."
date: 2026-08-21
status: Draft
flexibility: Exploring
motivation: "PR #1605 introduced ManifestStatus.DEGRADED and post-merge review found 5 places that didn't handle it. Both find current gaps AND prevent recurrence."
constraints: "None stated"
non-goals: "None stated"
depth: deep
---

# Research Brief: Exhaustive Status Handling Audit

**Initiated by**: Audit all status enum consumers for exhaustiveness gaps, research compile-time enforcement mechanisms, and investigate WS event emission coverage.

## Context

### What prompted this

PR #1605 added `degraded` as a new `ManifestStatus` variant (meaning "at least one instance running, at least one failed"). Post-merge review discovered 5 frontend locations that silently ignored the new variant. The concern is twofold: (1) are there more gaps right now, and (2) how do we make this class of bug impossible going forward.

### Current state

The codebase has 15 `StrEnum` types in Python (`src/hassette/types/enums.py` and scattered across core modules) and corresponding string literal union types generated into the TypeScript frontend via the OpenAPI pipeline. The highest-risk enums are:

- **ResourceStatus** (9 variants) -- the lifecycle state of any `Resource`/`Service`/`App`
- **ManifestStatus** (6 variants) -- the aggregate app-level status derived from instance states
- **ExecutionStatus** (5 variants) -- the outcome of a handler/job invocation
- **ConnectionState** (3 variants) -- the hassette-to-HA WebSocket link
- **StateCacheFreshness** (3 variants) -- whether the entity state cache is current

The Python backend uses pyright for type checking with `reportMatchNotExhaustive: "error"` already enabled. The TypeScript frontend uses strict mode with `noFallthroughCasesInSwitch: true`. Despite this, the enforcement mechanisms are largely inert because the code doesn't use the patterns they check -- Python has no `match` statements or `assert_never` calls on these enums, and TypeScript widens all status values to `string` before they reach branch sites.

### Key constraints

Solo developer. Migration cost matters -- the enforcement mechanism needs to be adoptable incrementally, not all-or-nothing.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Frontend type narrowing (`status.ts`, `status-priority.ts`) | 2 files | Low | Low -- mechanical retyping |
| Frontend ESLint rule addition | 1 file (`eslint.config.js`) | Low | None |
| Frontend bug fixes (Gaps 1-2 below) | 3 files | Low | Low -- isolated components |
| Python `assert_never` convention (future code) | 0 files today | Low | None -- convention, not retrofit |
| WS connectivity gap | 2-3 files | Medium | Low -- additive |
| StateCacheFreshness observability | 3-4 files (backend model + API + frontend) | Medium | Low -- additive |

### What already supports this

- **pyright `reportMatchNotExhaustive`** is already set to `"error"` in `pyrightconfig.json` (line 60). This was a deliberate cherry-pick from strict mode -- basic mode defaults it to `"none"`.
- **`assert_never` already works with `==`-style if/elif chains** in the repo's pyright version (1.1.408). Empirically verified: appending `else: typing.assert_never(x)` to an existing `==`-based if/elif chain catches missing variants at type-check time. No need to convert if/elif to `match`.
- **`ConnectionStatus`** in the frontend is the model pattern. It's declared as a narrow union (`state/store.ts:15`), every consumer keys off it via `Record<ConnectionStatus, ...>`, and the compiler would immediately flag a missing branch if a 5th variant were added. This pattern works and is already in the codebase.
- **The OpenAPI pipeline already generates narrow literal unions** (`generated-types.ts` lines 1478, 1497). The type information exists at the API boundary -- it's discarded downstream, not absent.
- **`@typescript-eslint/switch-exhaustiveness-check`** can be enabled with a one-line config addition. `parserOptions.projectService: true` is already set (the prerequisite for type-checked lint rules), and the rule ships in `typescript-eslint` (already installed).
- **`tally_manifest_statuses`** in `app_snapshots.py` already uses `tuple(ManifestStatus)` to generate its count dict -- self-updating when variants are added. This is the correct structural pattern for aggregate counting.

### What works against this

- **TypeScript type widening is pervasive.** Every status-mapping function in `utils/status.ts` accepts `string`, not the literal union. Internal dispatch uses `Map<string, X>` instead of `Record<LiteralUnion, X>`. This structurally prevents any compile-time exhaustiveness mechanism from ever firing, regardless of how narrow the type is at the API boundary.
- **Most Python consumers are intentionally partial.** The backend doesn't have fully-exhaustive if/elif chains on `ResourceStatus` or `ManifestStatus` -- most checks are single-value guards (`if status == FAILED: ...`) or membership tests (`if status in TERMINAL_STATUSES`). `assert_never` is mainly a forward-looking convention, not a retrofit opportunity.
- **pyright runs at pre-push only** (`prek.toml`: `stages = ["pre-push"]`), not pre-commit. A developer adding a new enum variant could commit code with missing branches and only discover it at push time.

## Gap Inventory

### Backend (Python): No active gaps

The backend audit checked all 15 enums against every non-test consumer. Every consumer is either (a) exhaustive or (b) intentionally partial with a sensible catch-all. The `ManifestStatus.DEGRADED` gaps from PR #1605 appear to already be fixed.

Notable patterns that resist gaps:
- `VALID_TRANSITIONS` dict in `resources/mixins.py` keys on all 9 `ResourceStatus` variants
- `build_manifest_info` in `app_registry.py` assigns all 6 `ManifestStatus` variants in priority order
- `tally_manifest_statuses` uses `tuple(ManifestStatus)` -- self-maintaining
- `RestartType` handling in `service_watcher.py` is a full if/elif/else chain covering all 3 variants

One minor non-gap finding: docstring examples in `bus/sync.py:563` and `bus/bus.py:1287` reference `ResourceStatus.STARTED`, which does not exist (the real values are `STARTING`/`RUNNING`). Stale docstrings, not code behavior.

### Frontend (TypeScript): 2 HIGH-severity gaps, 1 MEDIUM

**Gap 1 -- HIGH: `FailedAppsAlert` silently excludes "degraded" apps**
- **Location**: `frontend/src/app.tsx:425-435`
- **What happens**: The alert banner filters `manifests.filter(m => m.status === "failed")`. An app with `status === "degraded"` (some instances running, some failed) produces no alert signal.
- **Compounding factor**: This is also the only manifest-status consumer that reads the raw `m.status` field instead of overlaying live WS status via `appLiveStatus()`. Every other consumer (`sidebar-groups.ts`, `apps.tsx`, `palette-items.ts`) correctly uses the live overlay.
- **Test coverage**: Zero. `alert-banner.test.tsx` tests only the presentational component. `app.test.tsx` mocks the alert banner entirely. The filtering logic is untested.

**Gap 2 -- HIGH: Skipped executions mislabeled as "completed"**
- **Location**: `frontend/src/components/app-detail/execution-detail.tsx:156-174`, `frontend/src/components/shared/error-display.tsx:18-45`
- **What happens**: `ExecutionStatus` has 5 values. `"skipped"` is a real backend status (emitted when a job's trigger predicate returns `False`). In the execution detail view, a skipped record has no traceback and `status !== "success"`, so it enters `ErrorDisplay`. Inside `resolveResultDisplay()`, the if chain matches `"timed_out"`, `"cancelled"`, and `"error"` but not `"skipped"` -- it falls through to the default: `{ label: "result", message: "completed in Xms" }`. A job that never ran is displayed as having completed.
- **Contrast**: The list-view `ExecutionTable` handles this correctly via `STATUS_LABEL: Record<StatusKind, string>`, which includes `mute: "skipped"` and is compiler-exhaustive because it's a `Record` keyed by the closed `StatusKind` union.
- **Test coverage**: `error-display.tsx` has no test file at all. `"skipped"` as an `ExecutionStatus` is exercised in exactly one place across the entire frontend test suite (`utils/status.test.ts`).

**Gap 3 -- MEDIUM: Skipped executions get no status badge**
- **Location**: `frontend/src/components/app-detail/execution-detail.tsx:31-56`
- **What happens**: `StatusBadge` renders explicit badges for `"error"`, `"timed_out"`, `"cancelled"` but nothing for `"skipped"`. A skipped execution gets the same no-badge treatment as a successful one.

### WebSocket Event Emission: 1 HIGH gap, 1 observability gap, 1 incidental finding

**Gap 4 -- HIGH: HA connectivity changes don't update system status in the UI**
- **Location**: `frontend/src/hooks/use-websocket.ts:151-153` (frontend ignores `connectivity` events), `frontend/src/pages/diagnostics.tsx:375-382` (system status fetched via one-shot REST only)
- **What happens**: The backend correctly emits a `connectivity` WS event when the hassette-to-HA WebSocket link connects/disconnects. The frontend receives it but explicitly ignores it (`// Intentionally ignored`). The aggregated `SystemStatus` (the `status: "ok"|"degraded"|"starting"` field, `websocket_connected`, `boot_issues`) is fetched via one-shot REST (`/health`) with `staleTime: 30_000`, `refetchOnWindowFocus: false`, no `refetchInterval`. The only invalidation path is on browser-to-hassette WS reconnection -- unrelated to the hassette-to-HA link this data describes.
- **Effect**: If HA drops while an operator is on the Diagnostics page, the system health fields are frozen at whatever `/health` returned at page load. Per-service status rows do update live (via `service_status` WS messages), but the aggregate system health banner does not.

**Gap 5 -- HIGH (observability gap): StateCacheFreshness is invisible**
- **Location**: `src/hassette/core/state_proxy.py` (8 assignment sites, no external exposure)
- **What happens**: `StateCacheFreshness` (FRESH/STALE/UNAVAILABLE) is never exposed outside `state_proxy.py`. It is not in any REST response model, not in `SystemStatus`, and not in any WS payload. When a runtime HA disconnect after bootstrap marks the cache `STALE`, `get_system_status()` still reports a non-zero `entity_count` with no indication the data might be outdated. An operator cannot distinguish fresh from stale entity state from the UI.
- **Framing per the project's verification convention**: the running system emits no signal for this behavior. This is a gap in instrumentation, not a WS wiring bug to patch mechanically.

**Incidental finding -- MEDIUM: App resource-lifecycle transitions leak into `service_status` WS messages**
- Because `App` is a `Resource`, its lifecycle transitions (`handle_starting`/`handle_running` in `resources/lifecycle.py`) emit `HASSETTE_EVENT_SERVICE_STATUS` unconditionally. `RuntimeQueryService` subscribes to that topic with no role filter. Result: app instances appear intermixed with framework services in the Diagnostics "Services" panel, and two instances of the same App class collide on the same `resource_name` key (keyed by class name, not `app_key+index`), silently overwriting each other's status in `mergeServices()`.

### Root Cause: Frontend Type Widening

Every status-mapping function in `utils/status.ts` (`statusToVariant`, `statusToKind`, `executionStatusKind`, `levelToVariant`, `readinessVariant`) accepts `status: string`, not the literal union from `generated-types.ts`. Internal dispatch uses `Map<string, X>` rather than `Record<SpecificUnion, X>`. This means no function in the frontend status system can ever produce a compile-time exhaustiveness error, regardless of how narrow the type is at the API boundary. This is the structural reason PR #1605's gaps existed and why Gaps 1-3 above exist with no compiler signal.

## Options Evaluated

### Option A: Fix type widening + add ESLint exhaustiveness rule (frontend) + adopt `assert_never` convention (backend)

**How it works**: Two complementary changes, one per language.

On the TypeScript side: retype the ~7 function signatures in `status.ts` and `status-priority.ts` from `string` to the correct generated union types (`ManifestStatus`, `ResourceStatus`, `ExecutionStatus`). Convert the `Map<string, X>` dispatch tables to either `switch` statements with a `never`-typed default case, or `Record<LiteralUnion, X>` with `satisfies` (both proven to catch missing cases at compile time -- empirically verified against the repo's installed TypeScript). Add `"@typescript-eslint/switch-exhaustiveness-check": "error"` to `frontend/eslint.config.js`. No new dependencies; the rule ships in `typescript-eslint` (already installed) and `parserOptions.projectService` is already configured.

On the Python side: adopt a convention that any new exhaustive branch on a `StrEnum` ends with `else: typing.assert_never(x)`. No retrofit needed today (no fully-exhaustive if/elif chains on the high-risk enums exist). `reportMatchNotExhaustive: "error"` is already enabled and catches `match` statements. The `assert_never` addition extends this to if/elif chains. Consider adding a pyright probe test to `tests/pyright_probes/` that verifies the pattern works (the repo already has this test infrastructure).

**Pros**:
- Highest-leverage fix: 2-3 files changed on the frontend, 0 files changed on the backend today
- Uses patterns already proven in this codebase (`ConnectionStatus` + `Record<...>` is the existing model)
- Incremental adoption -- each function can be retyped independently
- Zero new dependencies
- The ESLint rule catches `switch` gaps even without the `never`-default pattern

**Cons**:
- Does not catch non-`switch` branching patterns (ad hoc `if (status === "failed")` checks like Gap 1's `.filter()` predicate). Those require the developer to route through the typed utility functions rather than doing bespoke string comparisons.
- The `Map<string, X>` to `switch`/`Record` conversion requires judgment about which pattern fits each site better (not purely mechanical)

**Effort estimate**: Small. The TypeScript retyping is confined to `status.ts` (147 lines) and `status-priority.ts` (~30 lines), plus one line in `eslint.config.js`. Consumer call sites do not need to change (passing a literal-union value into a `string`-typed parameter is already legal, so narrowing the parameter type is backward-compatible). The Python convention is documentation, not code.

**Dependencies**: None new.

### Option B: Additionally fix the 5 identified gaps

**How it works**: Option A establishes enforcement for the future. Option B fixes the gaps that exist right now:

1. **Gap 1** (`FailedAppsAlert`): Include `"degraded"` in the filter (or route through a shared "has failures" predicate). Switch from raw `m.status` to `appLiveStatus()` to match every other manifest-status consumer.
2. **Gap 2-3** (`execution-detail.tsx` / `error-display.tsx`): Add a `"skipped"` branch to `resolveResultDisplay()` with appropriate label/message. Add a `"skipped"` badge variant to `StatusBadge`.
3. **Gap 4** (connectivity WS): Either consume the `connectivity` WS event to invalidate the `/health` query, or add a `refetchInterval` to the system-status query so it self-corrects.
4. **Gap 5** (StateCacheFreshness): Add `cache_freshness` to `SystemStatus` response model, include it in the WS `service_status` or `connectivity` payload, and surface it in the Diagnostics UI.
5. **Incidental** (app-in-service-status): Filter `on_service_status` by `ResourceRole` to exclude `APP`-role resources, or key the merged services map by a composite key that includes instance identity.

**Pros**:
- Fixes real user-facing bugs (skipped-as-completed is actively misleading)
- Closes the observability gap for state cache freshness
- The alert banner fix is a one-line change

**Cons**:
- Gap 5 (StateCacheFreshness) is a larger change spanning backend models, API, and frontend -- not a quick fix
- The incidental finding (app-in-service-status) may require design thought about how multi-instance apps should appear in the Diagnostics panel

**Effort estimate**: Medium overall. Gaps 1-3 are Small individually. Gap 4 is Small (a `queryClient.invalidateQueries` call on `connectivity` events). Gap 5 is Medium (new field in `SystemStatus`, new WS payload content, new UI element). The incidental finding is Medium (behavioral design decision needed).

**Dependencies**: None new.

### Option C: Do less -- fix the type widening only, defer gap fixes

**How it works**: Only do the `status.ts`/`status-priority.ts` retyping and the ESLint rule addition. Don't fix any of the 5 gaps. The retyping will cause the existing gaps to surface as compiler errors (for switch-based consumers) or type mismatches (for `Record`-based maps), making them visible but not fixed.

**Pros**:
- Smallest possible change
- Establishes the enforcement mechanism
- Gaps become visible as TODO items (compiler errors or lint warnings) rather than silent runtime bugs

**Cons**:
- Gaps 1-3 remain user-facing bugs until fixed
- Gap 2 (skipped-as-completed) is actively misleading to anyone using the execution detail view
- Gap 4-5 are WS/observability issues that the type system can't catch (they're missing features, not wrong branches)

**Effort estimate**: Small.

**Dependencies**: None.

## Concerns

### Technical risks

- **Ad hoc string comparisons bypass the type system.** Gap 1 (`manifests.filter(m => m.status === "failed")`) is a `.filter()` predicate on a loose `string` field, not a `switch` or `Record` lookup. The ESLint exhaustiveness rule only checks `switch` statements. Preventing this class of bug requires either (a) always routing through typed utility functions, or (b) ensuring the `status` field on data interfaces carries the literal union type (not `string`) so that `=== "failed"` comparisons at least benefit from IDE autocomplete showing all variants.
- **`multi-instance.tsx` uses raw instance status instead of the live WS overlay.** This is the same pattern that produced Gap 1. It's not a missing-variant bug today, but it means the multi-instance view can show stale status after a WS update. Lower severity than Gap 1 because `statusToKind`/`statusToVariant` still handle every value that can appear.

### Complexity risks

- **Two different exhaustiveness mechanisms in one codebase.** Python uses `assert_never` in if/elif chains (checked by pyright). TypeScript uses `switch` + `never` default or `Record<Union, X>` (checked by tsc and ESLint). The patterns are conceptually identical but syntactically different. This is inherent to the dual-language setup and not avoidable.
- **`Map` vs `Record` vs `switch` -- three ways to dispatch on status in TypeScript.** `Map<string, X>` is not type-checkable. `Record<Union, X>` is. `switch` with `never` default is. The codebase needs to pick one or two patterns and be consistent. The existing `ConnectionStatus` consumers use `Record<...>`, which is the lowest-ceremony option for simple mappings.

### Maintenance risks

- **New status functions must remember to use the narrow type.** The enforcement only works if new code uses the literal union type, not `string`. A developer writing a new `function statusFoo(status: string)` silently opts out. The ESLint rule can't catch this -- it only checks `switch` exhaustiveness, not parameter type width.
- **Generated types can drift from hand-written types.** `frontend/src/utils/status.ts` line 3 defines a hand-rolled `AppStatus` type that doesn't match either generated `ManifestStatus` or `ResourceStatus` exactly (it includes `"shutting_down"`, which is in neither). After the retyping, this local type should be deleted in favor of the generated ones.

## Open Questions

- [ ] **Gap 5 design**: Should `StateCacheFreshness` be a field on `SystemStatus` (polled via `/health`), a field on the `connectivity` WS event, or a dedicated WS event type? The answer depends on how prominently stale-cache state should be surfaced in the UI.
- [ ] **Incidental finding scope**: Should the app-in-service-status leak be fixed by filtering `on_service_status` (suppress app-role events from the Services panel), by adding a role discriminator to the frontend's `mergeServices()`, or by rethinking how multi-instance apps appear in Diagnostics? This may warrant its own issue rather than being bundled here.
- [ ] **Should `status` fields on frontend data interfaces carry the literal union type?** Today, `AppRow.status` is `string` even though `AppManifestResponse.status` is the narrow `ManifestStatus` union. Narrowing the intermediate interfaces would make ad hoc `.filter(m => m.status === "failed")` checks benefit from autocomplete and type narrowing, but it requires auditing every place those interfaces are constructed.

## Recommendation

The frontend type-widening problem is the single highest-leverage fix. The Python backend is already well-positioned -- `reportMatchNotExhaustive` is enabled, no active gaps exist, and the `assert_never` convention is a forward-looking practice. The frontend, by contrast, has two active HIGH-severity bugs and a structural inability to benefit from any exhaustiveness mechanism until the type widening is fixed.

**Confidence**: The gap inventory and enforcement mechanism assessment are **Direct** -- grounded in empirical verification (pyright and tsc probe runs against the repo's installed tooling) and line-by-line code reading. The severity classifications are **Supported** -- multiple independent signals (code reading, test coverage gaps, and the PR #1605 precedent) converge on the same conclusions.

### Suggested next steps

1. **Fix Gaps 1-3 immediately** -- these are user-facing bugs. Gap 2 (skipped-as-completed) is actively misleading. Gap 1 (degraded-not-alerting) is the exact class of bug that prompted this audit. These are small, isolated fixes.
2. **Retype `status.ts` and `status-priority.ts`** -- change ~7 function signatures from `string` to the generated literal union types. Convert `Map<string, X>` dispatch tables to `Record<Union, X>` or `switch` + `never`. Add `@typescript-eslint/switch-exhaustiveness-check: "error"` to ESLint config. This establishes the enforcement mechanism.
3. **File issues for Gap 4 (WS connectivity) and Gap 5 (StateCacheFreshness observability)** -- these are larger, additive changes that deserve their own design consideration rather than being bundled into the exhaustiveness enforcement work.
4. **File an issue for the app-in-service-status incidental finding** -- this is a data-correctness issue in the Diagnostics panel that surfaced during the audit but is orthogonal to exhaustiveness enforcement.
5. **Add a pyright probe test** to `tests/pyright_probes/` verifying that `assert_never` catches missing StrEnum variants in if/elif chains, so the pattern is documented and regression-tested.

## Sources

- [Unreachable Code and Exhaustiveness Checking -- typing.python.org](https://typing.python.org/en/latest/guides/unreachable.html)
- [pyright reportMatchNotExhaustive discussion #5186](https://github.com/microsoft/pyright/discussions/5186)
- [Python type hints: exhaustiveness checking -- Adam Johnson](https://adamj.eu/tech/2022/10/14/python-type-hints-exhuastiveness-checking/)
- [typescript-eslint switch-exhaustiveness-check docs](https://github.com/typescript-eslint/typescript-eslint/blob/main/packages/eslint-plugin/docs/rules/switch-exhaustiveness-check.mdx)
- [Compile-time exhaustiveness checks in TypeScript -- DEV Community](https://dev.to/david-04/compile-time-exhaustiveness-checks-in-typescript-3igk)
- [ts-pattern GitHub](https://github.com/gvergnaud/ts-pattern)
- [Pyright configuration docs](https://microsoft.github.io/pyright/#/configuration.md)
