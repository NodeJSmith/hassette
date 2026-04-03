# Design: Wave 3 — Dashboard & App Detail Polish

**Status:** archived

**Date:** 2026-03-23
**Issues:** #363, #385, #383, #357, #359
**Scope:** Frontend (Preact) only — no backend changes
**Critique:** Reviewed 2026-03-23 by 3 adversarial critics. Findings incorporated below.

## Dropped from scope

- **#386 (multi-instance labels)** — Deferred. Critics (all 3) identified that the backend iterates `snapshot.manifests` (one per app_key) and `get_all_app_summaries()` hard-filters to `instance_index = 0`. This isn't a two-field addition — it requires restructuring the query layer and endpoint loop, plus fixing the `appStatus` signal keying, React keys, and card links. GH issue updated with findings.
- **#347 (handler display cleanup)** — Already implemented in `handler-row.tsx:42-63`. Closed.
- **#338 (scheduler-jobs instance_index filter)** — Endpoint removed in Preact migration. Closed.

## Problem

The Preact SPA has five rough edges across the dashboard and app list:

1. **No debounce on WS refetches (#363)** — every `app_status_changed` WS event triggers an immediate REST refetch of the dashboard app grid. During batch app startup (e.g., 8 apps starting in quick succession), this fires 8 redundant fetches. Worse, only the app grid refetches — KPIs and errors go stale, creating contradictory numbers on the same page.
2. **Dashboard tiles lack execution data (#385)** — tiles show handler/job counts but not invocation/execution counts, which are the most actionable numbers for diagnosing "is this app doing anything?"
3. **Multi-instance expand state lost on navigation (#383)** — expanding a multi-instance app in the app list resets on every page load because state is stored in ephemeral Preact signals.
4. **Duplicated status-to-variant mappings (#357)** — `VARIANT_MAP` and `BADGE_VARIANT_MAP` in `status-badge.tsx` duplicate status→color logic. The health bar, health card, health strip, and item row dots each have their own variant logic in CSS — 5 mapping sites total.
5. **Backend sends raw classification strings as CSS class names (#359)** — `error_rate_class` ("good"/"warn"/"bad") and `health_status` ("excellent"/"good"/"warning"/"critical") are used directly in CSS class selectors with no runtime validation. A backend change sending an unexpected value silently produces an unstyled element.

## Architecture

### 1. Debounce WS-triggered refetches (#363)

**Approach:** Add a `useDebouncedEffect` hook that wraps `appStatus` signal changes with a 500ms trailing debounce. The dashboard page replaces its current immediate `appGrid.refetch()` with a page-level debounced refresh that triggers **all three** dashboard data fetches (KPIs, app grid, errors).

**File:** New `frontend/src/hooks/use-debounced-effect.ts` — a generic hook reusable anywhere.

**Dashboard change:** `frontend/src/pages/dashboard.tsx` lines 22–31 — replace the `useEffect` that calls only `appGrid.refetch()` with `useDebouncedEffect(() => appStatus.value, 500, () => { kpis.refetch(); appGrid.refetch(); errors.refetch(); })`.

**Edge case:** On WS reconnection, `reconnectVersion` already triggers a full refetch via `useApi`'s built-in signal effect. The debounce applies only to `appStatus` changes. Document this invariant in `create-app-state.ts` as a comment on the signals, so future developers know `reconnectVersion` and `appStatus` must not be conflated.

**Critique note (TENSION — debounce vs optimistic update):** The adversarial reviewer argued that status changes should be applied optimistically to cached grid data instead of triggering a REST refetch. This is correct in principle — the WS already delivers the status. However, the grid also includes telemetry aggregates (invocation counts, error rates, health status) that change alongside status. Optimistic update would only update the status badge while leaving telemetry stale — a partial update that's worse than a debounced full refresh. The debounce approach is the right call for now. Optimistic status + periodic telemetry polling is a valid future optimization.

### 2. Execution/invocation counts on dashboard tiles (#385)

**Backend:** `DashboardAppGridEntry` already returns `total_invocations`, `total_executions`, `total_errors`, `total_job_errors`. No backend change needed.

**Frontend:** `app-card.tsx` — add a compact stats row below the existing handler/job counts showing invocations and executions. Use `--ht-text-dim` color, `--ht-text-xs` size, mono font. Format: `{invocations} inv · {executions} exec`.

### 3. Persist multi-instance expand state (#383)

**Approach:** Store expanded app keys in `localStorage` via a new `local-storage.ts` utility that owns the key prefix.

**Implementation:** New `frontend/src/utils/local-storage.ts` with:
- A single `STORAGE_PREFIX = "hassette:"` constant
- Typed `getStoredSet(key)` / `setStoredSet(key, value)` helpers with try/catch (corrupt/missing values fall back to empty set)
- Prune stored keys on mount by intersecting with current manifest app keys (prevents unbounded growth from deleted apps)

`manifest-row.tsx` initializes its `expanded` signal from the stored set and syncs on toggle.

**Key prefix normalization:** The existing `ht-theme` key in `create-app-state.ts:53` uses a different convention. The `local-storage.ts` utility should migrate it: read `ht-theme`, write to `hassette:theme`, delete the old key. All future localStorage access goes through this utility.

**Scope note:** Only persists which apps are expanded, not scroll position or filter state.

### 4. Consolidate status-to-variant mappings (#357)

**Current state (5 mapping sites):**
- `status-badge.tsx:7-21`: `VARIANT_MAP` + `BADGE_VARIANT_MAP` (app lifecycle status → CSS variant)
- `health-bar.tsx:12`: uses `health_status` string directly as CSS class
- `kpi-strip.tsx:25`: uses `error_rate_class` string directly as CSS class
- `health-strip.tsx:13-18`: `STATUS_COLOR_MAP` maps status → good/warn/bad (different vocabulary)
- `handler-row.tsx:31-32` / `job-row.tsx:31-32`: inline ternary for dot color (threshold logic, not a status mapping)

**Approach:** Create `frontend/src/utils/status.ts` with:
- `type AppStatus = "running" | "failed" | "stopped" | "disabled" | "blocked" | "starting" | "shutting_down"`
- `type StatusVariant = "success" | "danger" | "warning" | "neutral"`
- `function statusToVariant(status: string): StatusVariant` — single mapping for app lifecycle status
- `type HealthGrade = "excellent" | "good" | "warning" | "critical"`
- `function healthGradeToVariant(grade: string): StatusVariant` — single mapping
- `type ErrorRateClass = "good" | "warn" | "bad"`
- `function errorRateToVariant(cls: string): StatusVariant` — single mapping

Components that map app status, health grade, or error rate class import from `status.ts`. CSS classes use `ht-{component}--{variant}` suffix pattern consistently.

**Critique note (TENSION — consolidation scope):** The adversarial reviewer argued that handler/job dot color is threshold logic (`failed > 0 ? "danger" : ...`), not a status mapping, and shouldn't be in `status.ts`. This is correct — leave the handler/job dot ternaries inline. They're clear, local, and operate on numeric thresholds, not string status values. The consolidation covers the 4 string-mapping sites; the dot color stays where it is.

### 5. Runtime validation for backend classification strings (#359)

**Tied to #357.** The backend sends `error_rate_class` and `health_status` as plain strings. TypeScript union types are erased at runtime — they give false safety if the backend sends an unexpected value.

**Approach:** Each mapping function in `status.ts` serves as the runtime boundary:
- Accept `string` (not the union type) as input
- Check against a known set (e.g., `const APP_STATUSES = new Set(["running", "failed", ...])`)
- For unknown values: return `"neutral"` as fallback AND `console.warn("Unknown status:", raw)` to surface contract drift during development
- The union types exist for call sites that have already been validated — internal use only

In `frontend/src/api/endpoints.ts`, keep types as `string` (honest about what the API actually returns). The mapping functions in `status.ts` are the validation boundary, not the TypeScript types.

**No backend change needed.**

## Alternatives Considered

**Debounce (#363):** Considered `requestAnimationFrame` batching — coalesces within one frame (~16ms) but not across status events arriving 50-100ms apart. 500ms trailing debounce is more appropriate. Also considered optimistic update of status + periodic telemetry polling — valid future optimization but partial updates are worse than debounced full refresh for now.

**Expand state (#383):** Considered Preact signals via context instead of localStorage. Signals lose state on refresh; localStorage survives. Expand state is a user preference, not ephemeral UI state.

**Status consolidation (#357):** Considered moving all classification to backend (return `variant: "success"` instead of `health_status: "excellent"`). Rejected — semantic meaning is useful for tooltips and accessibility. Also considered consolidating handler/job dot color — rejected per adversarial critique; threshold logic should stay inline.

**Runtime validation (#359):** Considered narrowing TypeScript types to unions at the API boundary. Rejected — compile-time types without runtime validation create false confidence. Keep `string` in API types, validate in mapping functions.

## Test Strategy

- **Debounce hook:** Unit test with fake timers — verify multiple rapid calls coalesce into one, verify all 3 fetches fire.
- **Dashboard tiles:** E2E test — verify invocation/execution counts render on app cards.
- **Expand persistence:** Unit test for localStorage helpers (including corrupt data, missing keys, stale app keys). E2E test verifying expand state survives navigation.
- **Status utils:** Unit tests for all mapping functions — every known status → expected variant, unknown status → "neutral" + console.warn.
- **localStorage migration:** Unit test that `ht-theme` is migrated to `hassette:theme` and old key is removed.

## Files Changed (Estimated)

### New files
- `frontend/src/hooks/use-debounced-effect.ts`
- `frontend/src/utils/status.ts`
- `frontend/src/utils/local-storage.ts`

### Modified files
- `frontend/src/pages/dashboard.tsx` — debounced page-level refetch (all 3 endpoints)
- `frontend/src/components/dashboard/app-card.tsx` — invocation/execution counts
- `frontend/src/components/apps/manifest-row.tsx` — localStorage expand persistence
- `frontend/src/components/shared/status-badge.tsx` — import from status.ts, remove inline maps
- `frontend/src/components/dashboard/kpi-strip.tsx` — use errorRateToVariant
- `frontend/src/components/dashboard/health-bar.tsx` — use healthGradeToVariant
- `frontend/src/components/dashboard/health-strip.tsx` — replace STATUS_COLOR_MAP with statusToVariant
- `frontend/src/state/create-app-state.ts` — document reconnectVersion/appStatus invariant, migrate ht-theme key
