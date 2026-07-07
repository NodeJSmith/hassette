---
task_id: "T05"
title: "Add skipped status to frontend UI and where= documentation"
status: "done"
depends_on: ["T04"]
implements: ["FR#13", "AC#7"]
---

## Summary
Update the frontend to display the `'skipped'` execution status and predicate description in the job detail UI. Add documentation for the `where=` parameter to the scheduler docs pages with tested snippet files. Update docstrings on `Scheduler.schedule()` and all convenience methods.

## Target Files
- modify: `frontend/src/utils/status.ts`
- modify: `frontend/src/utils/status.test.ts`
- modify: `frontend/src/components/app-detail/job-detail.tsx`
- modify: `docs/pages/core-concepts/scheduler/methods.md`
- modify: `docs/pages/core-concepts/scheduler/index.md`
- create: `docs/pages/core-concepts/scheduler/snippets/scheduler_where_state_check.py`
- create: `docs/pages/core-concepts/scheduler/snippets/scheduler_where_job_arg.py`
- modify: `src/hassette/scheduler/scheduler.py` (docstrings only)
- read: `frontend/src/components/shared/status-shape.tsx` (reference for StatusKind values)
- read: `src/hassette/web/routes/scheduler.py` (verify routes use JobSummary directly — no separate model to update)
- read: `frontend/src/components/app-detail/job-detail.tsx` (reference for buildJobStatsCells pattern)
- read: `docs/pages/core-concepts/scheduler/snippets/scheduler_run_daily.py` (reference for snippet conventions)
- read: `design/specs/003-scheduler-where-predicates/design.md`

## Prompt
Update the frontend and documentation:

**1. `frontend/src/utils/status.ts` — `executionStatusKind()` (line 35):**
Add a branch for `'skipped'` before the `console.warn` fallback:
```typescript
if (status === "skipped") return "mute";
```
`"mute"` renders as a ring shape in `StatusShape` — neutral visual weight appropriate for a non-error skip.

**2. `frontend/src/utils/status.test.ts`:**
Add a test case verifying `executionStatusKind("skipped")` returns `"mute"`.

**3. `frontend/src/components/app-detail/job-detail.tsx` — `buildJobStatsCells()` (line 84):**
- Add a `Skipped` cell to the stats grid. Follow the pattern of existing cells (e.g., `Cancelled`). Use `job.skipped` as the value and `"mute"` as the tone.
- If `job.predicate_description` or `job.human_description` is non-null, display the predicate description in the job metadata section. Use `human_description` when available (more readable), fall back to `predicate_description`. Check how the listener detail page displays predicate descriptions for the visual pattern to follow.

**4. `docs/pages/core-concepts/scheduler/index.md`:**
Add a "Conditional Execution" section after the existing overview content. Include:
- Brief explanation of `where=` for conditional job execution
- A basic example using a snippet include (the zero-arg state check snippet)
- A note about telemetry visibility of skipped executions
- Link to `methods.md` for full parameter documentation

Follow the voice guide (`voice-guide.md`) — system-as-subject for concept pages, no "you" outside getting-started content.

**5. `docs/pages/core-concepts/scheduler/methods.md`:**
Add `where=` parameter documentation to the method signatures section. Include:
- Parameter type and default
- Behavior description (evaluated at dispatch time, fail-open on exceptions)
- One-shot vs recurring skip semantics
- Example snippets via `--8<--` includes

**6. Snippet files:**
Create two snippet files following existing conventions (see `scheduler_run_daily.py` for the pattern):

`scheduler_where_state_check.py` — a minimal App showing `where=` with a zero-arg lambda checking HA state:
```python
# --8<-- [start:where_state]
await self.scheduler.run_daily(
    self.morning_routine,
    at="07:00",
    name="morning_routine",
    where=lambda: self.states.get("binary_sensor.home_occupied").is_on,
)
# --8<-- [end:where_state]
```

`scheduler_where_job_arg.py` — a minimal App showing `where=` with a one-arg predicate receiving the `ScheduledJob`:
```python
# --8<-- [start:where_job]
await self.scheduler.run_every(
    self.check_entity,
    minutes=5,
    name="entity_check",
    kwargs={"entity_id": "sensor.temperature"},
    where=lambda job: job.kwargs["entity_id"] != "sensor.disabled",
)
# --8<-- [end:where_job]
```

**7. Docstrings:**
Update docstrings on `Scheduler.schedule()` and all convenience methods in `scheduler.py` to include the `where` parameter description. Keep it brief — one line describing the parameter type and behavior, referencing the docs page for details.

## Focus
- The `status.test.ts` file has existing test cases for all four current statuses — follow the exact same assertion pattern for `'skipped'`.
- `job-detail.tsx` now contains a `RunNowButton` component (lines 39-82, added by #1216) with loading/error state. The `buildJobStatsCells()` function starts at line 84, after `RunNowButton`. Be aware of the new imports (`triggerJob`, `useSignal`, `Button`, `IconPlay`, `Spinner`, `layoutStyles`) already present in the file.
- Gap found: `frontend/src/utils/status.test.ts` needs a `'skipped' → 'mute'` test case.
- For `job-detail.tsx`, check how `listener-detail.tsx` displays `predicate_description`/`human_description` — the job detail page should mirror that visual pattern.
- Snippet files must be valid Python that Pyright can type-check. Use real entity IDs (`binary_sensor.home_occupied`, `sensor.temperature`), not placeholder names.
- Lines in snippet files must be under 80 characters (docs content area is narrow).
- The scheduler index page should use `--8<--` includes for code examples, not inline code blocks.
- Follow `voice-guide.md` — concept pages use declarative statements and system-as-subject voice. No "you" in the index page's Conditional Execution section.
- This task modifies a rendered `.tsx` file (`job-detail.tsx`). The repo's CI enforces screenshot evidence for frontend changes (`tools/frontend/check_pr_screenshots.py`). If `job-detail.tsx` is one of the documented screenshots in `docs/screenshots.yml`, regenerate the affected `docs/_static/web_ui_*.png` via `uv run python scripts/capture_screenshots.py --only <name>`.

## Verify
- [ ] FR#13: The `Skipped` count cell appears in the job detail stats grid
- [ ] AC#7: The job detail page displays the `skipped` count and predicate description (human_description when available)
