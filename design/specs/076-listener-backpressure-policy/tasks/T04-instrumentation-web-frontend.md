---
task_id: "T04"
title: "Surface backpressure drops through the web API and frontend"
status: "done"
depends_on: ["T02", "T03"]
implements: ["FR#6", "FR#7", "AC#4", "AC#11"]
---

## Summary
Surface the `bp_dropped` counter end-to-end: widen `live_execution_counts` to a `NamedTuple` carrying
the backpressure count (reading `listener.invoker.bp_dropped`), migrate all of its consumers, add the
count and the configured policy to `ListenerWithSummary`, map them in `to_listener_with_summary`,
regenerate the OpenAPI/WS types, and render a "Backpressure dropped" cell in the UI showing a drop
*rate* (fraction of total), plus a policy chip when the policy is non-default.

## Target Files
- modify: `src/hassette/core/bus_service.py`
- modify: `src/hassette/web/models.py`
- modify: `src/hassette/web/mappers.py`
- modify: `src/hassette/web/routes/telemetry.py`
- modify: `src/hassette/web/routes/bus.py`
- modify: `src/hassette/test_utils/web_mocks.py`
- modify: `tests/integration/web_api/test_telemetry.py`
- modify: `frontend/src/components/app-detail/listener-detail.tsx`
- modify: `frontend/src/api/generated-types.ts`
- read: `design/specs/076-listener-backpressure-policy/design.md`
- read: `design/specs/076-listener-backpressure-policy/tasks/context.md`

## Prompt
Implement the instrumentation surface per the design doc's `## Architecture` §5 (the pipeline) and §7.

1. **Widen `live_execution_counts`** (`src/hassette/core/bus_service.py:232-253`): define a small
   `NamedTuple` (e.g. `class LiveCounts(NamedTuple): suppressed: int; dropped: int; bp_dropped: int`)
   and change the method to return `dict[int, LiveCounts]`, reading `guard.suppressed`, `guard.dropped`,
   and `listener.invoker.bp_dropped`. Keep the loop await-free — do NOT add an await.

2. **Migrate ALL consumers** of `live_execution_counts` (per "migrate callers then delete legacy API"):
   - `src/hassette/web/routes/telemetry.py:188` and `src/hassette/web/routes/bus.py:42` — they pass the
     dict through to `to_listener_with_summary`; update type annotations only (no unpack).
   - `src/hassette/web/mappers.py:188` — the only behavioral unpack: update
     `suppressed, dropped = (live_counts or {}).get(ls.listener_id, (0, 0))` to unpack three fields with
     a 3-wide default, update the `live_counts` type annotation (`mappers.py:175`), and map the new
     count onto the summary (step 3).
   - `tests/integration/web_api/test_telemetry.py:134` — replace `return_value={7: (2, 4)}` with the
     keyword-constructed `NamedTuple` (`{7: LiveCounts(suppressed=2, dropped=4, bp_dropped=0)}`).
   - `tests/integration/bus/test_execution_modes.py` —
     `test_live_execution_counts_snapshot_keyed_by_db_id` (~240-290) asserts the tuple shape; update it
     to the `NamedTuple`. (If T03 already touched this file, integrate cleanly.)
   - `src/hassette/test_utils/web_mocks.py:156` — returns `{}`; confirm it stays compatible.

3. **Web model** (`src/hassette/web/models.py:296`): add `backpressure_dropped_count: int = 0` and
   `backpressure: str` (the configured policy) to `ListenerWithSummary` (alongside `suppressed_count`/
   `dropped_count` at 334-335).

4. **Mapper** (`src/hassette/web/mappers.py`): in `to_listener_with_summary` (line 173) populate
   `backpressure_dropped_count` from the unpacked `bp_dropped` and `backpressure` from the persisted
   listener row.

5. **Regenerate types**: run `uv run python scripts/export_schemas.py --types` (regenerates
   `openapi.json`, `ws-schema.json`, `generated-types.ts`, `ws-types.ts`). In a worktree run
   `cd frontend && npm install` first if needed.

6. **Frontend** (`frontend/src/components/app-detail/listener-detail.tsx`): mirror lines 58-59 — push a
   "Backpressure dropped" cell when `listener.backpressure_dropped_count > 0`, but render it as a *rate*
   using `listener.total_invocations` as the denominator (e.g. `"40 (12%)"` from
   `bp_dropped / (total_invocations + bp_dropped)`). Show a policy chip only when `listener.backpressure`
   is non-default (`"drop_newest"`).

7. **Mapper unit test**: assert `bp_dropped > 0` flows into `backpressure_dropped_count` on the summary
   and that `suppressed_count`/`dropped_count` are unaffected.

## Focus
- `live_execution_counts` has exactly two production callers (`telemetry.py:188`, `bus.py:42`) that
  pass-through, one behavioral unpack (`mappers.py:188`), and two tests that fabricate the tuple. Miss a
  test caller and it asserts a stale shape. Construct the `NamedTuple` by KEYWORD in tests so a future
  fourth field can't shift positions.
- `listener.total_invocations` (model `models.py:305`, frontend `listener-detail.tsx:41`) is the
  drop-rate denominator — already present, no new field needed.
- The job path (`web/utils.py:42-43`) reads the guard directly and is NOT a consumer of
  `live_execution_counts` — do not touch it.
- This task modifies `bus_service.py` (live_execution_counts) and depends on T02 (the `bp_dropped`
  field) and T03 (the persisted `backpressure` for the chip) — both serialize the shared file.
- Frontend in a worktree: `node_modules` is not shared; `npm install` once before `npm run build`.

## Verify
- [ ] FR#6: `live_execution_counts` returns a `NamedTuple` carrying `bp_dropped` read from
  `listener.invoker.bp_dropped`; all callers (routes, mapper, both integration tests, mock) are migrated.
- [ ] FR#7: `ListenerWithSummary` carries `backpressure_dropped_count` and `backpressure`; the UI renders
  a distinct "Backpressure dropped" cell (as a rate) when `> 0` and a policy chip when non-default.
- [ ] AC#4: A listener with `bp_dropped > 0` returns a non-zero `backpressure_dropped_count` in its
  summary and the UI renders the cell; `suppressed_count`/`dropped_count` are unaffected.
- [ ] AC#11: The "Backpressure dropped" cell renders a *rate*
  (`bp_dropped / (total_invocations + bp_dropped)`, e.g. `"40 (12%)"`), not a bare count.
