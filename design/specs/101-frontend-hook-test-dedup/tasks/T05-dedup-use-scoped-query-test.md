---
task_id: "T05"
title: "Deduplicate setup boilerplate in use-scoped-query.test.ts"
status: "planned"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "FR#4", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `frontend/src/hooks/use-scoped-query.test.ts`
- modify: `frontend/src/test/query-test-utils.tsx` (if the extracted helper composes the existing shared primitives) OR create a dedicated helper file if hook-specific — use judgment after reading the file.

## Prompt

`frontend/src/hooks/use-scoped-query.test.ts` has ~10 flagged clusters. Get the authoritative current list first:

```bash
cd /home/jessica/source/hassette/.claude/worktrees/1560
uv run python tools/check_duplicate_code.py 2>&1 | grep -B1 -A1 "use-scoped-query.test.ts"
```

Note: one small cluster in this file (a 5-8 line block near the top, likely fake-timer or import setup) is shared with `frontend/src/hooks/use-relative-time.test.ts`, `frontend/src/hooks/use-query-invalidator.test.ts`, `frontend/src/utils/format.test.ts`, and `frontend/src/utils/time-window.test.ts`. Only fix this file's occurrence — do not touch the other files (FR#4; see context.md's Constraints and design.md's "MIXED clusters and scope" section for why a partial per-file fix is sufficient).

Separately, this file also appears in the plain 5-line `import`-statement cluster shared with `use-relative-time.test.ts`, `use-telemetry-health.test.ts`, and `use-websocket.test.ts` (see design.md's "A separate cross-cutting cluster"). Import lines can't be extracted into a helper — resolve this file's occurrence with `// dup-ignore-start: <reason>` / `// dup-ignore-end` around the shared import block.

Read the file, identify the repeated render/setup shape, extract a named helper for it, and replace every occurrence. Do not change assertions or test names.

For any occurrence that's a meaningfully distinct test body rather than true duplication, use `// dup-ignore-start: <specific reason>` / `// dup-ignore-end` instead of forcing extraction.

Re-run the checker scoped to this file to confirm clearance:

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep "use-scoped-query.test.ts"
```

(It's fine if this file still appears in the *mixed* cluster's list of *other* files' line numbers when you grep broadly — what matters is that `use-scoped-query.test.ts` itself no longer appears as one of the flagged occurrences.)

## Verify

- [ ] FR#2/FR#3: Every previously-flagged block in this file is either extracted to a helper or `dup-ignore`d with a specific reason.
- [ ] AC#2: `uv run python tools/check_duplicate_code.py` output contains no line referencing `use-scoped-query.test.ts`.
- [ ] AC#3: `cd frontend && npm run test -- src/hooks/use-scoped-query.test.ts` passes with the same number of tests as before the change.
- [ ] AC#4: `cd frontend && npm run typecheck && npm run lint` pass with no new errors.
