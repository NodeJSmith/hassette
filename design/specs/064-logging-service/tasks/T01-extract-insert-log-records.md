---
task_id: "T01"
title: "Move insert_log_records to DatabaseService"
status: "planned"
depends_on: []
implements: ["FR#7", "AC#8"]
---

## Summary
Extract `insert_log_records`, `_LOG_COLUMNS`, and `_LOG_INSERT_SQL` from `TelemetryRepository` to `DatabaseService` as a private method. This is the foundational data-layer change that subsequent tasks depend on — LogPersistenceHandler will call `db_service.enqueue(db_service._insert_log_records(batch))` instead of routing through TelemetryRepository.

## Prompt
1. Read `src/hassette/core/telemetry_repository.py` lines 688–720 — the `insert_log_records` method and `_LOG_COLUMNS`/`_LOG_INSERT_SQL` constants.

2. Add to `src/hassette/core/database_service.py`:
   - Move `_LOG_COLUMNS` and `_LOG_INSERT_SQL` constants (place near top, after existing constants)
   - Add `async def _insert_log_records(self, records: list[dict]) -> None` method. Copy the implementation from TelemetryRepository but access `self.db` directly instead of `self._db_service.db`. Keep the method private (prefix `_`) matching the existing `_do_run_retention_cleanup`/`_check_size_failsafe` pattern.

3. Remove from `src/hassette/core/telemetry_repository.py`:
   - Delete the `insert_log_records` method
   - Delete `_LOG_COLUMNS` and `_LOG_INSERT_SQL` constants

4. Update `src/hassette/logging_.py` — change `LogPersistenceHandler._flush()`:
   - Change `db_service.enqueue(repository.insert_log_records(b))` to `db_service.enqueue(db_service._insert_log_records(b))`
   - Remove the `_repository` attribute and all references to it in `_flush()` and `set_database()`

5. Update tests:
   - `tests/unit/core/test_log_records.py` — change the `repo` fixture: create a mock `DatabaseService` with `.db = db` and call `db_service._insert_log_records(records)` directly. Update all `await repo.insert_log_records(...)` calls.
   - `tests/unit/core/test_log_records_retention.py` — same fixture change pattern.

6. Run tests: `timeout 300 uv run pytest tests/unit/core/test_log_records.py tests/unit/core/test_log_records_retention.py -v`

## Focus
- The method is private (`_insert_log_records`) — matching `_do_run_retention_cleanup`, `_check_size_failsafe` pattern in database_service.py.
- `LogPersistenceHandler` still has `set_database()` in this task — that removal happens in T03. Only remove the `_repository` parameter from `set_database()` and the `_repository` attribute.
- The `_flush()` method uses `call_soon_threadsafe` and accesses `db_service` from a background thread — ensure the new call pattern is thread-safe (it is: `enqueue()` uses `put_nowait` which is thread-safe on asyncio queues).
- `test_log_records_retention.py` also uses `repo.insert_log_records()` (4 call sites) — don't miss it.

## Verify
- [ ] FR#7: `DatabaseService._insert_log_records(records)` exists and batch-inserts records into the `log_records` table
- [ ] AC#8: Test suite for insert_log_records passes with equivalent behavior via DatabaseService
