---
task_id: "T01"
title: "fix active frontend status-handling bugs"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3"]
---

## Target Files

- modify: `frontend/src/app.tsx`
- modify: `frontend/src/utils/status.ts`
- modify: `frontend/src/components/shared/error-display.tsx`
- modify: `frontend/src/components/app-detail/execution-detail.tsx`
- create: `frontend/src/components/shared/error-display.test.tsx`

## Prompt

Fix three active status-handling bugs in the frontend. Read `design/specs/102-status-exhaustiveness-enforcement/design.md` (Approach section, "Gap fixes") for the full rationale.

**FR#1 — FailedAppsAlert** (`frontend/src/app.tsx`, the `FailedAppsAlert` function near line 425):
- The current filter is `manifests.filter((m) => m.status === "failed")`. This misses apps with `status === "degraded"` (some instances running, some failed).
- Import `appLiveStatus` from `../utils/app-data` and `useAppStore` to get `appStatuses`.
- Replace raw `m.status` reads with `appLiveStatus(appStatuses, m)` to match every other manifest-status consumer.
- Instead of an ad hoc `=== "failed" || === "degraded"` chain (which is immune to the ESLint exhaustiveness rule and the Record/satisfies enforcement), define a `Record<ManifestStatus | ResourceStatus, boolean>` predicate in `status.ts` (e.g. `IS_FAILURE_STATUS`) with `satisfies`, where `failed`, `degraded`, and `crashed` are `true` and all others are `false`. Type it against the wider union because `appLiveStatus()` returns `ManifestStatus | ResourceStatus` — indexing a `Record<ManifestStatus, boolean>` with a value that could be `ResourceStatus` won't compile. Use `IS_FAILURE_STATUS[liveStatus]` in the filter. A future variant that should trigger the alert becomes a compile error if omitted from the record.

**FR#2 — resolveResultDisplay** (`frontend/src/components/shared/error-display.tsx`, `resolveResultDisplay` function):
- Add a `"skipped"` branch before the default fallback return.
- Return `{ label: "result", toneClass: "text-muted-foreground", message: "skipped" }` — no duration since the handler never ran.
- Export `resolveResultDisplay` (currently not exported) so it can be tested directly.
- Create `error-display.test.tsx` with tests covering all 5 `ExecutionStatus` values: `success` (not rendered by ErrorDisplay — but test resolveResultDisplay directly), `error`, `timed_out`, `cancelled`, `skipped`.

**FR#3 — StatusBadge** (`frontend/src/components/app-detail/execution-detail.tsx`, `StatusBadge` function near line 31):
- Add a `"skipped"` case: `{status === "skipped" && <Badge variant="neutral" size="sm">skipped</Badge>}`.
- Place it after the `"cancelled"` case, following the existing pattern.

## Verify

- [ ] FR#1: A test or manual inspection confirms that a manifest with `status: "degraded"` is included in the `FailedAppsAlert` filter
- [ ] FR#1: Remove one entry from `IS_FAILURE_STATUS` → `npm --prefix frontend run build` fails with a type error
- [ ] FR#2: `resolveResultDisplay("skipped", 0)` returns a result with `message: "skipped"`, not "completed in 0ms"
- [ ] FR#3: `StatusBadge` renders a badge element when `status === "skipped"`
- [ ] All existing frontend tests pass: `npm --prefix frontend run test`
