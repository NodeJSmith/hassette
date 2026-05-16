---
task_id: "T01"
title: "Extract formatRate to shared format utilities"
status: "done"
depends_on: []
implements: ["AC#11"]
---

## Summary

Move the `formatRate` function from its current location as a file-local function in `frontend/src/pages/handlers.tsx` to the shared format utilities module at `frontend/src/utils/format.ts`. Update the import in `handlers.tsx` and add unit tests for the function in `frontend/src/utils/format.test.ts`. This is a prerequisite for the card component, which needs to display error rates using the same calculation.

## Prompt

1. **Read** `frontend/src/pages/handlers.tsx` and locate the `formatRate` function (currently at line 74). It is a file-local function:
   ```tsx
   function formatRate(failed: number, total: number): string {
     return total > 0 ? ((failed / total) * 100).toFixed(1) + "%" : "—";
   }
   ```

2. **Add** `formatRate` as an exported function in `frontend/src/utils/format.ts`. Place it near the other formatting functions. Keep the exact same signature and logic.

3. **Update** `frontend/src/pages/handlers.tsx`: remove the local `formatRate` function and add an import from `../../utils/format`.

4. **Add unit tests** in `frontend/src/utils/format.test.ts`. Follow the existing test organization in that file (grouped by function in `describe` blocks). Test these cases:
   - `formatRate(0, 100)` → `"0.0%"`
   - `formatRate(3, 100)` → `"3.0%"`
   - `formatRate(1, 3)` → `"33.3%"`
   - `formatRate(0, 0)` → `"—"`
   - `formatRate(5, 0)` → `"—"` (degenerate case)
   - `formatRate(100, 100)` → `"100.0%"`

5. **Verify** that existing tests still pass: `cd frontend && npx vitest run src/utils/format.test.ts src/pages/handlers.test.tsx`

## Focus

- `frontend/src/utils/format.ts` — the shared format module. All formatting functions follow the same convention: return `"—"` for missing/invalid data. Keep `formatRate` consistent with this pattern.
- `frontend/src/utils/format.test.ts` — existing test file with ~306 lines organized by function. Each `describe` block tests one function. Match this style exactly.
- `frontend/src/pages/handlers.tsx` — the file losing its local `formatRate`. Two call sites exist at lines 170 and 212: `const errorRate = formatRate(row.failed, row.runs)`. These must not change — only the function definition moves.
- The existing `handlers.test.tsx` tests should continue to pass unchanged since the function behavior is identical.

## Verify

- [ ] AC#11: `formatRate` is exported from `frontend/src/utils/format.ts` and imported by `frontend/src/pages/handlers.tsx` — no local copy remains in handlers.tsx
