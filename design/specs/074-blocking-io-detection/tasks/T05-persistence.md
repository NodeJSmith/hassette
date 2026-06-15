---
task_id: "T05"
title: "Persist blocking events to the telemetry database"
status: "planned"
depends_on: ["T03", "T04"]
implements: ["FR#10", "FR#11", "AC#7", "AC#8"]
---

## Summary
Record every detected blocking event (from both tiers) to a new `blocking_events` telemetry table. Add the SQL migration, a `BlockingEvent` model, and a repository write path, then wire both the Tier 1 watchdog and the Tier 2 guard to emit one row per event. Events whose owner can't be resolved are recorded with framework-tier attribution, not dropped. No query API or UI this round.

## Prompt
Implement persistence per `design/specs/074-blocking-io-detection/design.md`, `## Architecture` → "Persistence" and `## Migration`.

1. **Migration** — add `src/hassette/migrations_sql/004.sql` creating `blocking_events`, following the `executions` table conventions in `001.sql` (INTEGER PK autoincrement, `session_id` FK, `source_tier` CHECK `('app','framework')`). Columns: `id`, `session_id` FK, `app_key`, `instance_name`, `instance_index`, `execution_id`, `tier` (CHECK `('watchdog','monkeypatch')`), `primitive` (nullable — Tier 2 only), `source_location` (nullable), `stall_duration_ms` (nullable — Tier 1 only), `detected_ts`, `source_tier`. Add indexes on `detected_ts`, `(app_key, detected_ts)`, and `session_id`. The migration runner auto-discovers numeric `*.sql` stems — no wiring needed.
2. **Model** — add a `BlockingEvent(BaseModel)` to `src/hassette/core/telemetry_models.py`, sibling to `SlowHandlerRecord`, with fields matching the table.
3. **Repository write** — add a write path in the telemetry repository (`src/hassette/core/telemetry_repository.py`) following the existing record→insert pattern used for other telemetry rows. One insert per event.
4. **Wire both tiers** — have the Tier 1 watchdog (T03) and Tier 2 guard (T04) hand their detected events to the repository write path. Tier 1 rows carry `tier='watchdog'`, `stall_duration_ms`, null `primitive`; Tier 2 rows carry `tier='monkeypatch'`, `primitive`, `source_location`, null `stall_duration_ms`.
5. **Sentinel/unknown owner** — when the marker yields no resolvable app owner, record the row with `source_tier='framework'` (and `app_key` null) rather than dropping it. Follow the sentinel-filtering test pattern in `CLAUDE.md` (records with unregistered IDs are handled deliberately — here, unresolved owners are recorded as framework, not silently dropped).
6. **Respect `IGNORE`** — when resolved behavior is `IGNORE` for the owning app, emit no warning AND write no row (the suppression is total).
7. **Tests** — integration tests in `tests/integration/database` (or alongside existing telemetry tests). One detected event → exactly one row with correct tier/attribution/columns (AC#7). An event with an unresolved owner → one row with `source_tier='framework'` (AC#8). Use the real DB via the test harness; follow existing telemetry-persistence test patterns.

## Focus
- Migrations: `src/hassette/migrations_sql/` has `001.sql`–`003.sql`; `_collect_migrations` (referenced from `core/database_service.py:440`) scans for numeric stems and PRAGMA `user_version` drives application. `004.sql` is picked up automatically.
- Schema precedent is **`executions`**, not `log_records` — only `executions` has a `session_id` FK and `source_tier` CHECK. Copy its column/constraint/index style, with ONE exception: `executions` carries a *second* CHECK tying `source_tier='framework'` to a sentinel `app_key`. Do NOT copy that — `blocking_events` uses a nullable `app_key` for unresolved owners, so its only `source_tier` constraint is `CHECK (source_tier IN ('app','framework'))`.
- `src/hassette/core/telemetry_repository.py` is the write path; `telemetry_models.py` holds `BaseModel` records (`Execution`, `SlowHandlerRecord`, `LogRecord`, ...). Match their field/typing conventions.
- The IGNORE-suppresses-row property (no warning AND no row for an `ignore` app) is owned end-to-end by T06/AC#6 — T05 just honors the resolver's `IGNORE` by not writing; do not add a separate AC#6 verify here.
- The DB write must not run on a path that itself blocks the loop — telemetry writes already go through the existing async/queue machinery; reuse it rather than writing synchronously from the watchdog/guard hot path.
- `session_id` must reference a valid session; reuse however other telemetry rows obtain the current session id (grep the repository for `session_id`).
- Capture full test output to a tmp file; do NOT run `pytest -n auto`.

## Verify
- [ ] FR#10: Each detected blocking event writes one `blocking_events` row with app attribution, tier, timestamp, and the tier-appropriate columns (duration for watchdog, primitive+source for monkeypatch).
- [ ] FR#11: An event whose owner is unresolved is recorded with `source_tier='framework'`, not dropped — asserted by test.
- [ ] AC#7: A single detected event produces exactly one row with the correct columns for its tier.
- [ ] AC#8: An unresolved-owner event produces one row attributed to the framework tier.
