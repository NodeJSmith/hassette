---
task_id: "T08"
title: "Deduplicate setup boilerplate in use-media-query.test.ts and use-roving-tab-index.test.ts"
status: "planned"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `frontend/src/hooks/use-media-query.test.ts`
- modify: `frontend/src/hooks/use-roving-tab-index.test.ts`
- modify or create: appropriate helper file(s) in `frontend/src/test/` — these two files are unrelated to each other (bundled in one task purely because both are small), so each likely needs its own small fix, not a shared helper between them.

## Prompt

Both files have small, self-contained duplication (1 cluster in `use-media-query.test.ts`, 2 in `use-roving-tab-index.test.ts`). Get the authoritative current list first:

```bash
cd /home/jessica/source/hassette/.claude/worktrees/1560
uv run python tools/check_duplicate_code.py 2>&1 | grep -B1 -A1 -E "use-media-query.test.ts|use-roving-tab-index.test.ts"
```

`use-media-query.test.ts`: the `matchMedia` mock itself is defined once in a `beforeEach` and is **not** the duplicated part — don't extract a `mockMatchMedia()` helper on that assumption. The actual flagged block (confirmed live) is a 3x-repeated dynamic-import + render pattern of this shape: `currentMatches = <bool>; const { useMediaQuery, BREAKPOINT_MOBILE } = await import("./use-media-query"); const { result } = renderHook(...)`. Extract a helper around that shape instead (e.g. a function that sets `currentMatches`, does the dynamic import, and renders the hook, returning `result`).

`use-roving-tab-index.test.ts`: likely repeated DOM/ref setup for keyboard-navigation tests. Extract a small helper for the repeated setup.

Treat these as two independent, small fixes within one task. Do not force a shared helper between the two files unless the actual duplicated code is identical (unlikely, given they test unrelated hooks). Replace every occurrence. Do not change assertions or test names.

For any occurrence that's a meaningfully distinct test body rather than true duplication, use `// dup-ignore-start: <specific reason>` / `// dup-ignore-end` instead of forcing extraction — this may be the better fit for these small, low-count clusters rather than adding a whole new helper file for a 3-line block used twice.

Re-run the checker scoped to these files to confirm clearance:

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep -E "use-media-query.test.ts|use-roving-tab-index.test.ts"
```

## Verify

- [ ] FR#2/FR#3: Every previously-flagged block in both files is either extracted to a helper or `dup-ignore`d with a specific reason.
- [ ] AC#2: `uv run python tools/check_duplicate_code.py` output contains no line referencing `use-media-query.test.ts` or `use-roving-tab-index.test.ts`.
- [ ] AC#3: `cd frontend && npm run test -- src/hooks/use-media-query.test.ts src/hooks/use-roving-tab-index.test.ts` passes with the same number of tests as before the change.
- [ ] AC#4: `cd frontend && npm run typecheck && npm run lint` pass with no new errors.
