---
task_id: "T02"
title: "Wire instance prop into app-detail-header and apps-table-row"
status: "done"
depends_on: ["T01"]
implements: ["FR#8", "FR#9", "AC#11", "AC#12"]
---

## Summary

Wire the `instance` prop from T01 into the two page-level components that render ActionButtons: the app-detail header (when viewing a single instance) and the apps table row (instance sub-rows). Also add `confirmStop` to both app-level and instance sub-rows in the apps table — currently only the app-detail header passes it. Includes one E2E test to verify the instance detail view fires instance-level routes.

## Target Files

- modify: `frontend/src/components/app-detail/app-detail-header.tsx`
- modify: `frontend/src/pages/apps-table-row.tsx`
- modify: `frontend/src/pages/apps-table-row.test.tsx`
- modify: `frontend/src/pages/app-detail.header.test.tsx`
- modify: `tests/e2e/test_app_detail.py`
- read: `frontend/src/pages/app-detail.tsx`
- read: `frontend/src/api/generated-types.ts`
- read: `design/specs/107-instance-actions-ui-cli/design.md`

## Prompt

### app-detail-header.tsx

In `frontend/src/components/app-detail/app-detail-header.tsx`:

The `ActionButtons` at line 66 currently passes `appKey`, `status`, `variant="text"`, and `confirmStop`. When `manifest.instance_count > 1` and `!showParentOverview`, also pass:

```tsx
instance={{ index: resolvedInstanceIndex, name: currentInstance?.instance_name ?? "" }}
```

The `currentInstance` and `resolvedInstanceIndex` are already available as props (`Props` interface). When showing the parent overview or a single-instance app, do not pass `instance` (existing behavior).

### apps-table-row.tsx

In `frontend/src/pages/apps-table-row.tsx`:

1. **Instance sub-rows** (line 210): The `<ActionButtons>` call already has access to `inst.index` and `inst.instance_name`. Pass:

```tsx
instance={{ index: inst.index, name: inst.instance_name }}
confirmStop
```

2. **App-level row** (line 161): Add `confirmStop` to the existing `<ActionButtons>` call. Do NOT pass `instance` — this is the collapsed parent row, and the design explicitly excludes instance-level actions here (Non-Goals).

### Tests

Update `apps-table-row.test.tsx` to verify:
- Instance sub-rows pass `instance` and `confirmStop` to ActionButtons.
- App-level row passes `confirmStop` but does NOT pass `instance`.

Update `app-detail.header.test.tsx` if it asserts on ActionButtons props — it currently only checks the component renders, so this may not need changes.

### E2E Test

Write one Playwright test (in existing `tests/e2e/` or new file) that:
1. Navigates to a multi-instance app in the demo stack.
2. Clicks an instance tab to view a single instance.
3. Clicks an action button (e.g., Reload).
4. Verifies the request goes to `/apps/{app_key}/instances/{index}/reload` (not `/apps/{app_key}/reload`).

See design doc `## Smoke Test → Frontend` for the scenario. The demo stack has multi-instance example apps.

## Focus

- `app-detail-header.tsx` already receives `currentInstance` (type `InstanceInfo | undefined`) and `resolvedInstanceIndex` (number) as props. The guard `manifest.instance_count > 1 && !showParentOverview` is already used at line 73 for the instance index display — reuse the same condition.
- `currentInstance?.instance_name` can be undefined if the resolved index is out of range (stale URL). The `?? ""` fallback keeps the prop type-safe. The design accepts this edge case (the backend 404 is the backstop).
- `apps-table-row.tsx` renders instance sub-rows in a `.map()` at line 166. Each `inst` has `.index` (number) and `.instance_name` (string) available.
- The E2E test infrastructure uses Playwright. Multi-instance apps exist in the demo stack. See CLAUDE.md `## E2E Tests (Playwright)` for setup and run commands.
- `app-detail.header.test.tsx` currently only asserts `action-buttons` testid exists (line 70) — likely no changes needed unless the test starts asserting on props.
- Adding `confirmStop` to the app-level table row is an intentional behavior change — see Behavioral Invariants in the design doc.

## Verify

- [ ] FR#8: app-detail-header passes `instance` to ActionButtons when viewing a single instance of a multi-instance app
- [ ] FR#9: apps-table-row passes `instance` to ActionButtons in instance sub-rows and `confirmStop` on both app-level and instance sub-rows
- [ ] AC#11: Component test confirms apps-table-row passes confirmStop on both row types
- [ ] AC#12: E2E test navigates to multi-instance app instance view and verifies action buttons fire instance-level routes
