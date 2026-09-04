# Context: Decompose command_executor.py into focused modules

## Problem & Motivation

`src/hassette/core/command_executor.py` is 1167 lines, past the repo's 800-line ceiling, and
mixes four concerns: execution-record building, timeout-warning rate limiting, the batch
drain/retry/persist pipeline, and the `CommandExecutor` service's own execute/dispatch/lifecycle
logic. GitHub issue #810.

## Key Decisions

1. Follow the module-level-function delegation pattern already used in this codebase for
   exactly this kind of split (`src/hassette/resources/lifecycle.py`,
   `src/hassette/resources/operations.py`): extract behavior into functions that take the
   `CommandExecutor` instance as an explicit first argument, typed via
   `if typing.TYPE_CHECKING: from hassette.core.command_executor import CommandExecutor`.
2. Do NOT move any state off the `CommandExecutor` instance. All instance attributes
   (`_write_queue`, `_dropped_overflow`, `_dropped_exhausted`, `_dropped_shutdown`,
   `_timeout_warn_timestamps`, `_clock`, `_last_capacity_warn_ts`, `_last_unowned_warn_ts`,
   `repository`, `task_bucket`, etc.) stay exactly where they are — tests construct
   `CommandExecutor` via `CommandExecutor.__new__()` and set these directly
   (`tests/unit/core/_fixtures_command_executor.py`).
3. `CommandExecutor` keeps every currently-public method as a bound method with an identical
   signature. Methods that move to module functions (`build_record`, `enqueue_record`,
   `drain_and_persist`, `flush_queue`, `persist_batch`, `handle_fk_violation`,
   `emit_completion_events`) become thin delegating wrappers that call the extracted function,
   passing `self` as the first argument. `log_timeout_rate_limited` does NOT move (see Decision 5).
4. **Calling convention (revised after sketch-time challenge, resolved 2026-09-04 — Finding 1,
   CRITICAL): every internal call site always goes through `self.<method>(...)` /
   `executor.<method>(...)` bound-method lookup, never a bare module-function call.** This
   applies inside `serve()`, inside `_execute()`, and among the `execution_pipeline.py` functions
   calling each other (`drain_and_persist`/`flush_queue` calling `persist_batch`; `persist_batch`
   calling `handle_fk_violation`/`emit_completion_events`; `handle_fk_violation` calling
   `emit_completion_events`). The original plan (bare module-function calls internally, bound
   method only for external/tested callers) was rejected: 6 existing tests monkeypatch
   `persist_batch`/`drain_and_persist` as instance attributes
   (`test_command_executor_pipeline_queue.py:155,290,320`,
   `test_command_executor_pipeline_serve.py:67-68,112-113,146-147`), and a bare module-function
   call bypasses instance-`__dict__` lookup entirely, silently defeating those mocks. There is no
   per-method fast-path exception — the one extra call frame this costs is negligible on a
   batched, SQLite-bound telemetry pipeline, and a uniform rule can't be silently broken by a
   future test adding a 7th monkeypatch site.
5. **`log_timeout_rate_limited` is NOT extracted (revised after sketch-time challenge, resolved
   2026-09-04 — Finding 2, HIGH).** It stays a `CommandExecutor` method exactly as today, along
   with its two constants (`_TIMEOUT_WARN_SUPPRESS_SECS`, `_TIMEOUT_WARN_CACHE_MAX`). The
   original plan (a dedicated `timeout_warning.py` module) was rejected: it's a single-caller,
   ~50-60-line extraction, and the two real extractions (record builder + pipeline) already bring
   `command_executor.py` to ~752 lines — under the 800-line ceiling without it.
6. Two new modules, one per concern:
   - `src/hassette/core/execution_record_builder.py` — `build_execution_record()`.
   - `src/hassette/core/execution_pipeline.py` — `RetryableBatch` + `enqueue_record()`,
     `drain_and_persist()`, `flush_queue()`, `persist_batch()`, `handle_fk_violation()`,
     `emit_completion_events()` + their four constants.
7. `RetryableBatch`, `_MAX_RETRY_COUNT`, `_UNOWNED_WARN_RATE_LIMIT_SECS` must remain importable
   from `hassette.core.command_executor` — re-export with the `from x import y as y` form (ruff's
   recognized explicit-re-export idiom, avoids an F401 unused-import warning).
8. `ExecutionMarker` is NOT part of this extraction — it stays defined in `command_executor.py`
   exactly as today. `block_io_guard.py` and `loop_watchdog.py` import it from there.

## Constraints

- **Zero test modification.** All 8 existing test files under `tests/unit/core/test_command_executor*.py`
  and `tests/integration/test_command_executor*.py` (~2800 lines total) must pass with no changes
  to the test files themselves. `git diff` on those 8 files must be empty at the end.
- Do not change any method's signature, return type, or behavior — this is a structural move
  only, not a redesign. No new features, no bug fixes bundled in.
- Do not move state off `CommandExecutor` instances (see Key Decision 2).
- Do not use `from __future__ import annotations` anywhere (repo-wide ban).
- Each new module should land under ~400 lines; `command_executor.py` must end under 800 lines.
- Do not touch `bus_service.py`, `scheduler_service.py`, or `bus/invocation.py` — their
  `.enqueue_record()` calls keep working unmodified because `enqueue_record` stays a
  `CommandExecutor` method.
