---
task_id: "T03"
title: "Deduplicate setup boilerplate in use-query-invalidator.test.ts"
status: "done"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `frontend/src/hooks/use-query-invalidator.test.ts`
- modify: `frontend/src/test/query-test-utils.tsx` (add a generically-reusable helper here — this pattern composes the file's existing `createTestQueryClient`/`renderHookWithProviders`, so it belongs alongside them, not in a new file)

## Prompt

`frontend/src/hooks/use-query-invalidator.test.ts` has ~15 flagged clusters. Get the authoritative current list first:

```bash
cd /home/jessica/source/hassette/.claude/worktrees/1560
uv run python tools/check_duplicate_code.py 2>&1 | grep -B1 -A1 "use-query-invalidator.test.ts"
```

**What you'll find**: nearly every `it()` block repeats this shape (varying only the filter fn and query key):

```ts
const filterFn = ...;
const queryClient = createTestQueryClient();
const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

const { rerender } = renderHookWithProviders<void, { value: string | null }>(
  ({ value }) => useQueryInvalidator(value, filterFn, [key], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS),
  { queryClient, initialProps: { value: NULL_STRING } },
);
```

**Fix**: add a helper to `frontend/src/test/query-test-utils.tsx`:

```ts
export function renderInvalidatorHook<T>(
  hook: (value: T) => void,
  initialValue: T,
) {
  const queryClient = createTestQueryClient();
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  const { rerender } = renderHookWithProviders<void, { value: T }>(
    ({ value }) => hook(value),
    { queryClient, initialProps: { value: initialValue } },
  );
  return { queryClient, invalidateSpy, rerender };
}
```

Adjust the exact signature to whatever removes the most duplication cleanly — read the file first and check how much varies between call sites (the hook call itself, e.g. `useQueryInvalidator(value, filterFn, [key], WS_DEBOUNCE_DELAY_MS, WS_DEBOUNCE_MAX_WAIT_MS)`, differs per test, so the helper likely needs to take a factory function like the sketch above rather than baking in the hook call). This file imports `vi` from `vitest` already — `query-test-utils.tsx` will need to add that import if it doesn't have it, or the spy creation can stay in the test file if that reads cleaner (spy is only 1 line; use judgment on whether it's worth moving into the shared helper vs. leaving as the one line callers still write themselves).

Replace every occurrence with the new helper. Do not change assertions or test names.

Re-run the checker scoped to this file to confirm clearance:

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep "use-query-invalidator.test.ts"
```

## Verify

- [ ] FR#2/FR#3: Every previously-flagged block in this file is either extracted to a helper or `dup-ignore`d with a specific reason.
- [ ] AC#2: `uv run python tools/check_duplicate_code.py` output contains no line referencing `use-query-invalidator.test.ts`.
- [ ] AC#3: `cd frontend && npm run test -- src/hooks/use-query-invalidator.test.ts` passes with the same number of tests as before the change.
- [ ] AC#4: `cd frontend && npm run typecheck && npm run lint` pass with no new errors.
