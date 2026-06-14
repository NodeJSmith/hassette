---
task_id: "T03"
title: "Persist mode and expose live suppressed/dropped counts via the web API"
status: "planned"
depends_on: ["T02"]
implements: ["FR#14", "FR#15", "FR#16", "AC#1", "AC#10", "AC#11"]
---

## Summary

Persist the resolved `mode` as a single new column on the `listeners` table and surface it through the telemetry/web API. Expose the live (in-memory) suppressed/dropped counts from the guards via the bus, merged into the listener summary by `db_id`. Do NOT persist the counts — only `mode` is written to the DB. Regenerate the REST and WebSocket types so the new fields reach the frontend.

## Prompt

1. **Migration** — new `src/hassette/migrations_sql/003.sql`, append-only, following the `002.sql` one-statement form:
   ```sql
   ALTER TABLE listeners ADD COLUMN mode TEXT NOT NULL DEFAULT 'single';
   ```
   Only the `listeners` table. Do NOT add counter columns. Do NOT touch `scheduled_jobs` (that is issue #1027). The migration runner applies it via `PRAGMA user_version`; confirm `003` is picked up by `migration_runner.py`'s numeric-stem scan.

2. **Persist `mode` through the full registration chain** — `mode` is not on the registration object today, so four edits are required (the SQL alone is not enough — `_listener_insert_params` reads `registration.mode`, which does not exist yet):
   1. **`core/registration.py`** — add a `mode` field to the `ListenerRegistration` dataclass (around line 9).
   2. **`core/bus_service.py`** `_build_registration` (around line 166) — populate `mode=listener.options.mode` (as its string value) when constructing the `ListenerRegistration`, alongside the other `listener.options.*` fields.
   3. **`core/telemetry_repository.py`** `_listener_insert_params` (around line 78) — add `mode` to the params dict from `registration.mode`.
   4. **`core/telemetry_repository.py`** `register_listener` — add `mode` to the INSERT column list/VALUES and to the `ON CONFLICT(app_key, instance_index, name, topic) DO UPDATE SET` list, exactly like `debounce`/`once`.

   Because the resolved (tier-aware) mode is part of the registration object, this is correct config persistence (FR#14). Do NOT add any counter columns anywhere in this chain.

3. **Summary projection** — `core/telemetry/registration_queries.py`: select `l.mode` alongside the existing `l.debounce, l.throttle, l.once, l.priority` projection. NOTE: there are **two** such projection blocks (around lines 61 and 127) — add `l.mode` to **both**. Add `mode` to the `ListenerSummary` telemetry model in `core/telemetry_models.py`.

4. **Expose live counts from the bus** — `core/bus_service.py`: add a method that returns a snapshot of current per-listener `(suppressed, dropped)` counts keyed by listener `db_id`, read from each active listener's `ExecutionModeGuard`. The bus already holds every active listener in its router; each listener carries its `db_id` after registration. This is read-only, in-memory, no DB access (FR#15).

5. **Web models + mapper + routes** — `web/models.py` `ListenerWithSummary` (~line 295): add `mode: str`, `suppressed_count: int = 0`, `dropped_count: int = 0`. `web/mappers.py` `to_listener_with_summary` (~line 173): pass through `mode` from the DB summary and populate `suppressed_count`/`dropped_count` from the bus's live snapshot by `db_id` (default 0 when the listener has no live guard — e.g. retired). The mapper gains a parameter for the live snapshot; there are **two** call sites that must both pass it: `web/routes/telemetry.py:187` (`app_listeners`) and `web/routes/bus.py:41` — both return `ListenerWithSummary` and must obtain the live snapshot from the bus and pass it to the mapper. Counts never touch the DB.

6. **`restart` → cancelled rows** — no new code: a `restart`-cancelled task already flows through `CommandExecutor` and lands as a `status='cancelled'` execution row. Add an integration test asserting this (FR#16, AC#11).

7. **Regenerate types** — run `uv run python scripts/export_schemas.py --types` to regenerate all four artifacts: `frontend/openapi.json` and `frontend/ws-schema.json` (at the `frontend/` root) and `frontend/src/api/generated-types.ts` and `frontend/src/api/ws-types.ts` (the listener model flows over WebSocket too). Run `cd frontend && npm install` first if node_modules is absent in this worktree (see `.claude/rules/frontend-worktree.md`). Commit the regenerated artifacts.

8. **Tests** — integration:
   - Registering a listener with each mode persists it; the listener summary endpoint returns the mode (FR#14, AC#1).
   - After `single` drops and `queued` cap-drops, the listener-summary endpoint returns the live `suppressed_count`/`dropped_count` merged by `db_id` (FR#15, AC#10); a retired listener reports 0.
   - A `restart`-cancelled invocation produces a `status='cancelled'` execution row (FR#16, AC#11).
   - `mode` persists across re-registration and a mode-only change is detected by `diff_fields()` (covered by T02's `matches`/`diff_fields` change; assert the persisted value updates here).

Run the affected test files. Touching telemetry/DB and `core/` — run `uv run nox -s system` per CLAUDE.md.

## Focus

- `core/telemetry_repository.py` `register_listener` uses `ON CONFLICT(app_key, instance_index, name, topic) DO UPDATE` and already resets `cancelled_at = NULL` on conflict (lines ~313) — this is the pattern; add `mode` to both the insert and the `DO UPDATE SET`. CRITICAL: do NOT add the counters here; they are not config and must not be in the upsert.
- `web/models.py` `ListenerWithSummary` is at line ~295 with a conditional `cancelled` field at ~308; `web/mappers.py` `to_listener_with_summary` at ~173. The live-count merge by `db_id` is the one piece that spans bus→mapper→route — keep the snapshot read-only and cheap.
- `registration_queries.py` summary projection currently selects `l.debounce, l.throttle, l.once, l.priority` — `mode` slots in there.
- Schema freshness is checked by `tools/check_schemas_fresh.py` (pre-push) and CI git-diff on `generated-types.ts`/`ws-types.ts` — regenerate all four artifacts or CI fails. Do not hand-edit `ws-types.ts` (generated via `scripts/generate-ws-types.cjs`).
- The frontend rendering of these fields is T04; this task only makes them available in the API + generated types.
- `python.md`: no future annotations, `X | None`, top-level imports.

## Verify
- [ ] FR#14: `003.sql` adds the `mode` column; the registration upsert writes it; the listener-summary endpoint returns the persisted mode.
- [ ] FR#15: the listener-summary endpoint returns live `suppressed_count`/`dropped_count` sourced from the in-memory guards by `db_id` (0 for listeners with no live guard); no counter columns exist in the DB.
- [ ] FR#16: a `restart`-cancelled invocation appears in the `executions` table with `status='cancelled'`.
- [ ] AC#1: registering with each of the four modes persists the mode and it is queryable via the API.
- [ ] AC#10: after drops, the web API reflects the suppressed/dropped counts.
- [ ] AC#11: integration test confirms the `restart` cancellation row is `status='cancelled'`.
