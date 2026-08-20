---
task_id: "T09"
title: "Resolve use-relative-time.test.ts's mixed-cluster duplication"
status: "planned"
depends_on: ["T01", "T03", "T05"]
implements: ["FR#2", "FR#3", "FR#4", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `frontend/src/hooks/use-relative-time.test.ts`
- modify or create: an appropriate helper file in `frontend/src/test/`

## Prompt

`frontend/src/hooks/use-relative-time.test.ts` has no clusters of its own, but appears in 1-2 clusters shared with `frontend/src/hooks/use-query-invalidator.test.ts`, `frontend/src/hooks/use-scoped-query.test.ts`, `frontend/src/utils/format.test.ts`, and `frontend/src/utils/time-window.test.ts` — the last two are not target files and must not be touched. Get the authoritative current list first:

```bash
cd /home/jessica/source/hassette/.claude/worktrees/1560
uv run python tools/check_duplicate_code.py 2>&1 | grep -B1 -A1 "use-relative-time.test.ts"
```

Read `frontend/src/hooks/use-relative-time.test.ts` and identify what the shared block actually is (likely a fake-timer setup/teardown pattern given it's shared with a formatting-utility test and a time-window test — `vi.useFakeTimers()` / `vi.setSystemTime(...)` / cleanup, or a repeated import block).

**Fix only this file's occurrence.** Per design.md's "MIXED clusters and scope": once this file's copy becomes a helper call instead of the literal block, it stops matching the token pattern the other files still contain inline and drops out of the flagged list for this cluster — even though the cluster will likely keep firing among `format.test.ts`/`time-window.test.ts`/etc. That is expected and correct; do not edit those other files.

If a genuinely reusable helper makes sense (e.g. a fake-system-time setup), add it to `frontend/src/test/` under an appropriately generic name (not `use-relative-time`-specific if the pattern is really about time mocking in general) so it's available if a future non-target-file cleanup wants to adopt it too — but do not go modify `format.test.ts`/`time-window.test.ts`/`use-query-invalidator.test.ts`/`use-scoped-query.test.ts` to use it as part of this task (T03 and T05 handle `use-query-invalidator.test.ts` and `use-scoped-query.test.ts`'s own clusters separately, and may or may not touch this same block — check whether T03/T05 already landed and already extracted a matching helper before adding a duplicate one).

Do not change assertions or test names. For a meaningfully distinct test body rather than true duplication, use `// dup-ignore-start: <specific reason>` / `// dup-ignore-end` instead.

Separately, this file also appears in a plain 5-line `import`-statement cluster shared with `use-scoped-query.test.ts`, `use-telemetry-health.test.ts`, and `use-websocket.test.ts` (see design.md's "A separate cross-cutting cluster"). Import lines can't be extracted into a helper — resolve this file's occurrence with `// dup-ignore-start: <reason>` / `// dup-ignore-end` around the shared import block.

Re-run the checker scoped to this file to confirm clearance:

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep "use-relative-time.test.ts"
```

## Verify

- [ ] FR#2/FR#3/FR#4: This file's occurrence in the mixed cluster(s) is resolved without modifying `format.test.ts`, `time-window.test.ts`, or any other non-target file.
- [ ] AC#2: `uv run python tools/check_duplicate_code.py` output contains no line referencing `use-relative-time.test.ts`.
- [ ] AC#3: `cd frontend && npm run test -- src/hooks/use-relative-time.test.ts` passes with the same number of tests as before the change.
- [ ] AC#4: `cd frontend && npm run typecheck && npm run lint` pass with no new errors.
