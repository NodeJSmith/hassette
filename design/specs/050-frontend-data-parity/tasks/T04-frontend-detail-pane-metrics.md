---
task_id: "T04"
title: "Surface hidden metrics and error traceback on handler/job detail panes"
status: "done"
depends_on: ["T01", "T02"]
implements: ["FR#2", "FR#5", "FR#6", "FR#7", "FR#8", "FR#17", "AC#4", "AC#5", "AC#13"]
---

## Summary
Update the handler and job detail pane components to surface the newly available backend data: successful/cancelled counts on handlers, successful count and timed_out/failed separation on jobs, min/avg/max duration on both, error banner with expandable traceback on jobs, and expandable traceback on handler error banners.

## Prompt
All changes are in `frontend/src/components/app-detail/handlers-tab.tsx`.

**Handler stats row** (`HandlerStatsRow` component, line 65):
- Add a "Successful" stat showing `listener.successful` count
- Add a "Cancelled" stat showing `listener.cancelled` count — only render when > 0
- Replace the single "Avg" duration with a min/avg/max display: show `listener.min_duration_ms` / `listener.avg_duration_ms` / `listener.max_duration_ms`. Use `formatDuration()` for each. When min/max are `null` (never fired), show "—"

**Handler error banner** (`ListenerDetail` component, around line 218):
- The existing error banner shows `last_error_type` and `last_error_message`
- Add an expandable traceback section below the message — show `listener.last_error_traceback` in a `<pre>` code block
- Use a disclosure pattern: collapsed by default, click to expand. Style with `--bg-sunken` for the traceback background
- Follow Geist Mono for the traceback text

**Job detail pane** (`JobDetail` component, line 266):
- Add an error banner matching the handler pattern: show `job.last_error_type`, `job.last_error_message`, expandable `job.last_error_traceback` when the job has errors (`job.failed > 0 || job.timed_out > 0`)
- This is new — jobs currently have no error banner at all
- Place it between the schedule chips and the stats row

**Job stats row** (`JobStatsRow` component, line 105):
- Add a "Successful" stat showing `job.successful` count
- The "Failed" and "Timed Out" stats already exist (lines 124-132) — ensure they are visually distinct (they already use separate entries, but verify the timed_out entry uses a different visual treatment than failed)
- Replace the single "Avg" duration with min/avg/max display matching the handler pattern. Handle `null` min/max as "—" (the "no executions yet" edge case — see design doc Edge Cases)

**Styles** in `frontend/src/global.css`:
- Add styles for the expandable traceback section: collapsed/expanded states, `--bg-sunken` background, Geist Mono font, `--r-sm` border radius
- Keep density compact — no excessive padding around the traceback

**Tests**: Update existing tests in the handlers-tab test file:
- Test that handler stats row renders successful count
- Test that cancelled count only renders when > 0
- Test that min/max duration render as "—" when null
- Test that job error banner renders with traceback
- Test that job stats row includes successful and separates failed/timed_out

## Focus
- `HandlerStatsRow` at line 65 currently renders: Last, Calls, Failed, Timed Out, Avg — add Successful between Calls and Failed, Cancelled after Timed Out (conditional)
- `JobStatsRow` at line 105 currently renders: Last, Runs, Failed, Timed Out, Avg — add Successful between Runs and Failed
- The frontend uses `formatDuration()` from `frontend/src/utils/format.ts` for duration display
- The `ListenerData` and `JobData` type aliases in `endpoints.ts` (lines 12, 18) auto-resolve from generated-types.ts — the new fields will be available after T01/T02 regenerate schemas
- The error banner pattern for handlers is at line 218 — use this as the template for the job error banner
- `--bg-sunken` is `#F4F4F1` light / `#15171B` dark (from design/context.md)
- The design context says "no left-border accents" — use indentation or background color for the traceback block, not a colored left border
- Test file is at `frontend/src/components/app-detail/__tests__/handlers-tab.test.tsx` or similar — find the exact path

## Verify
- [ ] FR#2: Job detail pane displays an expandable traceback for the last error
- [ ] FR#5: Handler stats row shows the successful invocation count
- [ ] FR#6: Handler stats row shows cancelled count when > 0, hidden when 0
- [ ] FR#7: Job stats row shows the successful execution count
- [ ] FR#8: Job stats row visually separates timed_out from failed (distinct stat entries)
- [ ] AC#4: Handler stats row includes successful and cancelled (conditional) counts
- [ ] AC#5: Job stats row includes successful count with separate timed_out and failed entries
- [ ] FR#17: Handler error banner includes an expandable traceback section
- [ ] AC#13: Handler error banner shows last_error_traceback in a collapsible code block
