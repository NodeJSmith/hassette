# Design: Decompose command_executor.py into focused modules

**Date:** 2026-09-04
**Status:** archived
**Mode:** sketch

## Problem

`src/hassette/core/command_executor.py` is 1167 lines — well past the repo's 800-line ceiling
(`CLAUDE.md` — Code Style) — and bundles record-building, the batch drain/retry/persist pipeline,
timeout-warning rate limiting, and the core execute/dispatch + lifecycle logic of the
`CommandExecutor` service itself all in one file. GitHub issue #810 tracks this.

## Goals

- Split the two concerns whose extraction actually earns its place — record building and the
  batch pipeline — into separate, focused modules under 400 lines each (matching the repo's
  typical file-size band). Timeout-warning rate limiting stays a `CommandExecutor` method
  (sketch-time challenge Finding 2: a single-caller ~50-60-line function isn't needed to hit the
  800-line target and gains nothing from its own module).
- Preserve `CommandExecutor`'s public method surface and every instance attribute exactly as-is
  — tests reach into private attributes (`_write_queue`, `_timeout_warn_timestamps`,
  `_dropped_overflow`, `_dropped_exhausted`, `_dropped_shutdown`, `_clock`,
  `_last_capacity_warn_ts`, `_last_unowned_warn_ts`) and call methods
  (`build_record`, `persist_batch`, `drain_and_persist`, `flush_queue`, `enqueue_record`,
  `handle_fk_violation`, `emit_completion_events`) directly on `CommandExecutor` instances.
- Zero test modifications. All 8 existing test files (5 unit + 2 integration, ~2800 lines) must
  pass unchanged.

## Functional Requirements

- **FR#1** `CommandExecutor` retains every currently-public method (`build_record`,
  `log_timeout_rate_limited`, `enqueue_record`, `drain_and_persist`, `flush_queue`,
  `persist_batch`, `handle_fk_violation`, `emit_completion_events`, plus all lifecycle/dispatch
  methods) as bound methods with identical signatures and behavior.
- **FR#2** `CommandExecutor` retains every instance attribute tests construct directly via
  `CommandExecutor.__new__()` (see `tests/unit/core/_fixtures_command_executor.py`), unchanged
  in name and semantics.
- **FR#3** Record-building logic (`build_record` and its per-`InvokeHandler`/`ExecuteJob`
  branches) moves to a new `execution_record_builder.py` module as a standalone function.
- **FR#4** Timeout-warning rate-limit logic (`log_timeout_rate_limited`, its two constants, its
  lazy-eviction/cap behavior over `_timeout_warn_timestamps`) is NOT extracted — it stays exactly
  where it is today, as a `CommandExecutor` method (sketch-time challenge Finding 2).
- **FR#5** The batch pipeline (`RetryableBatch`, `enqueue_record`, `drain_and_persist`,
  `flush_queue`, `persist_batch`, `handle_fk_violation`, `emit_completion_events`, and their
  constants `_MAX_RETRY_COUNT`, `_BATCH_DRAIN_CAP`, `_RETRY_BACKOFF_BASE_SECONDS`,
  `_UNOWNED_WARN_RATE_LIMIT_SECS`) moves to a new `execution_pipeline.py` module as standalone
  functions plus the `RetryableBatch` dataclass. Every internal call among these functions (and
  from `serve()`/`_execute()` into them) goes through `executor.<method>(...)` bound-method
  lookup, never a bare module-function call (sketch-time challenge Finding 1, CRITICAL — see
  "Calling convention" below).
- **FR#6** `RetryableBatch`, `_MAX_RETRY_COUNT`, and `_UNOWNED_WARN_RATE_LIMIT_SECS` remain
  importable from `hassette.core.command_executor` (re-exported), since
  `tests/unit/core/test_command_executor_pipeline_*.py` import them from that path today.
  `ExecutionMarker` stays defined in `command_executor.py` — it is not part of the extracted
  concerns and `block_io_guard.py`/`loop_watchdog.py` already import it from there.
- **FR#7** `command_executor.py` after the split is under 800 lines.
- **FR#8** No 6 existing tests that monkeypatch a `CommandExecutor` bound method as an instance
  attribute (`test_command_executor_pipeline_queue.py:155,290,320`,
  `test_command_executor_pipeline_serve.py:67-68,112-113,146-147`) observe any change in
  behavior — the monkeypatched method is still reached via `self.`/`executor.` attribute lookup
  from every internal caller.

## Acceptance Criteria

- **AC#1** `wc -l src/hassette/core/command_executor.py` reports under 800.
- **AC#2** `wc -l src/hassette/core/execution_record_builder.py src/hassette/core/execution_pipeline.py` each report under 400.
- **AC#3** `uv run pytest tests/unit/core/test_command_executor.py tests/unit/core/test_command_executor_error_handler.py tests/unit/core/test_command_executor_execution_id.py tests/unit/core/test_command_executor_pipeline_persist.py tests/unit/core/test_command_executor_pipeline_queue.py tests/unit/core/test_command_executor_pipeline_serve.py tests/integration/test_command_executor.py tests/integration/test_command_executor_error_handler.py` passes with zero failures, and `git diff` on those 8 files is empty.
- **AC#4** `uv run nox -s dev` (or the equivalent full unit+integration run) passes with no new failures.
- **AC#5** `prek -a && prek pyright -a --stage pre-push` passes clean.
- **AC#6** `git diff --stat` shows no changes to `bus_service.py`, `scheduler_service.py`, or `bus/invocation.py` — their `.enqueue_record()` calls keep working unmodified because `enqueue_record` stays a `CommandExecutor` method.

## Approach

Follow the module-level-function delegation pattern already established in this codebase for
exactly this kind of split — `src/hassette/resources/lifecycle.py` and
`src/hassette/resources/operations.py` extract `Resource`/`LifecycleMixin` behavior into
functions that take the resource as an explicit first argument (`mark_ready(resource, reason=...)`,
`handle_failed(resource, exc)`), typed against a narrow Protocol
(`_LifecycleHostP` in `hassette.resources.mixins`) and narrowed internally where mutable state is
needed. `src/hassette/core/telemetry/repository.py` shows the same idea one level simpler: pure
SQL-building functions extracted into `execution_queries.py` / `registration_queries.py` /
`summary_queries.py`, called from thin methods that stay on the main class.

This repo already recognizes the "pipeline" as a named concern — the test files are literally
`test_command_executor_pipeline_serve.py`, `test_command_executor_pipeline_persist.py`,
`test_command_executor_pipeline_queue.py` — so `execution_pipeline.py` is the natural home for
that logic, and the split mirrors an existing seam rather than inventing one.

**Why not a mixin class or a delegate object holding the pipeline's state:** the test fixtures
(`make_executor`, `init_executor` in `_fixtures_command_executor.py`) construct `CommandExecutor`
via `CommandExecutor.__new__()` and set `_write_queue`, `_dropped_overflow`, `_dropped_exhausted`,
`_dropped_shutdown`, `_timeout_warn_timestamps`, `_clock`, `_last_capacity_warn_ts`,
`_last_unowned_warn_ts` directly as instance attributes, and other tests read them back the same
way. Moving that state onto a separate delegate object (e.g. a `PersistencePipeline` the executor
holds a reference to) would require every one of those attribute accesses to change shape, which
violates the zero-test-modification constraint. State stays exactly where it is, on
`CommandExecutor` instances; only the *behavior* that operates on that state moves into module-level
functions taking the executor as an explicit argument, exactly like `lifecycle.py` does for
`Resource`.

### New modules

**`src/hassette/core/execution_record_builder.py`**
- `build_execution_record(cmd: InvokeHandler | ExecuteJob, result: ExecutionResult, execution_start_ts: float, execution_id: str, *, session_id: int | None) -> ExecutionRecord` — the body currently at `command_executor.py:453-524` (the `result.status is None` guard, the `match cmd` construction for `InvokeHandler`/`ExecuteJob`). Pure function — `session_id` is passed in explicitly instead of being read from `self.hassette.try_session_id()` inside the function, since the function no longer has `self`.

**`src/hassette/core/execution_pipeline.py`**
- `RetryableBatch` dataclass (moved from `command_executor.py:86-101`, unchanged).
- Constants `_MAX_RETRY_COUNT = 3`, `_BATCH_DRAIN_CAP = 100`, `_RETRY_BACKOFF_BASE_SECONDS = 1.0`, `_UNOWNED_WARN_RATE_LIMIT_SECS = 30.0` (moved from `command_executor.py:45-50`).
- `enqueue_record(executor: "CommandExecutor", record: ExecutionRecord) -> None` — body from `command_executor.py:416-451`.
- `drain_and_persist(executor: "CommandExecutor", first_item: ExecutionRecord | RetryableBatch | None = None) -> None` — body from `command_executor.py:807-870`. Calls `executor.persist_batch(...)` — through the bound-method attribute lookup, not a bare module-local call (see "Calling convention" below).
- `flush_queue(executor: "CommandExecutor") -> None` — body from `command_executor.py:872-909`. Calls `executor.persist_batch(...)`.
- `persist_batch(executor: "CommandExecutor", records: list[ExecutionRecord], *, retry_count: int = 0) -> None` — body from `command_executor.py:911-1016`. Calls `executor.emit_completion_events(records)` and `executor.handle_fk_violation(records)`.
- `handle_fk_violation(executor: "CommandExecutor", records: list[ExecutionRecord]) -> None` — body from `command_executor.py:1133-1167`. Calls `executor.emit_completion_events(records)`.
- `emit_completion_events(executor: "CommandExecutor", records: list[ExecutionRecord]) -> None` — body from `command_executor.py:1018-1065`. Reads `executor._clock`, `executor._last_unowned_warn_ts`, `executor.hassette.send_event(...)`.

**`log_timeout_rate_limited` is NOT extracted.** It stays a `CommandExecutor` method exactly as
today (`command_executor.py:378-414`, including the `_TIMEOUT_WARN_SUPPRESS_SECS`/
`_TIMEOUT_WARN_CACHE_MAX` constants at `:47-48`). A single-caller, ~50-60-line function extracted
into its own module bought nothing — the two real extractions (`execution_record_builder.py` +
`execution_pipeline.py`) already bring `command_executor.py` to ~752 lines, under the 800-line
ceiling without touching this function at all (sketch-time challenge Finding 2, resolved
2026-09-04: drop the extraction).

### Calling convention: always through the bound method, never a bare module-function call

Every internal call site — inside `serve()`, inside `_execute()`, and among the extracted
`execution_pipeline.py` functions calling each other — goes through `self.<method>(...)` /
`executor.<method>(...)` attribute lookup, exactly like every external caller (tests,
`bus_service.py`, etc.). There is no separate "internal callers skip the wrapper" convention.

This was the design's original mistake, caught by the sketch-time challenge (Finding 1,
CRITICAL, resolved 2026-09-04): calling the bare module function directly
(`execution_pipeline.persist_batch(executor, ...)`) instead of through the instance
(`executor.persist_batch(...)`) skips Python's instance-`__dict__` attribute lookup entirely.
Six existing tests monkeypatch these exact methods as instance attributes
(`executor.persist_batch = fake_persist` in `test_command_executor_pipeline_queue.py`;
`executor.drain_and_persist = fake_drain` in `test_command_executor_pipeline_serve.py`) and
expect the code under test to call the overridden version. A bare module-function call would
silently defeat every one of those overrides — the real implementation runs instead of the test
double, and the assertions fail. Paying one extra call frame per invocation (on a batched,
SQLite-bound telemetry pipeline — not a hot loop) is the correct trade against that risk; there
is no carve-out for any method, so a future test that monkeypatches `build_record` or
`log_timeout_rate_limited` can't silently reintroduce this bug either.

### `command_executor.py` after the split

Keeps: `ExecutionMarker` dataclass, the `CommandExecutor` class definition with `__init__`,
`config_log_level`, `serve()`, `get_drop_counters()`, `get_error_handler_failures()`, `execute()`,
`_execute()`, `bind_execution_context()`, `unbind_execution_context()`, `execute_handler()`,
`execute_job()`, `invoke_error_handler()`, `register_listener()`, `register_job()`,
`upsert_app_manifest()`, `mark_job_removed()`, `mark_job_status()`, `mark_listener_cancelled()`,
`reconcile_registrations()`, `record_blocking_event()`, and — unchanged from today —
`log_timeout_rate_limited()` and its two constants (see above: not extracted).

Adds thin delegating methods that preserve today's call surface for the record-builder and
pipeline extractions only:

```python
def build_record(self, cmd, result, execution_start_ts, execution_id) -> ExecutionRecord:
    return execution_record_builder.build_execution_record(
        cmd, result, execution_start_ts, execution_id, session_id=self.hassette.try_session_id()
    )

def enqueue_record(self, record) -> None:
    execution_pipeline.enqueue_record(self, record)

async def drain_and_persist(self, first_item=None) -> None:
    await execution_pipeline.drain_and_persist(self, first_item=first_item)

async def flush_queue(self) -> None:
    await execution_pipeline.flush_queue(self)

async def persist_batch(self, records, *, retry_count=0) -> None:
    await execution_pipeline.persist_batch(self, records, retry_count=retry_count)

async def handle_fk_violation(self, records) -> None:
    await execution_pipeline.handle_fk_violation(self, records)

async def emit_completion_events(self, records) -> None:
    await execution_pipeline.emit_completion_events(self, records)
```

`serve()` and `_execute()` keep calling `self.drain_and_persist(...)`, `self.flush_queue()`,
`self.build_record(...)`, `self.log_timeout_rate_limited(...)`, and `self.enqueue_record(...)`
exactly as today — no internal call site changes to bare module-function calls anywhere (see
"Calling convention" above).

Re-export at the top of `command_executor.py` for the names tests import directly from this
module:

```python
from hassette.core.execution_pipeline import (
    RetryableBatch as RetryableBatch,
    _MAX_RETRY_COUNT as _MAX_RETRY_COUNT,
    _UNOWNED_WARN_RATE_LIMIT_SECS as _UNOWNED_WARN_RATE_LIMIT_SECS,
)
```

(The `as X` re-export form is deliberate — it's the convention ruff recognizes as an intentional
re-export rather than an unused import (F401), so no `# noqa` is needed.)

## Dependencies and Assumptions

None beyond the existing test suite as the correctness oracle — this is a pure structural move
with no behavior change, so "all existing tests pass unmodified" is both the acceptance
criterion and the safety net (see `rules/common/refactoring-discipline.md` — Pin Behavior First).
No new test coverage is required by this change; the existing 2800 lines of tests already pin
the behavior being moved.

## Changed Files

- `create`: `src/hassette/core/execution_record_builder.py` — `build_execution_record()`.
- `create`: `src/hassette/core/execution_pipeline.py` — `RetryableBatch`, `enqueue_record()`, `drain_and_persist()`, `flush_queue()`, `persist_batch()`, `handle_fk_violation()`, `emit_completion_events()` + their constants. Internal calls among these functions go through `executor.<method>(...)`, not bare module-function calls.
- `modify`: `src/hassette/core/command_executor.py` — remove the record-building and batch-pipeline code (`log_timeout_rate_limited` and its constants stay put, unmoved), add thin delegating methods for the record-builder and pipeline extractions, re-export `RetryableBatch`/`_MAX_RETRY_COUNT`/`_UNOWNED_WARN_RATE_LIMIT_SECS`. `serve()` and `_execute()` keep calling `self.method(...)` for every extracted method — no internal call site switches to a bare module-function call.

## Addendum

[None yet — sketch is in draft.]
