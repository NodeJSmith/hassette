---
task_id: "T09"
title: "Delete old hooks, remove reconnectVersion, and verify"
status: "planned"
depends_on: ["T03", "T04", "T05", "T06", "T07", "T08"]
implements: ["AC#1", "AC#4", "AC#5", "AC#6"]
---

## Summary

Final cleanup: delete the four old hook files and their tests, remove the `reconnectVersion` signal from AppState and its increment from `use-websocket.ts`, verify no stale imports remain, and run the full test suite + TypeScript compilation to confirm behavioral parity and zero regressions.

## Prompt

### 1. Delete old hook files

Delete these 7 files:
- `frontend/src/hooks/use-api.ts`
- `frontend/src/hooks/use-api.test.ts`
- `frontend/src/hooks/use-scoped-api.ts`
- `frontend/src/hooks/use-scoped-api.test.ts`
- `frontend/src/hooks/use-filtered-signal-refetch.ts`
- `frontend/src/hooks/use-filtered-signal-refetch.test.ts`
- `frontend/src/hooks/use-manifest-fetcher.ts` (may already be deleted by T05 — skip if missing)

### 2. Remove `reconnectVersion` from AppState

In `frontend/src/state/create-app-state.ts`:
- Remove the `reconnectVersion: signal(0)` line (~line 185)
- Remove any comments referencing `reconnectVersion`
- Update the `AppState` type (it's inferred from `ReturnType<typeof createAppState>`, so removing the signal is sufficient)

### 3. Remove `reconnectVersion` increment from `use-websocket.ts`

In `frontend/src/hooks/use-websocket.ts`, find the reconnect handler block:
```typescript
if (hasConnectedRef.current) {
  state.logs.clear();
  state.serviceStatus.value = {};
  state.reconnectVersion.value = state.reconnectVersion.value + 1; // REMOVE THIS LINE
}
```

Remove only the `reconnectVersion` increment line. Keep `state.logs.clear()` and `state.serviceStatus.value = {}` — those are still needed.

Also remove `reconnectVersion` from any comments in the file.

### 4. Verify no stale imports

Run grep to confirm zero remaining references to deleted hooks:

```bash
grep -rn "use-api\|useApi\|use-scoped-api\|useScopedApi\|use-filtered-signal-refetch\|useFilteredSignalRefetch\|use-manifest-fetcher\|useManifestFetcher\|reconnectVersion" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules | grep -v ".test."
```

Also grep test files separately:
```bash
grep -rn "use-api\|useApi\|use-scoped-api\|useScopedApi\|use-filtered-signal-refetch\|useFilteredSignalRefetch\|use-manifest-fetcher\|useManifestFetcher\|reconnectVersion" frontend/src/ --include="*.test.*" | grep -v node_modules
```

Both commands should return zero results. If any stale references exist, fix them.

### 5. Run full test suite

```bash
cd frontend && npm run test
```

All tests must pass. If any fail, investigate and fix — they indicate a migration gap.

### 6. Run TypeScript compilation

```bash
cd frontend && npx tsc --noEmit
```

Must complete with zero errors. Type mismatches (especially `Error` vs `string` in JSX, or `Signal<T>` vs `T`) indicate missed migration points.

### 7. Run linter

```bash
cd frontend && npm run lint
```

Fix any lint errors introduced during the migration.

## Focus

- `use-manifest-fetcher.ts` may already be deleted by T05. Check before attempting deletion — `rm` on a missing file is harmless but noting the expectation is important.
- The grep patterns must cover both kebab-case file references (`use-api`) and camelCase import names (`useApi`). Also cover `reconnectVersion`.
- Be careful removing the `reconnectVersion` increment from `use-websocket.ts` — remove ONLY the increment line, not the surrounding `if` block or the other signal resets.
- After `reconnectVersion` is removed from `create-app-state.ts`, any remaining reference to `state.reconnectVersion` in test files will cause a TypeScript error. The type check in step 6 catches this.
- If the test suite reveals failures, check for: (a) missing MSW handlers for endpoints, (b) async timing issues in tests that were previously synchronous, (c) error type mismatches (`Error` object rendered as `[object Error]`).
- The E2E test suite (`npm run test` in `frontend/` only covers unit/integration tests). E2E tests run via `uv run nox -s e2e` from the repo root — run this too if the project has Playwright installed.

## Verify

- [ ] AC#1: grep returns zero results for old hook names and `reconnectVersion` across all source and test files
- [ ] AC#4: `npm run test` in `frontend/` exits with zero failures
- [ ] AC#5: E2E test suite passes — run `uv run nox -s e2e` and confirm zero failures
- [ ] AC#6: `npx tsc --noEmit` in `frontend/` completes with zero errors
