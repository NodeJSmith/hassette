---
task_id: "T07"
title: "Deduplicate setup boilerplate in use-log-filters.test.ts, use-correct-url.test.ts, and use-query-params.test.ts"
status: "done"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `frontend/src/components/shared/log-table/use-log-filters.test.ts`
- modify: `frontend/src/hooks/use-correct-url.test.ts`
- modify: `frontend/src/hooks/use-query-params.test.ts`
- modify or create: an appropriate helper file in `frontend/src/test/` for the shared block, plus any per-file helpers each of these three needs for their own additional clusters.

## Prompt

These three files share a single small (~5 line) flagged cluster with each other (likely a repeated import/setup line pattern, e.g. a shared URL-parsing or location-mock idiom), and `use-log-filters.test.ts` and `use-query-params.test.ts` each have a few additional clusters of their own. Get the authoritative current list first:

```bash
cd /home/jessica/source/hassette/.claude/worktrees/1560
uv run python tools/check_duplicate_code.py 2>&1 | grep -B1 -A1 -E "use-log-filters.test.ts|use-correct-url.test.ts|use-query-params.test.ts"
```

Since this cluster spans three target files (all in scope, unlike the mixed-with-non-target-file clusters elsewhere in this spec), a genuinely shared helper makes sense here. Confirmed: all three files already import `createWouterMock` from `frontend/src/test/mock-wouter.ts`, and the flagged block is leftover `const mockNavigate = vi.fn(); vi.mock("wouter", () => createWouterMock({ ... }))` boilerplate wrapped around that existing helper — extend/wrap `mock-wouter.ts`'s existing infrastructure (e.g. a `mockWouterNavigate()` helper that returns `mockNavigate` and does the `vi.mock` call) rather than inventing an unrelated new pattern.

For `use-log-filters.test.ts`'s and `use-query-params.test.ts`'s own additional clusters (not shared with the other two files), extract file-local helpers as needed, following the same pattern as other tasks in this spec.

Replace every occurrence. Do not change assertions or test names. For any occurrence that's a meaningfully distinct test body rather than true duplication, use `// dup-ignore-start: <specific reason>` / `// dup-ignore-end` instead of forcing extraction.

Re-run the checker scoped to these three files to confirm clearance:

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep -E "use-log-filters.test.ts|use-correct-url.test.ts|use-query-params.test.ts"
```

## Verify

- [ ] FR#2/FR#3: Every previously-flagged block in these three files is either extracted to a helper or `dup-ignore`d with a specific reason.
- [ ] AC#2: `uv run python tools/check_duplicate_code.py` output contains no line referencing any of `use-log-filters.test.ts`, `use-correct-url.test.ts`, or `use-query-params.test.ts`.
- [ ] AC#3: `cd frontend && npm run test -- src/components/shared/log-table/use-log-filters.test.ts src/hooks/use-correct-url.test.ts src/hooks/use-query-params.test.ts` passes with the same number of tests as before the change.
- [ ] AC#4: `cd frontend && npm run typecheck && npm run lint` pass with no new errors.
