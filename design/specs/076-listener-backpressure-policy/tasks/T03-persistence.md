---
task_id: "T03"
title: "Persist the backpressure policy on the listeners table"
status: "done"
depends_on: ["T01", "T02"]
implements: ["FR#8", "AC#5", "AC#8", "AC#9"]
---

## Summary
Persist the configured policy as a `listeners.backpressure` column for parity with `mode`, so the UI
can show a listener's policy even at zero drops. Adds migration 008, the field on the
`ListenerRegistration` struct, the value in `build_registration`, and — critically — the column in the
INSERT statement, its parameter dict, AND the `ON CONFLICT ... DO UPDATE SET` upsert clause in
`telemetry_repository.py`. Integration tests pin both first-registration and the replace-upsert path.

## Target Files
- create: `src/hassette/migrations_sql/008.sql`
- modify: `src/hassette/core/registration.py`
- modify: `src/hassette/core/bus_service.py`
- modify: `src/hassette/core/telemetry_repository.py`
- modify: `tests/integration/bus/test_execution_modes.py`
- read: `src/hassette/migrations_sql/003.sql`
- read: `design/specs/076-listener-backpressure-policy/design.md`
- read: `design/specs/076-listener-backpressure-policy/tasks/context.md`

## Prompt
Implement persistence per the design doc's `## Architecture` §6 and `## Migration`.

1. **Migration** (`src/hassette/migrations_sql/008.sql`): mirror `003.sql` exactly:
   ```sql
   ALTER TABLE listeners ADD COLUMN backpressure TEXT NOT NULL DEFAULT 'block'
       CHECK (backpressure IN ('block', 'drop_newest'));
   ```
   The CHECK lists only the two implemented values — do NOT add `'keep_latest'`.

2. **Registration struct** (`src/hassette/core/registration.py`): add
   `backpressure: str = DEFAULT_BACKPRESSURE_POLICY` to `ListenerRegistration` (alongside `mode` at
   line 64). Import `DEFAULT_BACKPRESSURE_POLICY` from `hassette.types.enums`.

3. **build_registration** (`src/hassette/core/bus_service.py`): add
   `backpressure=listener.options.backpressure.value` to the `ListenerRegistration(...)` construction in
   `build_registration` (alongside `mode=listener.options.mode.value` at line 229).

4. **SQL — three coordinated edits in `src/hassette/core/telemetry_repository.py`:**
   - `_listener_insert_params` (function at line 82): add `"backpressure": registration.backpressure`
     to the returned dict (alongside `"mode": registration.mode` at line 109).
   - `INSERT INTO listeners` (statement at line 292): add the `backpressure` column to the column list
     (line ~297) and `:backpressure` to the VALUES binds (line ~303).
   - `ON CONFLICT ... DO UPDATE SET` (clause at line 306): add `backpressure = excluded.backpressure`
     (alongside `mode = excluded.mode` at line 317). **This is the critical edit** — without it, a
     `replace` re-registration with a changed policy keeps the stale value.

5. **Tests** (`tests/integration/bus/test_execution_modes.py` or the appropriate listeners-persistence
   integration test file): add (a) AC#5 — register a `DROP_NEWEST` listener, assert the `listeners` row
   reads `'drop_newest'` and a `BLOCK`/omitted listener reads `'block'`; (b) AC#9 — register `name=X`
   with `BLOCK`, then re-register `name=X` with `DROP_NEWEST` via `if_exists="replace"`, assert the row
   now reads `'drop_newest'` (exercises the `DO UPDATE SET` clause). AC#8 (migration applies on fresh +
   upgraded DB) is covered by the migration-runner test suite — verify the runner picks up `008.sql`.

## Focus
- `003.sql` (adds `listeners.mode`) is the exact precedent for the migration. `006.sql` adds the same
  pattern to `scheduled_jobs.mode`.
- The SQL lives in `telemetry_repository.py`, NOT `bus_service.py` — this is a common trap. The flow is
  `build_registration` (bus_service) → `register_listener(reg)` → `_listener_insert_params` + INSERT
  (telemetry_repository).
- The `DO UPDATE SET` clause (line 306-319) already updates `debounce`, `throttle`, `priority`, `mode`,
  etc. — append `backpressure = excluded.backpressure` in the same style.
- This task modifies `bus_service.py` (build_registration); it depends on T02 to serialize the shared
  file. The gate branch (T02) and build_registration (T03) are different functions in the same file.
- The migration runner applies numbered SQL files in order; `008.sql` is the next number (existing:
  001–007).
- **Shared file with T04:** T04 also edits `tests/integration/bus/test_execution_modes.py` (it migrates
  the `live_execution_counts` tuple assertion to a `NamedTuple`). T04 depends on this task and runs
  after it, so write your new AC#5/AC#9 tests normally — T04 will integrate, not overwrite. Keep your
  additions clearly separated so the later merge is clean.

## Verify
- [ ] FR#8: The configured policy is persisted on the `listeners` row at registration and updated on a
  `replace` re-registration; rows written before the migration default to `'block'`.
- [ ] AC#5: Integration test asserts the persisted `backpressure` value is `'drop_newest'` after
  registering a DROP_NEWEST listener and `'block'` for a default one.
- [ ] AC#8: The migration runner applies `008.sql` cleanly on a fresh DB and a DB upgraded from the
  prior schema; the column defaults to `'block'`.
- [ ] AC#9: Integration test asserts that re-registering with `if_exists="replace"` and a changed policy
  leaves the `listeners` row reading the new value (exercises `DO UPDATE SET`).
