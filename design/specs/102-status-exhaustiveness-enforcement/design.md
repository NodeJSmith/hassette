# Design: Status Exhaustiveness Enforcement

**Date:** 2026-08-21
**Status:** archived
**Mode:** sketch

## Problem

Adding a new status enum variant silently breaks multiple frontend consumers because all status-mapping functions accept `string` instead of generated literal union types. PR #1605 introduced `ManifestStatus.DEGRADED` and post-merge review found 5 places that missed it. Three active bugs remain: degraded apps missing from the failure alert, skipped executions mislabeled as "completed", and skipped executions missing a status badge.

## Goals

- Fix the 3 active frontend status-handling bugs (Gaps 1-3 from the research brief)
- Retype frontend status utilities from `string` to generated literal unions so the compiler catches missing variants
- Add `@typescript-eslint/switch-exhaustiveness-check` ESLint rule
- File issues for larger WS/observability gaps that deserve separate design (connectivity refresh, StateCacheFreshness visibility, app-in-service-status leak)

## Non-Goals

- Retrofitting Python `match`/`assert_never` on existing backend consumers (backend is already gap-free; `reportMatchNotExhaustive` is enabled)
- Fixing the WS connectivity refresh gap (Gap 4) or StateCacheFreshness observability gap (Gap 5) in this PR — those are additive features needing separate design
- Fixing the app-in-service-status leak (incidental finding) — orthogonal to exhaustiveness

**Note on backend scope:** The Pydantic WS schema models in `domain_models.py` type `status` fields as `str` despite the underlying dataclass payloads using `ResourceStatus`/`ExecutionStatus`. This PR fixes those 3 models to use the correct enum types and regenerates `ws-schema.json`/`ws-types.ts`. This is a schema-fidelity fix, not exhaustiveness work — the non-goal of "don't touch backend Python" applies to adding match/assert_never to consumers, not to fixing type widening in the schema export layer.

## Functional Requirements

- **FR#1** `FailedAppsAlert` includes apps with `status === "degraded"` in its failure banner, using the live WS overlay (`appLiveStatus`) instead of raw `m.status`
- **FR#2** `resolveResultDisplay()` in `error-display.tsx` handles `"skipped"` with a distinct label/message instead of falling through to "completed in Xms"
- **FR#3** `StatusBadge` in `execution-detail.tsx` renders a badge for `"skipped"` executions
- **FR#4** Status-mapping functions in `status.ts` accept the correct generated literal union type instead of `string`, so adding a new variant without updating the map is a compile-time error
- **FR#5** `STATUS_PRIORITY` in `status-priority.ts` is typed against the generated union so missing a variant is a compile-time error
- **FR#6** `@typescript-eslint/switch-exhaustiveness-check` is enabled as an ESLint error
- **FR#7** GitHub issues are filed for each of: WS connectivity refresh gap, StateCacheFreshness observability gap, and app-in-service-status leak

## Acceptance Criteria

- **AC#1** (FR#1) A manifest with `status: "degraded"` appears in the `FailedAppsAlert` banner
- **AC#2** (FR#2) A skipped execution shows "skipped" label text, not "completed in Xms"
- **AC#3** (FR#3) A skipped execution renders a distinct status badge
- **AC#4** (FR#1, FR#4, FR#5) Removing any single entry from `IS_FAILURE_STATUS`, `APP_STATUS_MAP`, `STATUS_KIND_MAP`, `STATUS_PRIORITY`, or `EXECUTION_STATUS_KIND` produces a TypeScript compiler error
- **AC#5** (FR#4) `cd frontend && npm run build` succeeds with the retyped signatures
- **AC#6** (FR#7) Three GitHub issues exist for the deferred gaps, each with type/area/size labels and acceptance criteria

## Approach

### Gap fixes (FR#1-3)

**FR#1 — FailedAppsAlert** (`app.tsx:425-435`): The filter currently checks `m.status === "failed"`. Change it to use `appLiveStatus()` from `utils/app-data.ts` (matching every other manifest-status consumer) and route the failure check through a `Record<ManifestStatus | ResourceStatus, boolean>` predicate (`IS_FAILURE_STATUS`) in `status.ts` with `satisfies`. `failed`, `degraded`, and `crashed` are `true`; all others `false`. This ensures a future variant that should trigger the alert is a compile error if omitted — an ad hoc `===` chain would be immune to both the ESLint rule and the Record/satisfies enforcement, reproducing the exact bug class this PR exists to close.

**FR#2 — resolveResultDisplay** (`error-display.tsx:18-45`): Add a `"skipped"` branch before the default fallback. Use a neutral tone (`text-muted-foreground`) with message `"skipped"` — no duration since the handler never ran. The existing `executionStatusKind` in `status.ts:48-56` already maps `"skipped"` → `"mute"`, so the upstream `StatusShape` already works; only the `ErrorDisplay` text is wrong.

**FR#3 — StatusBadge** (`execution-detail.tsx:31-56`): Add a `"skipped"` case rendering `<Badge variant="neutral" size="sm">skipped</Badge>`. This matches the existing pattern for `"cancelled"` (also `variant="neutral"`).

### Type narrowing (FR#4-5)

The generated types already exist in `generated-types.ts`:
- `ManifestStatus: "disabled" | "blocked" | "degraded" | "running" | "failed" | "stopped"`
- `ResourceStatus: "not_started" | "starting" | "running" | "stopping" | "stopped" | "failed" | "crashed" | "exhausted_dead" | "exhausted_cooling"`
- `ExecutionStatus: "success" | "error" | "cancelled" | "timed_out" | "skipped"`

**status.ts changes:**
- Import `ManifestStatus`, `ResourceStatus`, `ExecutionStatus` from `generated-types.ts` (via the `components["schemas"]` path)
- Delete the hand-rolled `AppStatus` type (line 3-4). Note: `"shutting_down"` is in neither `ResourceStatus` nor `ManifestStatus` (the backend has `"stopping"` in `ResourceStatus` but not `"shutting_down"`). It exists only in the frontend maps as a legacy value. Add it to the `StatusMapKey` union alongside the service-health extras so the current map entries compile; it can be removed as dead code in a follow-up if confirmed unused.
- Convert `APP_STATUS_MAP` and `STATUS_KIND_MAP` from `Map<string, X>` to `Record<union, X>` with `satisfies` — this makes missing entries a compile-time error. The `statusToVariant`/`statusToKind` functions then index the record directly.
- Convert `executionStatusKind` from an if/else chain to a `Record<ExecutionStatus, StatusKind>` lookup with `satisfies` — retyping the parameter alone does not produce a compile error when a branch is deleted (the fallback `return "err"` swallows all unmatched values). The Record pattern makes a missing key a compile-time error, matching the other maps.
- Retype `isReloadableStatus` from `string` to `ManifestStatus | ResourceStatus` (not `ManifestStatus` alone — `appLiveStatus()` returns the wider union, and `palette-items.ts:59` passes its result directly to `isReloadableStatus`)
- Retype `readinessVariant` parameter from `string` to the resource status union
- Keep `levelToVariant`/`levelToKind` as `string` — log levels are open-ended, not a closed enum

**status-priority.ts changes:**
- Import `ResourceStatus` and `ManifestStatus` from `generated-types.ts`
- Type `STATUS_PRIORITY` as `Record<ResourceStatus | ManifestStatus | "shutting_down", number>` with `satisfies` — any missing variant is a compile error. `"shutting_down"` is included because the map has this entry today (see `StatusMapKey` rationale above).
- Retype `statusPriority` parameter from `string` to `ResourceStatus | ManifestStatus | "shutting_down"`

**Key design decision:** `APP_STATUS_MAP` covers both `ResourceStatus` and `ManifestStatus` values plus service-health values (`"success"`, `"failure"`, `"unknown"`) and the legacy frontend-only value `"shutting_down"`. These extras don't come from either generated enum. Define a local union: `type StatusMapKey = ResourceStatus | ManifestStatus | "success" | "failure" | "unknown" | "shutting_down"` and use it as the `Record` key type. This keeps the compiler checking the enum portion while allowing the known extras.

### Caller site narrowing (FR#4)

Retyping the status utility functions from `string` to literal unions also requires narrowing the upstream interfaces that feed values into them. Without this, every call site that passes a `string`-typed variable produces TS2345. Key interfaces to narrow:

- `AppStatusEntry.status` in `state/store.ts` — receives `ResourceStatus` values from WS `app_status_changed` events. Narrow from `string` to `ResourceStatus`.
- `ServiceStatusEntry.status` in `state/store.ts` — receives `ResourceStatus` values from WS `service_status` events. Narrow from `string` to `ResourceStatus`.
- `appLiveStatus()` return type in `utils/app-data.ts` — returns either a `ManifestStatus` (from the manifest `row.status`), a `ResourceStatus` (from the WS overlay), or the synthesized `"degraded"`. Narrow return type to `ManifestStatus | ResourceStatus`.
- `instanceLiveStatus()` return type in `utils/app-data.ts` — same pattern as `appLiveStatus()`, narrow to `ManifestStatus | ResourceStatus`.
- `AppRow.status` — if still typed as `string`, narrow to `ManifestStatus`.

**Additional caller sites to narrow** (discovered via `grep -rn "statusToVariant\|statusToKind\|executionStatusKind\|isReloadableStatus\|statusPriority" frontend/src`):
- `ActionButtons` props in `action-buttons.tsx` — `status: string` prop fed from `appLiveStatus()`, narrow to `ManifestStatus | ResourceStatus`
- `ExecutionRecord.status` in `execution-table.tsx` — feeds `executionStatusKind()`, narrow to `ExecutionStatus`
- Any remaining `string`-typed variables passed to retyped functions — run `npm run build` after retyping to find them; fix each by narrowing the source interface rather than casting.

### ESLint rule (FR#6)

Add to `eslint.config.js` rules block:
```
"@typescript-eslint/switch-exhaustiveness-check": "error"
```

`parserOptions.projectService: true` is already configured (line 21-22), which is the prerequisite for type-checked lint rules.

### Issue filing (FR#7)

File three issues using `/mine-create-issue`:
1. **WS connectivity refresh** — `connectivity` WS event is received but ignored; system status is fetched via one-shot REST with no refresh
2. **StateCacheFreshness observability** — `StateCacheFreshness` is never exposed outside `state_proxy.py`; operators can't distinguish fresh from stale entity state
3. **App-in-service-status leak** — app resource-lifecycle transitions emit `HASSETTE_EVENT_SERVICE_STATUS`, polluting the Diagnostics Services panel

## Smoke Test

After implementation:
1. `cd frontend && npm run build` — succeeds (no type errors from retyped signatures)
2. `cd frontend && npm run lint` — passes with the new exhaustiveness rule
3. `cd frontend && npm run test` — all existing tests pass
4. Remove one entry from `APP_STATUS_MAP` → `npm run build` fails with a type error (proves enforcement works)
5. Remove one entry from `STATUS_KIND_MAP` → `npm run build` fails with a type error

## Changed Files

- modify: `frontend/src/utils/status.ts` — retype functions from `string` to literal unions, convert Maps and if/else chains to Records
- modify: `frontend/src/utils/status-priority.ts` — type `STATUS_PRIORITY` against generated unions
- modify: `frontend/src/app.tsx` — fix `FailedAppsAlert` to include degraded and use live WS overlay
- modify: `frontend/src/components/shared/error-display.tsx` — add `"skipped"` branch to `resolveResultDisplay()`
- modify: `frontend/src/components/app-detail/execution-detail.tsx` — add `"skipped"` badge to `StatusBadge`
- modify: `frontend/eslint.config.js` — add `switch-exhaustiveness-check` rule
- modify: `frontend/src/state/store.ts` — narrow `AppStatusEntry.status` and `ServiceStatusEntry.status` from `string` to `ResourceStatus`
- modify: `frontend/src/utils/app-data.ts` — narrow `appLiveStatus()` and `instanceLiveStatus()` return types
- modify: `src/hassette/schemas/domain_models.py` — fix `AppStatusChangedData.status/previous_status`, `ServiceStatusData.status/previous_status` from `str` to `ResourceStatus`
- modify: `src/hassette/web/models.py` — fix `ExecutionCompletedData.status` from `str` to `ExecutionStatus`
- modify: `frontend/ws-schema.json` — regenerated via `export_schemas.py --types`
- modify: `frontend/src/api/ws-types.ts` — regenerated via `export_schemas.py --types`
- modify: `frontend/openapi.json` — regenerated via `export_schemas.py --types`
- modify: `frontend/src/api/generated-types.ts` — regenerated via `export_schemas.py --types`
- modify: `frontend/src/components/shared/action-buttons.tsx` — narrow `Props.status` from `string`
- modify: `frontend/src/components/shared/execution-table.tsx` — narrow `ExecutionRecord.status` from `string`
- create: `frontend/src/components/shared/error-display.test.tsx` — test coverage for `resolveResultDisplay()` including skipped
- modify: `frontend/src/utils/status.test.ts` — update tests for retyped signatures
- modify: `frontend/src/utils/status-priority.test.ts` — update tests for retyped signatures
