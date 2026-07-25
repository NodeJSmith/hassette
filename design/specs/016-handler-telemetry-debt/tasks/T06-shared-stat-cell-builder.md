---
task_id: "T06"
title: "Extract shared stat-cell builder + tests"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "AC#1"]
---

## Summary

Create a shared `buildCommonStatCells` function that consolidates the 8 structurally identical stat cells currently duplicated in `buildListenerStatsCells` and `buildJobStatsCells`. Each caller constructs a normalized `CommonStatInput` and appends domain-specific cells. Add a co-located unit test file for the builder.

## Target Files

- create: `frontend/src/components/app-detail/stat-cell-builders.ts`
- create: `frontend/src/components/app-detail/stat-cell-builders.test.ts`
- modify: `frontend/src/components/app-detail/listener-detail.tsx`
- modify: `frontend/src/components/app-detail/job-detail.tsx`
- read: `frontend/src/components/shared/detail-stats.tsx`
- read: `design/specs/016-handler-telemetry-debt/design.md`

## Prompt

Create `frontend/src/components/app-detail/stat-cell-builders.ts` with:

1. A `CommonStatInput` interface (see design doc's "Frontend: Shared stat-cell builder" section for the exact fields).

2. A `buildCommonStatCells(input: CommonStatInput): DetailStatsCell[]` function that returns the shared cells:
   - Total (label from `totalLabel`, value from `total`)
   - Failed (with `"err"` tone when > 0)
   - Err % (using `formatRate`, with `"err"` tone when failed > 0)
   - Avg (using `formatDurationOrDash`)
   - Last (using `lastLabel`)
   - Conditional cells (only when > 0): Timed Out (`"warn"`), Cancelled (`"cancel"`), Thread Leaked (`"warn"`), Suppressed (`"mute"`), Dropped (`"warn"`)

Update `listener-detail.tsx`:
- Replace `buildListenerStatsCells` with a call to `buildCommonStatCells` using `{ totalLabel: "Calls", total: listener.total_invocations, ... }`
- Append the Backpressure Dropped cell (with percentage math) after the common cells
- Import `buildCommonStatCells` and `CommonStatInput` from `./stat-cell-builders`

Update `job-detail.tsx`:
- Replace `buildJobStatsCells` with a call to `buildCommonStatCells` using `{ totalLabel: "Runs", total: job.total_executions, ... }`
- Handle the Next/Last cell: if `nextRunText` exists, pass it as `lastLabel`; otherwise pass the `lastExecutedLabel`
- **Splice Skipped after Cancelled, NOT at the end** — the current order is `Timed Out, Cancelled, Skipped, Thread Leaked, Suppressed, Dropped`. Find the Cancelled cell's index and insert Skipped immediately after it to preserve the existing row order. Appending at the end would reorder to `..., Dropped, Skipped` which is a visual regression.
- Import `buildCommonStatCells` and `CommonStatInput` from `./stat-cell-builders`

Create `stat-cell-builders.test.ts`:
- Test shared cell construction with representative input
- Test conditional cells appear only when count > 0
- Test tones are correct (err for failed, warn for timed_out, etc.)
- Test that the function returns only common cells — domain-specific cells are the caller's responsibility

## Focus

- The listener's `lastLabel` is simple: `listener.last_invoked_at ? lastInvokedLabel || "—" : "—"`. The job's is more complex: if `nextRunText` exists, use it; else fallback to `lastExecutedLabel`. Handle the Next/Last branching in the job caller, not in the shared builder.
- Import `formatRate` and `formatDurationOrDash` from `../../utils/format` in the new file.
- The `DetailStatsCell` type is imported from `../shared/detail-stats`.

## Verify

- [ ] FR#1: `buildCommonStatCells` exists and produces the shared cells for both listener and job callers
- [ ] FR#2: Backpressure Dropped (listener) and Skipped (job) are appended by callers, not by the shared builder
- [ ] AC#1: `cd frontend && npm run build && npm test` passes; existing stats-row assertions in `handlers-tab.test.tsx` (or its post-split successors) are unchanged and still pass
