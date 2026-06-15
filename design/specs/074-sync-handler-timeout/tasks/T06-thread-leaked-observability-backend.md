---
task_id: "T06"
title: "Record thread-leaked observability on execution records"
status: "planned"
depends_on: ["T04"]
implements: ["FR#3", "AC#1"]
---

## Summary
Make the timeout leak observable end-to-end on the backend: at the timeout site, check whether the sync handler's worker thread (captured in T04) is still alive; if so, log a distinct "thread still alive" signal and set a new `thread_leaked` flag on the execution record. Add the column via migration `004.sql`, thread the field through the `ExecutionRecord` dataclass, `build_record`, and the telemetry insert path. A timeout that fired before the worker started (no captured thread) is not a leak and must not be flagged.

## Prompt
1. **Migration** — create `src/hassette/migrations_sql/004.sql` adding `thread_leaked INTEGER NOT NULL DEFAULT 0` to the `executions` table (the table DDL with the `status` CHECK constraint and reserved columns is in `001.sql:82-107`). Do NOT reuse a reserved column (`trigger_mode`/`retry_count`/`attempt_number`) and do NOT extend the `status` CHECK set. Follow the one-statement style of `003.sql`. The expected-head version is computed from the highest-numbered file (`database_service.py:434-447`), so adding `004.sql` is sufficient.

2. **Dataclass** — add `thread_leaked: bool = False` (or `int`, matching how other boolean-ish columns like `is_di_failure` are typed) to `ExecutionRecord` (`src/hassette/core/execution_record.py:12-105`), with a docstring.

3. **Build path** — populate `thread_leaked` in `command_executor.build_record` (`command_executor.py:359-420`, both the handler branch `:384-402` and the job branch `:404-420`) from the `ExecutionResult`/timeout outcome.

4. **Persistence** — add `thread_leaked` to `telemetry_repository._execution_insert_params` (`telemetry_repository.py:18-52`) so it flows into `_EXECUTION_INSERT_COLUMNS`/`_EXECUTION_INSERT_SQL` (`:58-65`). Confirm whether the column tuple is auto-derived from the params dict or hard-coded, and update accordingly.

5. **The liveness check** — at the timeout handling in `command_executor._execute` (`:265-288`), after the timeout is observed, read the worker-thread reference captured by T04's `run_in_thread` and check `thread.is_alive()`. If the reference is set AND alive, mark the result as thread-leaked (so `build_record` sets `thread_leaked=True`) and emit a distinct log line at the existing timeout-warning site distinguishing "thread still alive" from a clean timeout. If the reference is unset (worker never started — the "not-started" timeout), do NOT flag it. Keep the command layer decoupled from executor internals — it reads only a thread reference and `is_alive()`, never the pool.

Tests:
- A sync handler that blocks past its timeout produces a record with `thread_leaked=1`, distinguishable from a clean timeout (`thread_leaked=0`), verified against the real dedicated executor (not a mock).
- The not-started case (timeout fires before `_call` runs) yields `thread_leaked=0`.
- The record round-trips through persistence with the new column (write + read back).
- Adapt any test asserting on the executions schema or `ExecutionRecord` shape — search `tests/unit/core/test_unified_execution.py` and `tests/integration/web_api/test_execution_endpoint.py` and any fixture constructing `ExecutionRecord`.

Run affected files with `uv run pytest <files> -v` (never `-n auto`). This touches `src/hassette/core/` — run `uv run nox -s system` before done.

## Focus
- The capture mechanism is defined by T04 (ContextVar or shared cell). Consume exactly what T04 exposes; if T04 used a ContextVar set inside `_call`, confirm it is readable at the `_execute` timeout site, otherwise use the explicit cell T04 provides. Do not re-derive a future handle.
- Keep `thread_leaked` separate from `status` — `status='timed_out'` stays unchanged (preserves FR#9 / the caller contract). The leak is an orthogonal flag.
- `ExecutionRecord` is frozen (`@dataclass(frozen=True)`); construct with the new field, don't mutate.
- The persistence column tuple at `telemetry_repository.py:58-62`: verify whether it is derived from the params dict keys or listed manually — a manual list must be updated or the INSERT will desync from the DDL.
- The leak check is best-effort (the thread may finish microseconds later); a brief grace is acceptable. Do not block the loop waiting on the worker. Concretely: prefer a single immediate `is_alive()` read at the timeout site — do NOT `await asyncio.sleep(...)` then re-read, which would extend the handler's observed timeout window and muddy `duration_ms`. If a grace is truly needed, keep it to a sub-millisecond, non-blocking check, and document why.

## Verify
- [ ] FR#3: a timed-out sync handler whose worker thread is still alive logs a distinct "thread still alive" signal and sets `thread_leaked=1` on the execution record; a not-started timeout sets `thread_leaked=0`.
- [ ] AC#1: the leaked-thread execution record is distinguishable from a clean timeout and persists through the DB (new `004.sql` column), verified against the real dedicated-executor path.
