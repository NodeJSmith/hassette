---
task_id: "T04"
title: "Deduplicate setup boilerplate in use-telemetry-health.test.ts"
status: "planned"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `frontend/src/hooks/use-telemetry-health.test.ts`
- modify: `frontend/src/test/query-test-utils.tsx` (if the extracted helper composes the existing `createTestQueryClient`/`renderHookWithProviders` primitives) OR create a dedicated `frontend/src/test/telemetry-health-test-utils.ts` if the setup is hook-specific enough not to belong in the shared file — read the file first and use judgment.

## Prompt

`frontend/src/hooks/use-telemetry-health.test.ts` has ~8 flagged clusters. Get the authoritative current list first:

```bash
cd /home/jessica/source/hassette/.claude/worktrees/1560
uv run python tools/check_duplicate_code.py 2>&1 | grep -B1 -A1 "use-telemetry-health.test.ts"
```

Read the file to understand the repeated shape — it will be render + mock setup boilerplate similar in spirit to `use-query-invalidator.test.ts` (see `frontend/src/hooks/use-query-invalidator.test.ts` and, if T03 has already landed, `frontend/src/test/query-test-utils.tsx`'s `renderInvalidatorHook` for the pattern this project now follows: extract a small factory helper that takes what varies per test as parameters and returns whatever the tests assert against).

Extract a named helper for the repeated setup, following the same naming convention (`render<Thing>Hook` or similar). Replace every occurrence. Do not change assertions or test names.

For any occurrence that's a meaningfully distinct test body rather than true duplication, use `// dup-ignore-start: <specific reason>` / `// dup-ignore-end` instead of forcing extraction.

Separately, this file also appears in a plain 5-line `import`-statement cluster shared with `use-relative-time.test.ts`, `use-scoped-query.test.ts`, and `use-websocket.test.ts` (see design.md's "A separate cross-cutting cluster"). Import lines can't be extracted into a helper — resolve this file's occurrence with `// dup-ignore-start: <reason>` / `// dup-ignore-end` around the shared import block.

Re-run the checker scoped to this file to confirm clearance:

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep "use-telemetry-health.test.ts"
```

## Verify

- [ ] FR#2/FR#3: Every previously-flagged block in this file is either extracted to a helper or `dup-ignore`d with a specific reason.
- [ ] AC#2: `uv run python tools/check_duplicate_code.py` output contains no line referencing `use-telemetry-health.test.ts`.
- [ ] AC#3: `cd frontend && npm run test -- src/hooks/use-telemetry-health.test.ts` passes with the same number of tests as before the change.
- [ ] AC#4: `cd frontend && npm run typecheck && npm run lint` pass with no new errors.
