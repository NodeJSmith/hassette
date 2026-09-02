---
task_id: "T01"
title: "Add instance prop and instance endpoints to ActionButtons"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#6", "FR#7", "AC#1", "AC#2", "AC#3", "AC#4", "AC#5"]
---

## Summary

Add three per-instance endpoint functions to the frontend API layer and extend the ActionButtons component with an optional `instance` prop. When present, action buttons route to instance-level API endpoints and produce instance-aware toast text, testid, aria-label, and stop-confirmation dialog text. When absent, all behavior is unchanged. This is the core frontend plumbing — wiring into specific pages is T02.

## Target Files

- modify: `frontend/src/api/endpoints.ts`
- modify: `frontend/src/components/shared/action-buttons.tsx`
- modify: `frontend/src/components/shared/action-buttons.test.tsx`
- read: `frontend/src/api/client.ts`
- read: `frontend/src/api/generated-types.ts`
- read: `design/specs/107-instance-actions-ui-cli/design.md`

## Prompt

### Endpoint functions

Add three functions to `frontend/src/api/endpoints.ts` following the existing `startApp`/`stopApp`/`reloadApp` pattern:

```typescript
export const startInstance = (appKey: string, index: number) =>
  apiPost<ActionResponse>(`/apps/${encodeURIComponent(appKey)}/instances/${index}/start`);
export const stopInstance = (appKey: string, index: number) =>
  apiPost<ActionResponse>(`/apps/${encodeURIComponent(appKey)}/instances/${index}/stop`);
export const reloadInstance = (appKey: string, index: number) =>
  apiPost<ActionResponse>(`/apps/${encodeURIComponent(appKey)}/instances/${index}/reload`);
```

### ActionButtons component

In `frontend/src/components/shared/action-buttons.tsx`:

1. **Add `instance` prop** to `Props`: `instance?: { index: number; name: string }`. This is a single paired object — not two independent optional fields.

2. **Update `performAction`**: Accept an optional `instance` parameter. When present, call `startInstance`/`stopInstance`/`reloadInstance` with `instance.index`; when absent, call app-level functions. Update toast text: success becomes `Instance "${instance.name}" of "${appKey}" ${outcome}` when instance is present, keeps existing `App "${appKey}" ${outcome}` when absent. Same pattern for error toast.

3. **Update `buildButtonSpecs`**: Accept the `instance` parameter. When present, produce instance-aware `ariaLabel` values (e.g., "Start instance 'office'" vs. "Start app"). Visibility logic is unchanged.

4. **Update `ActionButton`**: When `instance` is present, render `data-testid={`btn-${spec.action}-${appKey}-${instance.index}`}` instead of the current appKey-only testid.

5. **Update `StopConfirmDialog`**: Accept an optional `instanceName` prop. When present, set title to `Stop instance '${instanceName}'?` and description to `Stop instance '${instanceName}' of '${appKey}'? It will stop processing events until restarted.` When absent, keep current "Stop app?" title and existing description.

6. **Wire the `instance` prop through** the `ActionButtons` export: pass it to `performAction`, `buildButtonSpecs`, and `StopConfirmDialog`.

### Tests

Add test cases to `frontend/src/components/shared/action-buttons.test.tsx`:

- With `instance={{ index: 1, name: "office" }}`: clicking Start calls `startInstance("app_key", 1)`, not `startApp`.
- With `instance`: clicking Stop/Reload calls instance-level endpoints.
- Without `instance`: existing tests continue passing (backward compatibility).
- With `instance` + `confirmStop`: dialog title says "Stop instance 'office'?" and description includes instance name.
- With `instance`: `data-testid` includes instance index, `aria-label` includes instance name.
- With `instance`: toast text includes instance name.

Existing tests must pass unchanged — they don't provide `instance` and should see no behavior change.

See design doc `## Architecture → Frontend` for full specification.

## Focus

- The `ACTIONS` const map (`action-buttons.tsx:24-28`) maps each action to `{ request, verb, outcome }`. The instance routing needs to coexist with this map — when `instance` is present, use `startInstance`/`stopInstance`/`reloadInstance` instead of the `request` from `ACTIONS`. The verb/outcome strings stay the same.
- `useAsyncAction` hook (`use-async-action.ts`) wraps the action in loading state — the instance param must flow through the `run` → `performAction` call chain.
- The `ActionButtonStatusKey` type (`utils/status.ts`) drives button visibility — this does not change.
- `StopConfirmDialog` currently takes `appKey`, `open`, `onOpenChange`, `onConfirm`. Add `instanceName?: string`.

## Verify

- [ ] FR#1: ActionButtons with `instance={{ index: 1, name: "office" }}` clicking Start calls `POST /apps/{appKey}/instances/1/start`
- [ ] FR#2: ActionButtons with `instance` clicking Stop calls instance-level stop route
- [ ] FR#3: ActionButtons with `instance` clicking Reload calls instance-level reload route
- [ ] FR#4: ActionButtons without `instance` calls app-level routes (existing behavior unchanged)
- [ ] FR#5: Stop dialog title and description both include instance name when `instance` is provided
- [ ] FR#6: `data-testid` includes instance index and `aria-label` includes instance name when `instance` present
- [ ] FR#7: Toast text includes instance name when `instance` present
- [ ] AC#1: Component tests confirm instance-level endpoint calls with `instance` prop
- [ ] AC#2: Component tests confirm app-level endpoint calls without `instance` prop
- [ ] AC#3: Component test confirms dialog title and description include instance name
- [ ] AC#4: Component test confirms instance-scoped testid and aria-label
- [ ] AC#5: Component test confirms instance-aware toast text
