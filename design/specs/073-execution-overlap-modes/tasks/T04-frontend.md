---
task_id: "T04"
title: "Show mode chip and suppressed/dropped counts in the UI"
status: "done"
depends_on: ["T03"]
implements: ["FR#18", "FR#19", "AC#13"]
---

## Summary

Surface the new listener fields in the monitoring UI: a mode chip in the unified handler row and mode + suppressed/dropped stat cells in the listener detail pane. Mirror the existing conditional `cancelled` cell pattern — show counts only when non-zero. Verify against the live demo stack and the e2e suite.

## Prompt

All paths under `frontend/src/`. The generated types (`api/generated-types.ts`) already carry `mode`, `suppressed_count`, `dropped_count` after T03 — consume them, do not redefine.

1. **Mode chip in the handler row** — `components/app-detail/unified-handler-row.tsx`: render a mode chip beside the existing kind chip, showing the listener's `mode` (`single`/`restart`/`queued`/`parallel`). Use the shared `Chip`/`Badge` component (see `components/shared/`), matching how the kind chip is rendered. Keep it compact (FR#18).

2. **Detail stat cells** — `components/app-detail/listener-detail.tsx`: in the stats-cell builder (the one with the conditional `if (listener.cancelled > 0) cells.push({ label: "Cancelled", value: listener.cancelled })` at ~line 55), add:
   - a mode cell (always shown): `{ label: "Mode", value: listener.mode }` (FR#18)
   - a suppressed cell shown only when `listener.suppressed_count > 0` (FR#19)
   - a dropped cell shown only when `listener.dropped_count > 0` (FR#19)

   Follow the exact conditional-push pattern already used for `cancelled`.

3. **Styling** — reuse existing chip/cell classes; do not add raw `ht-*` classes or hex/px values. If a new class is genuinely needed, follow the CSS Modules + tokens rules in CLAUDE.md (co-located `.module.css`, token variables only). Prefer reusing what the kind chip and existing cells use.

4. **Verify visually + e2e** — run the demo stack and confirm the chip and cells render for a listener of each mode and with non-zero counts (see the demo-script approach in project memory / `tests/TESTING.md`). Run the e2e suite: `uv run nox -s e2e` (build the SPA first if needed: `uv run nox -s frontend`). Confirm the app-detail Handlers view renders the mode chip and the suppressed/dropped counts (AC#13).

## Focus

- `unified-handler-row.tsx` already renders a kind chip/Badge and a stats line (calls/failed/timed-out) — the mode chip goes beside the kind chip; match that JSX.
- `listener-detail.tsx` stats-cell builder at ~line 55 has the `cancelled` conditional-push — clone that exact shape for suppressed/dropped, and add the always-shown mode cell.
- Counts are live (reset on restart) — that's expected; don't add any "historical" affordance.
- Worktree: run `cd frontend && npm install` once before building (`.claude/rules/frontend-worktree.md`).
- TypeScript rules (`references/common/typescript.md`): no `any`, no `as` casts, no enums — the generated `mode` is a string union from the schema; use it directly.
- Do not edit `generated-types.ts`/`ws-types.ts` by hand — they came from T03's regeneration.

## Verify
- [ ] FR#18: the handler row and the listener detail pane both display the listener's `mode`.
- [ ] FR#19: the listener detail pane shows `suppressed_count` and `dropped_count` cells only when non-zero.
- [ ] AC#13: the app-detail UI renders the mode chip and the suppressed/dropped counts (confirmed via the demo stack and the e2e suite).
