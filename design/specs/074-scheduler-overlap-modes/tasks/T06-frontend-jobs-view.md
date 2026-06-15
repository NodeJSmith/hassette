---
task_id: "T06"
title: "Display job mode and overlap counts in the jobs UI"
status: "planned"
depends_on: ["T05"]
implements: ["FR#12", "AC#11"]
---

## Summary

Show each scheduled job's overlap `mode` and, when non-zero, its live `suppressed`/`dropped` counts
in the web UI jobs view, mirroring how listener mode and counts render in the handlers view. Update
the test factory and component tests.

## Prompt

Implement the frontend half of design.md "Architecture §6". The backend fields and regenerated types
already exist (T05).

1. **Jobs view component**: find the component that renders the scheduled-jobs table/rows (the jobs
   equivalent of the handlers view — see Focus) and add display of `mode` and the
   `suppressed_count`/`dropped_count` fields. Mirror how the listener row surfaces mode + counts in
   `frontend/src/components/app-detail/unified-handler-row.tsx` / `listener-detail.tsx` (e.g. a
   `Badge`/`Chip` for mode, counts shown only when > 0). Reuse the shared `Badge`/`Chip` components
   and existing CSS-module patterns (see CLAUDE.md "CSS Architecture").

2. **Test factory** (GAP): `frontend/src/test/factories.ts` — add `mode`, `suppressed_count`,
   `dropped_count` to the `JobSummary` factory with sensible defaults (`mode: "single"`, counts `0`).

3. **Component tests**: add/extend tests asserting the mode renders and that suppressed/dropped show
   only when non-zero. Match the existing `*.test.tsx` style for the jobs/handlers views.

Run `cd frontend && npm install` (worktree) then `npm run build` and the frontend tests to verify.
Do NOT regenerate types here — T05 already did and committed them; consume `generated-types.ts`.

## Focus

- Backend fields available on `JobSummary` after T05: `mode: string`, `suppressed_count: number`,
  `dropped_count: number` (in `generated-types.ts`).
- Listener parity reference for the visual pattern: `frontend/src/components/app-detail/
  unified-handler-row.tsx`, `listener-detail.tsx`, and `frontend/src/pages/handlers-rows.tsx` —
  these already render listener `mode` and suppressed/dropped. Mirror that treatment for jobs.
- Locate the jobs view: grep `frontend/src/` for `JobSummary`, `/scheduler/jobs`, `next_run`,
  `fire_at`, or `jobs` in `frontend/src/pages/` and `frontend/src/components/app-detail/` — the jobs
  table consumes the same endpoint enriched in T05.
- CSS: use CSS Modules + `clsx`; shared `Badge`/`Chip`/`Card` components instead of raw `ht-*`
  classes (CLAUDE.md "CSS Architecture", "When to use styles/ vs a module vs a shared component").
- Worktree: `node_modules` is not shared — `npm install` first (`.claude/rules/frontend-worktree.md`).
- Screenshot before/after if practical (frontend invariant) — the demo stack is the real-data path.

## Verify

- [ ] FR#12: the jobs UI displays each job's mode; suppressed/dropped counts render when non-zero.
- [ ] AC#11: the jobs view (UI half) shows mode and live counts sourced from the jobs API; the JobSummary test factory and component tests cover the new fields.
