---
task_id: "T04"
title: "Display trigger_mode in execution UI and update docs"
status: "done"
depends_on: ["T02", "T03"]
implements: ["FR#9", "FR#10", "AC#9", "AC#10"]
---

## Summary
Add visual indicators for manually triggered executions in the frontend: a "manual" badge in execution table rows and a `trigger_mode` line item in the execution detail panel. Also update the docs page that covers the handlers tab and regenerate the affected screenshot. This task depends on both T02 (backend endpoint + generated types with `trigger_mode`) and T03 (Run Now button visible in screenshot).

## Target Files
- modify: `frontend/src/components/shared/execution-table.tsx`
- modify: `frontend/src/components/shared/detail-panel.tsx`
- modify: `frontend/src/components/shared/execution-table.test.tsx`
- modify: `docs/pages/web-ui/debug-handler.md`
- regenerate: `docs/_static/web_ui_app_detail_handlers.png`
- read: `frontend/src/components/shared/badge.tsx`
- read: `frontend/src/api/generated-types.ts`
- read: `docs/screenshots.yml`

## Prompt
### Manual badge in execution table

In `frontend/src/components/shared/execution-table.tsx`, add a `<Badge variant="info" size="sm">manual</Badge>` to execution rows where `trigger_mode === "manual"`. Position it in the same area as the existing "thread leaked" badge (line 117-119), after the status indicators.

The `ExecutionRecord` interface (lines 20-31) will already have `trigger_mode` from the regenerated types in T02. If the generated types use a different field name, match it. Check `frontend/src/api/generated-types.ts` to confirm the field name.

Follow the existing badge pattern:
```tsx
{row.trigger_mode === "manual" && (
  <Badge variant="info" size="sm" aria-label="manually triggered">
    manual
  </Badge>
)}
```

### trigger_mode in detail panel

In `frontend/src/components/shared/detail-panel.tsx`, add `trigger_mode` as its own line item, rendered independently of the existing `trigger_context_id`-gated context block (lines 34-39). The context block is gated on `context` being truthy, and `trigger_context_id` is always `None` for job executions — placing `trigger_mode` inside that conditional would mean it never renders for jobs.

Add a new prop for `trigger_mode` (or read it from the execution record if passed directly). Render it unconditionally when the value is present:

```tsx
{triggerMode && (
  <div>
    <dt>Trigger Mode</dt>
    <dd>{triggerMode}</dd>
  </div>
)}
```

Update the `DetailPanel` call site in `execution-table.tsx` (line 133) to pass `trigger_mode` from the execution record.

### Frontend tests

In `frontend/src/components/shared/execution-table.test.tsx`, add tests:

- Execution row renders "manual" badge when `trigger_mode` is `"manual"`
- Execution row does NOT render "manual" badge when `trigger_mode` is `null`/`undefined`
- Detail panel renders trigger_mode value when present

Follow the existing test patterns in that file for rendering execution rows and checking badge visibility.

### Documentation update

Update `docs/pages/web-ui/debug-handler.md` to mention:
- The "Run Now" button in the job detail panel walkthrough
- The "manual" badge in the execution table that distinguishes manual triggers from scheduled runs

Keep the additions brief and consistent with the page's existing voice and structure.

### Screenshot regeneration

Regenerate the handlers tab screenshot. First check `docs/screenshots.yml` for the entry name (expected: `web_ui_app_detail_handlers`). Then run:

```bash
uv run python scripts/capture_screenshots.py --only web_ui_app_detail_handlers
```

This starts a demo stack, navigates to the handlers tab, and captures the screenshot. The demo stack must have a manually triggered job execution to show the "manual" badge — this may require triggering a job via the API during the capture run. Check `docs/screenshots.yml` for any `wait_for` or setup conditions.

If the demo stack doesn't produce a visible "manual" badge in the screenshot (because no manual trigger has been fired), note this as a limitation — the badge will appear in the screenshot only after a manual trigger has been executed in the demo environment.

## Focus
- `Badge` component (line 7 of `badge.tsx`) supports variants: `success`, `danger`, `warning`, `info`, `neutral`. Use `info` for "manual".
- The "thread leaked" badge (lines 117-119 of `execution-table.tsx`) is the only existing badge in rows — follow its exact pattern for consistency.
- `DetailPanel` props interface (line 6 of `detail-panel.tsx`) includes `context` (optional object with `triggerContextId`/`triggerOrigin`), `executionId`, `status`, `durationMs`, `errorType`, `errorMessage`, `errorTraceback`, and `testId`. Adding `triggerMode` as a new optional prop is the cleanest approach.
- The `context` block in `DetailPanel` (lines 34-39) uses `<dt>`/`<dd>` inside a definition list. Match this structure for `triggerMode`.
- `debug-handler.md` documents the exact UI surface this task changes. Keep the voice consistent with the existing page — see `.claude/rules/voice-guide.md` for voice rules.
- The screenshot manifest is at `docs/screenshots.yml`. The capture tool (`scripts/capture_screenshots.py`) starts its own demo stack with Docker — it needs Docker and Playwright installed.

## Verify
- [ ] FR#9: Execution table rows display a "manual" badge for `trigger_mode="manual"` executions
- [ ] FR#10: Execution detail panel shows `trigger_mode` value as its own line item when present
- [ ] AC#9: "manual" badge is visually distinguishable in execution rows
- [ ] AC#10: Detail panel renders trigger_mode independently of the context block
