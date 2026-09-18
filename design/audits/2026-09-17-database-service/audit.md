# Audit Findings
**Target:** src/hassette/core/database_service.py and related infrastructure
**Date:** 2026-09-17
**Format-version:** 4
**Likely-invalid:** 0

## Finding 1: Six DatabaseConfig fields are silently ignored — users can set them but they do nothing

**Severity:** HIGH | **Type:** Tech Debt | **Raised-by:** Audit Analysis (1/1)
**Classification:** User-directed
**visibility:** presented
**disposition:** pending

**Problem:** `config/models.py:80-95` declares `retention_interval_seconds`, `size_failsafe_interval_seconds`, `size_failsafe_max_iterations`, `size_failsafe_delete_batch`, `size_failsafe_vacuum_pages`, `max_consecutive_heartbeat_failures`, and `heartbeat_interval_seconds` on `DatabaseConfig`. None are read anywhere — `database_service.py:31-49` hardcodes the same values as module-level constants. These fields pass validation, appear in generated config schema, and silently do nothing if set.

**Why-it-matters:** A user who tunes `size_failsafe_max_iterations` in their config expecting it to take effect gets silent misconfiguration. Worse than not having the option — it presents six configurable knobs that are actually inert.

**Recommendation:** Option A

**Options:**
- **A** *(recommended)*: Wire the config fields — replace the module-level constants with reads from `self.hassette.config.database.*`
- **B**: File as issue — track for future work
- **C**: Skip — noted, no action this session

**Why A:** This is the cheapest fix with the clearest user-facing impact — six one-line changes from constant to config read.

## Finding 2: submit() has no timeout — most callers hang indefinitely on a full or wedged queue

**Severity:** HIGH | **Type:** Structural | **Raised-by:** Audit Analysis (1/1)
**Classification:** User-directed
**visibility:** presented
**disposition:** pending

**Problem:** `submit()` (`database_service.py:522-547`) calls `await queue.put(...)` with no timeout. Only `update_heartbeat()` wraps its `submit()` call in a 30s `asyncio.timeout` — every other caller (`register_listener`, `register_job`, `persist_execution_batch`, `SessionManager.create_session` on the startup critical path) hangs indefinitely if the queue is full or the worker is wedged.

**Why-it-matters:** A slow disk or burst of execution batches fills the queue, and registrations/session creation hang the startup critical path. The heartbeat timeout (which was explicitly designed for this scenario, per comments at `:51-58`) only protects one caller — the same risk exists everywhere `submit()` is called.

**Recommendation:** Option A

**Options:**
- **A** *(recommended)*: Add a configurable default timeout to `submit()` itself (e.g., `timeout: float = 30.0`), so all callers get bounded waits without each needing their own `asyncio.timeout` wrapper
- **B**: File as issue — track for future work
- **C**: Skip — noted, no action this session

**Why A:** The pattern is already proven by `update_heartbeat`'s manual timeout — this generalizes it to all callers.

## Finding 3: TOCTOU race between update_heartbeat guard and submit() around force_terminal teardown

**Severity:** HIGH | **Type:** Structural | **Raised-by:** Audit Analysis (1/1)
**Classification:** User-directed
**visibility:** presented
**disposition:** pending

**Problem:** `update_heartbeat()` (`database_service.py:703-706`) checks `if self._db_write_queue is None: return` before calling `submit()`, but `submit()` re-reads `self._db_write_queue` rather than using a captured local. If `_force_terminal()` runs `detach_write_queue()` (setting `_db_write_queue = None`) between the guard and `submit()`'s `.put()`, an `AttributeError` is raised. `update_heartbeat()`'s except clauses only catch `TimeoutError` and `(sqlite3.Error, OSError, ValueError)` — the `AttributeError` propagates uncaught, crashing `serve()`.

**Why-it-matters:** `_force_terminal()` is documented as reachable from a timeout-driven path while `serve()` may still be running. This race produces a crash instead of a counted heartbeat failure.

**Recommendation:** Option A

**Options:**
- **A** *(recommended)*: Have `submit()` capture `queue = self._db_write_queue` as a local at entry, raise a clear `RuntimeError` if None (matching `enqueue()`'s pattern), and have `update_heartbeat` catch that `RuntimeError` as a heartbeat failure
- **B**: File as issue — track for future work
- **C**: Skip — noted, no action this session

**Why A:** Small, localized fix that eliminates the TOCTOU window by construction.

## Finding 4: No priority distinction between telemetry and operational writes — heartbeat restart conflates "busy" with "wedged"

**Severity:** MEDIUM | **Type:** Structural | **Raised-by:** Audit Analysis (1/1)
**Classification:** User-directed
**visibility:** presented
**disposition:** pending

**Problem:** Heartbeat, registrations, execution batches, log records, retention cleanup, and size failsafe all share one FIFO queue. A backlog of legitimate work (execution batch retries, size failsafe iterations) can starve the heartbeat, triggering a full `DatabaseService` restart that conflates "worker is genuinely stuck" with "worker is merely busy."

**Why-it-matters:** An unnecessary restart propagates disruption app-wide — every other service depends on `DatabaseService` via `submit()`/`enqueue()`. Prior art (HA Recorder) documents this as the ceiling of the single-queue pattern, but hassette's volume is well below HA's entity-update rates — the more immediate fix is ensuring the failsafe doesn't monopolize the worker (see Finding 5).

**Recommendation:** Option B

**Options:**
- **A**: Separate queues for operational vs telemetry writes
- **B** *(recommended)*: File as issue — the immediate symptom (failsafe blocking the worker) is addressed by Finding 5; priority queues are a future lever if volume grows
- **C**: Skip — noted, no action this session

**Why B:** Prior art confirms the single-queue shape is correct for hassette's scale. The priority problem is real but its most acute trigger (failsafe monopolizing the worker) has a simpler fix.

## Finding 5: Size failsafe blocks the write worker for up to 30 iterations with no yield

**Severity:** MEDIUM | **Type:** Structural | **Raised-by:** Audit Analysis (1/1)
**Classification:** User-directed
**visibility:** presented
**disposition:** pending

**Problem:** `_check_size_failsafe()` runs inline on the single write worker — up to 10 iterations × 3 priority tiers, each with a DELETE batch + `incremental_vacuum(100)` + `wal_checkpoint(TRUNCATE)`. All I/O-bound operations that block every other queued write (including heartbeat) for their duration. No time budget, no yield-back-to-queue between iterations.

**Why-it-matters:** A database far over its size limit ties up the write worker uninterrupted, stacking heartbeat and registration writes behind it. This is the most concrete trigger for Finding 4's "busy confused with wedged" problem.

**Recommendation:** Option B

**Options:**
- **A**: Add a yield-back (`await asyncio.sleep(0)` or re-enqueue continuation) between iterations to let other queued writes drain
- **B** *(recommended)*: File as issue — the current sketch (spec 111) already extracts the per-tier loop; a yield point is a natural follow-up once the extraction lands
- **C**: Skip — noted, no action this session

**Why B:** The sketch decomposition is the prerequisite — adding a yield point to the current monolithic method is harder than adding it to the extracted `_run_failsafe_tier`.

## Finding 6: run_size_failsafe() is the least-tested public method — zero direct or indirect coverage

**Severity:** MEDIUM | **Type:** Test Gap | **Raised-by:** Audit Analysis (1/1)
**Classification:** User-directed
**visibility:** presented
**disposition:** pending

**Problem:** `run_size_failsafe()` (`database_service.py:919-925`) — the enqueue wrapper for `_check_size_failsafe()` — is never called by any test. The `serve()` branch that calls it (lines 367-370) is also never exercised — `test_serve_runs_heartbeat_and_retention` only patches `_HEARTBEAT_INTERVAL_SECONDS`/`_RETENTION_INTERVAL_SECONDS`, not `_SIZE_FAILSAFE_INTERVAL_SECONDS`. The guard clauses (`_db is None`, `_db_write_queue is None`) are untested.

**Why-it-matters:** The public entry point and its integration with `serve()` have zero coverage. Only the underlying `_check_size_failsafe()` is tested directly, skipping the enqueue/guard path.

**Recommendation:** Option B

**Options:**
- **A**: Add test coverage for `run_size_failsafe()` and its serve-loop branch now
- **B** *(recommended)*: File as issue — the sketch already plans new failsafe tests; this should be tracked alongside
- **C**: Skip — noted, no action this session

**Why B:** The sketch's T02 already adds failsafe tests; this gap is best addressed in that same effort.

## Finding 7: _insert_log_records rollback/re-raise branch has zero test coverage

**Severity:** MEDIUM | **Type:** Test Gap | **Raised-by:** Audit Analysis (1/1)
**Classification:** User-directed
**visibility:** presented
**disposition:** pending

**Problem:** `_insert_log_records()` (`database_service.py:927-941`) has a `BEGIN`/`executemany`/`commit` block with `except Exception: await db.rollback(); raise`. No test forces `executemany` to fail. All 4 tests in `test_log_records.py::TestInsertLogRecords` exercise only the happy path.

**Why-it-matters:** The rollback+re-raise is the only error recovery for log persistence — if it silently stops working (e.g., a future edit wraps the inner call), log records could partially commit.

**Recommendation:** Option B

**Options:**
- **A**: Add a test now
- **B** *(recommended)*: File as issue — this is the same class of gap as Finding 2 in the sketch's challenge (rollback pin test), can be addressed together
- **C**: Skip — noted, no action this session

**Why B:** Pattern matches the rollback pin test the sketch already requires for retention — should be tracked as a sibling issue.

## Finding 8: session_manager.py bypasses the write queue, reaching directly into db.execute/commit/rollback

**Severity:** MEDIUM | **Type:** Pattern Drift | **Raised-by:** Audit Analysis (1/1)
**Classification:** User-directed
**visibility:** presented
**disposition:** pending

**Problem:** `session_manager.py` reaches past `submit()` to call `self._database_service.db.execute/commit/rollback` directly in several places — bypassing the single-writer queue that every other caller uses.

**Why-it-matters:** Violates the single-writer invariant that the write queue exists to enforce. Under concurrent access, these direct calls could race with queued writes on the same connection.

**Recommendation:** Option B

**Options:**
- **A**: Refactor session_manager to use submit() for all writes
- **B** *(recommended)*: File as issue — needs investigation of whether the direct access is intentional (e.g., for startup-time ordering) before changing it
- **C**: Skip — noted, no action this session

**Why B:** May be deliberate (session creation happens before the write queue is fully up). Needs investigation, not a blind refactor.

## Finding 9: rollback() can mask the original error if BEGIN itself failed

**Severity:** MEDIUM | **Type:** Fragility | **Raised-by:** Audit Analysis (1/1)
**Classification:** User-directed
**visibility:** presented
**disposition:** pending

**Problem:** Both `_do_run_retention_cleanup` (line 828) and `_insert_log_records` (line 940) call `rollback()` unconditionally in their `except` blocks. If the exception originated from `BEGIN` itself failing (e.g., "cannot start a transaction within a transaction"), `rollback()` on a connection with no open transaction can raise a new exception, masking the original diagnostic.

**Why-it-matters:** The original error (which would explain the root cause) is replaced by a less informative rollback error. The `logger.exception` call at line 829 may never execute.

**Recommendation:** Option B

**Options:**
- **A**: Wrap `rollback()` in its own try/except to preserve the original error
- **B** *(recommended)*: File as issue — small fix but needs to be done carefully to avoid swallowing the rollback error entirely
- **C**: Skip — noted, no action this session

**Why B:** The fix is straightforward but the sketch is already touching these exact methods — better tracked as a companion issue.

## Finding 10: Skipped retention/failsafe passes have no health signal

**Severity:** MEDIUM | **Type:** Structural | **Raised-by:** Audit Analysis (1/1)
**Classification:** User-directed
**visibility:** presented
**disposition:** pending

**Problem:** `run_retention_cleanup()` and `run_size_failsafe()` use `enqueue()` (fire-and-forget). If the queue is full, they log an error and return `False` — but no counter tracks consecutive skips (unlike `_consecutive_heartbeat_failures` for heartbeats). Multiple skipped retention passes in a row are invisible to any health signal.

**Why-it-matters:** A persistently full queue silently stops retention cleanup, letting the database grow without bound — exactly the failure mode the size failsafe exists to catch, but the failsafe itself can also be skipped by the same mechanism.

**Recommendation:** Option B

**Options:**
- **A**: Add a consecutive-skip counter analogous to `_consecutive_heartbeat_failures`
- **B** *(recommended)*: File as issue — good improvement but not blocking current work
- **C**: Skip — noted, no action this session

**Why B:** Valuable observability improvement, not a correctness bug. Track alongside the other failsafe improvements.
