---
task_id: "T02"
title: "retype status utilities from string to literal unions"
status: "planned"
depends_on: ["T01"]
implements: ["FR#4", "FR#5", "FR#6"]
---

## Target Files

- modify: `src/hassette/schemas/domain_models.py`
- modify: `src/hassette/web/models.py`
- modify: `frontend/ws-schema.json` (regenerated)
- modify: `frontend/src/api/ws-types.ts` (regenerated)
- modify: `frontend/openapi.json` (regenerated)
- modify: `frontend/src/api/generated-types.ts` (regenerated)
- modify: `frontend/src/utils/status.ts`
- modify: `frontend/src/utils/status-priority.ts`
- modify: `frontend/eslint.config.js`
- modify: `frontend/src/state/store.ts`
- modify: `frontend/src/utils/app-data.ts`
- modify: `frontend/src/components/shared/action-buttons.tsx`
- modify: `frontend/src/components/shared/execution-table.tsx`
- modify: `frontend/src/utils/status.test.ts`
- modify: `frontend/src/utils/status-priority.test.ts`

## Prompt

Retype frontend status-mapping functions from `string` to generated literal union types so adding a new enum variant without updating the maps is a compile-time error. Read `design/specs/102-status-exhaustiveness-enforcement/design.md` (Approach section, "Type narrowing", "Caller site narrowing", and "ESLint rule") for the full rationale.

### Step 0: Fix WS schema types and regenerate (domain_models.py)

The Pydantic WS schema models in `src/hassette/schemas/domain_models.py` type `status` fields as `str` despite the underlying dataclass payloads (`src/hassette/events/hassette.py`) using `ResourceStatus`/`ExecutionStatus`. Fix these 3 models:

1. `AppStatusChangedData` in `src/hassette/schemas/domain_models.py` (around line 107-121): change `status: str` to `status: ResourceStatus` and `previous_status: str | None` to `previous_status: ResourceStatus | None`. Import `ResourceStatus` from `hassette.types.enums`.
2. `ServiceStatusData` in `src/hassette/schemas/domain_models.py` (around line 130-150): change `status: str` to `status: ResourceStatus` and `previous_status: str | None` to `previous_status: ResourceStatus | None`.
3. `ExecutionCompletedData` in `src/hassette/web/models.py` (around line 284): change `status: str` to `status: ExecutionStatus`. Import `ExecutionStatus` from `hassette.types.types` (not `enums` — `ExecutionStatus` is defined in `types.py`, not `enums.py`).

Then regenerate the WS schema and all TypeScript types:
```bash
uv run python scripts/export_schemas.py --types
```

This regenerates `ws-schema.json`, `ws-types.ts`, `openapi.json`, and `generated-types.ts`. Verify the regenerated `ws-types.ts` now carries the enum union types instead of `string` for these fields.

### Step 1: Narrow upstream interfaces (store.ts, app-data.ts)

Narrow the interfaces that feed `string`-typed values into the status utilities. Without this, retyping the utility parameters causes TS2345 at every call site.

**`frontend/src/state/store.ts`:**
- Import `ResourceStatus` from `../api/generated-types` (via `components["schemas"]`).
- Change `AppStatusEntry.status` from `string` to `ResourceStatus` (these values come from WS `app_status_changed` events which carry `ResourceStatus`).
- Change `AppStatusEntry.previous_status` from `string | null` to `ResourceStatus | null`.
- Change `ServiceStatusEntry.status` from `string` to `ResourceStatus` (from WS `service_status` events).
- Change `ServiceStatusEntry.previous_status` from `string | null` to `ResourceStatus | null`.

**`frontend/src/utils/app-data.ts`:**
- Import `ManifestStatus`, `ResourceStatus` from `../api/generated-types`.
- Narrow `appLiveStatus()` return type from `string` to `ManifestStatus | ResourceStatus`.
- Narrow `instanceLiveStatus()` return type from `string` to `ManifestStatus | ResourceStatus` (same pattern, same file).
- If `AppRow.status` is still typed as `string`, narrow it to `ManifestStatus`.

### Step 2: Retype status.ts

1. Import the generated types. In `generated-types.ts`, the types are nested under `components["schemas"]`. Add at the top of `status.ts`:
   ```typescript
   import type { components } from "../api/generated-types";
   type ManifestStatus = components["schemas"]["ManifestStatus"];
   type ResourceStatus = components["schemas"]["ResourceStatus"];
   type ExecutionStatus = components["schemas"]["ExecutionStatus"];
   ```

2. Delete the hand-rolled `AppStatus` type (lines 3-4). Note: `"shutting_down"` is in **neither** `ResourceStatus` nor `ManifestStatus` — the backend has `"stopping"` but not `"shutting_down"`. It exists only as a legacy frontend value.

3. Define a combined union for `APP_STATUS_MAP` that covers both enum sets plus extras:
   ```typescript
   type StatusMapKey = ResourceStatus | ManifestStatus | "success" | "failure" | "unknown" | "shutting_down";
   ```
   `"shutting_down"` is a legacy frontend-only value not in either backend enum. Include it in the union so existing map entries compile. `"success"`, `"failure"`, `"unknown"` are service-health values not in either enum.

4. Convert `APP_STATUS_MAP` from `Map<string, StatusVariant>` to a `Record` with `satisfies`:
   ```typescript
   const APP_STATUS_MAP: Record<StatusMapKey, StatusVariant> = { ... } satisfies Record<StatusMapKey, StatusVariant>;
   ```
   Move all entries from the Map constructor into the record literal. Keep the same key-value pairs.

5. Update `statusToVariant` to accept `StatusMapKey` instead of `string`:
   ```typescript
   export function statusToVariant(status: StatusMapKey): StatusVariant {
     return APP_STATUS_MAP[status];
   }
   ```
   The `console.warn` fallback is no longer needed since the type system guarantees the key exists.

6. Update `INACTIVE_STATUSES` — retype from `Set<string>` to `Set<ManifestStatus | "shutting_down">` (since `"shutting_down"` is in the set but not in `ManifestStatus`).

7. Retype `isReloadableStatus` parameter from `string` to `ManifestStatus | ResourceStatus` (not `ManifestStatus` alone — `appLiveStatus()` returns the wider union and `palette-items.ts:59` passes its result directly).

8. Convert `STATUS_KIND_MAP` from `Map<string, StatusKind>` to `Record` with `satisfies`. Check which values are present and type against the matching union (`ResourceStatus | ManifestStatus | "shutting_down"` likely, since it includes `"shutting_down"`). Update `statusToKind` to accept the matching union type.

9. Convert `executionStatusKind` from an if/else chain with a fallback `return "err"` to a `Record<ExecutionStatus, StatusKind>` lookup with `satisfies`. The if/else pattern does not produce a compile error when a branch is deleted (the fallback swallows all unmatched values). The Record pattern makes a missing key a compile-time error.
   ```typescript
   const EXECUTION_STATUS_KIND: Record<ExecutionStatus, StatusKind> = {
     success: "ok",
     timed_out: "warn",
     cancelled: "cancel",
     error: "err",
     skipped: "mute",
   } satisfies Record<ExecutionStatus, StatusKind>;

   export function executionStatusKind(status: ExecutionStatus): StatusKind {
     return EXECUTION_STATUS_KIND[status];
   }
   ```

10. Retype `readinessVariant` first parameter from `string` to `ResourceStatus`.

11. Keep `levelToVariant` and `levelToKind` as `string` — log levels are open-ended, not a closed enum.

### Step 3: Retype status-priority.ts

1. Import the generated types (same pattern as status.ts).
2. Type `STATUS_PRIORITY` as `Record<ResourceStatus | ManifestStatus | "shutting_down", number>` with `satisfies`. Check that every variant from both enums is present; add any missing ones.
3. Retype `statusPriority` parameter from `string` to `ResourceStatus | ManifestStatus | "shutting_down"`.

### Step 4: ESLint rule (eslint.config.js)

Add to the rules block (inside the `files: ["**/*.{ts,tsx}"]` config object):
```
"@typescript-eslint/switch-exhaustiveness-check": "error",
```

### Step 5: Fix tests

**`status.test.ts`**: Update any test calls that pass raw strings to the retyped functions. The tests should still pass — if they were passing valid status values before, the retyping just narrows the accepted type. If any test passes an intentionally invalid string (to test the `console.warn` fallback that no longer exists), remove that test case.

**`status-priority.test.ts`**: Update references to match the new type. Tests that assert on `STATUS_PRIORITY["shutting_down"]` should still work since `"shutting_down"` is in the union.

### Step 6: Fix remaining caller site compile errors

Run `npm --prefix frontend run build`. If any call sites still pass a `string`-typed value to a retyped function, fix each by narrowing the source variable's type — not by casting. The design's Approach section ("Caller site narrowing") lists the key interfaces. Any additional sites discovered at this step should be narrowed the same way.

## Verify

- [ ] FR#4: Remove one entry from `APP_STATUS_MAP` → `npm --prefix frontend run build` fails with a type error referencing the missing key
- [ ] FR#4: Restore the entry → `npm --prefix frontend run build` succeeds
- [ ] FR#4: Remove one entry from `STATUS_KIND_MAP` → `npm --prefix frontend run build` fails with a type error
- [ ] FR#4: Remove one entry from `EXECUTION_STATUS_KIND` → `npm --prefix frontend run build` fails with a type error
- [ ] FR#5: Remove one entry from `STATUS_PRIORITY` → `npm --prefix frontend run build` fails with a type error
- [ ] FR#6: `npx --prefix frontend eslint frontend/src/utils/status.ts` passes with the new rule
- [ ] All existing frontend tests pass: `npm --prefix frontend run test`
