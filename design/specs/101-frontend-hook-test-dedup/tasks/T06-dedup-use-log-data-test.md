---
task_id: "T06"
title: "Deduplicate setup boilerplate in use-log-data.test.ts"
status: "done"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "FR#4", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `frontend/src/components/shared/log-table/use-log-data.test.ts`
- modify or create: an appropriate helper file in `frontend/src/test/` — read the file first to decide whether the extraction belongs in `query-test-utils.tsx` (if it composes those primitives) or a dedicated file.

## Prompt

`frontend/src/components/shared/log-table/use-log-data.test.ts` has ~6 flagged clusters, plus one small cluster shared with `frontend/src/api/ws-validator.test.ts` and `frontend/src/state/store.test.ts`. Get the authoritative current list first:

```bash
cd /home/jessica/source/hassette/.claude/worktrees/1560
uv run python tools/check_duplicate_code.py 2>&1 | grep -B1 -A1 "use-log-data.test.ts"
```

Only fix this file's occurrences — for the mixed cluster with `ws-validator.test.ts`/`store.test.ts`, do not touch those two non-target files (FR#4; see design.md's "MIXED clusters and scope").

Read the file, identify the repeated fixture/render setup, extract a named helper, and replace every occurrence. Do not change assertions or test names.

For any occurrence that's a meaningfully distinct test body rather than true duplication, use `// dup-ignore-start: <specific reason>` / `// dup-ignore-end` instead of forcing extraction.

Re-run the checker scoped to this file to confirm clearance:

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep "use-log-data.test.ts"
```

## Verify

- [ ] FR#2/FR#3: Every previously-flagged block in this file is either extracted to a helper or `dup-ignore`d with a specific reason.
- [ ] AC#2: `uv run python tools/check_duplicate_code.py` output contains no line referencing `use-log-data.test.ts`.
- [ ] AC#3: `cd frontend && npm run test -- src/components/shared/log-table/use-log-data.test.ts` passes with the same number of tests as before the change.
- [ ] AC#4: `cd frontend && npm run typecheck && npm run lint` pass with no new errors.
