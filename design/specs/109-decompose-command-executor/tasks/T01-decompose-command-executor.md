---
task_id: "T01"
title: "Split command_executor.py into execution_record_builder and execution_pipeline modules"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#6", "FR#7", "FR#8", "AC#1", "AC#2", "AC#3", "AC#4", "AC#5", "AC#6"]
---

## Target Files

- create: `src/hassette/core/execution_record_builder.py`
- create: `src/hassette/core/execution_pipeline.py`
- modify: `src/hassette/core/command_executor.py`

## Prompt

Read `src/hassette/core/command_executor.py` in full before starting (it is 1167 lines). This
task is a pure structural extraction — no behavior change, no signature change, no bundled
fixes. Single task, done atomically: this is not independently splittable across sub-tasks
because the pieces being extracted call each other directly (`persist_batch` calls
`handle_fk_violation` and `emit_completion_events`; `drain_and_persist` and `flush_queue` call
`persist_batch`), so a partial extraction would leave `command_executor.py` in a broken
intermediate state.

**Two concerns are extracted: record building and the batch pipeline. Timeout-warning rate
limiting (`log_timeout_rate_limited` and its two constants) is NOT extracted — it stays exactly
where it is today, as a `CommandExecutor` method at `command_executor.py:378-414` with its
constants at `:47-48`.** (This was originally planned as a third module,
`timeout_warning.py`, but the sketch-time challenge found a single-caller ~50-60 line module
unjustified — the two real extractions already bring `command_executor.py` under the 800-line
ceiling without it. Do not create `timeout_warning.py`.)

**Critical constraint — calling convention:** Every internal call site (inside `serve()`, inside
`_execute()`, and among the `execution_pipeline.py` functions calling each other) must go through
`executor.<method>(...)` / `self.<method>(...)` bound-method attribute lookup, **never** a bare
module-function call like `execution_pipeline.persist_batch(executor, ...)`. This is not a style
preference — it is required for correctness. Six existing tests monkeypatch these exact methods
as instance attributes before invoking a caller:
- `tests/unit/core/test_command_executor_pipeline_queue.py:155,290,320` — set
  `executor.persist_batch = fake_persist`, then call `await executor.drain_and_persist()`.
- `tests/unit/core/test_command_executor_pipeline_serve.py:67-68,112-113,146-147` — set
  `executor.drain_and_persist = fake_drain` (or similar), then call `await executor.serve()`.

Python's `self.foo(...)` / `executor.foo(...)` call syntax looks up `foo` on the instance's
`__dict__` first, which is exactly where these tests plant their fakes. A bare module-level call
(`persist_batch(executor, ...)` instead of `executor.persist_batch(...)`) skips that lookup
entirely and calls the real implementation, silently defeating the test's mock and making its
assertions fail. So: `execution_pipeline.py`'s own functions call each other via `executor.<name>(...)`,
and `command_executor.py`'s `serve()`/`_execute()` also call `self.<name>(...)` for every
extracted method. There is no fast-path exception for any method — not even ones with no
monkeypatch site today, since a future test could add one.

### 1. Create `src/hassette/core/execution_record_builder.py`

Move the body of `CommandExecutor.build_record()` (currently `command_executor.py:453-524`,
including its docstring and the `if result.status is None: raise RuntimeError(...)` guard) into
a standalone function:

```python
def build_execution_record(
    cmd: InvokeHandler | ExecuteJob,
    result: ExecutionResult,
    execution_start_ts: float,
    execution_id: str,
    *,
    session_id: int | None,
) -> ExecutionRecord:
```

`session_id` is now a required keyword parameter (the function no longer has `self.hassette` to
call `try_session_id()` on). Everything else — the `match cmd:` construction of `ExecutionRecord`
for `InvokeHandler` and `ExecuteJob` — is unchanged. Import only what this function needs
(`ExecutionRecord`, `SYNTHETIC_ORIGIN` from `hassette.core.execution_record`; `InvokeHandler`,
`ExecuteJob` from `hassette.commands`; `ExecutionResult` from `hassette.utils.execution`).

This function has no monkeypatch dependency (nothing in the test suite overrides `build_record`
as an instance attribute), so it is safe to call directly as a module-level function from
`command_executor.py`'s thin wrapper and from `_execute()`.

### 2. Create `src/hassette/core/execution_pipeline.py`

Move here, as module-level constructs (constants and standalone async/sync functions, each
taking `executor: "CommandExecutor"` as first argument):

- Constants (currently `command_executor.py:45-50`): `_MAX_RETRY_COUNT = 3`,
  `_BATCH_DRAIN_CAP = 100`, `_RETRY_BACKOFF_BASE_SECONDS = 1.0`,
  `_UNOWNED_WARN_RATE_LIMIT_SECS = 30.0`. (Do NOT move `_TIMEOUT_WARN_SUPPRESS_SECS`/
  `_TIMEOUT_WARN_CACHE_MAX` — those stay in `command_executor.py`, see above.)
- `RetryableBatch` dataclass (currently `command_executor.py:86-101`) — move as-is, including its
  docstring.
- `enqueue_record(executor, record: ExecutionRecord) -> None` — body from
  `command_executor.py:416-451`.
- `async def drain_and_persist(executor, first_item: ExecutionRecord | RetryableBatch | None = None) -> None`
  — body from `command_executor.py:807-870`. Where the original called `self.persist_batch(...)`,
  call `executor.persist_batch(...)` — the bound method (which is the thin wrapper defined on
  `CommandExecutor` in step 3, itself delegating back into this module). **Not** a bare
  `persist_batch(executor, ...)` call — see the calling-convention constraint above.
- `async def flush_queue(executor) -> None` — body from `command_executor.py:872-909`. Same
  convention: calls `executor.persist_batch(...)`.
- `async def persist_batch(executor, records: list[ExecutionRecord], *, retry_count: int = 0) -> None`
  — body from `command_executor.py:911-1016`. Where the original called
  `self.emit_completion_events(records)` and `self.handle_fk_violation(records)`, call
  `executor.emit_completion_events(records)` and `executor.handle_fk_violation(records)`.
- `async def handle_fk_violation(executor, records: list[ExecutionRecord]) -> None` — body from
  `command_executor.py:1133-1167`. Calls `executor.emit_completion_events(records)`.
- `async def emit_completion_events(executor, records: list[ExecutionRecord]) -> None` — body
  from `command_executor.py:1018-1065`. Reads `executor._clock`, `executor._last_unowned_warn_ts`,
  calls `executor.hassette.send_event(...)`.

Type `executor` via:

```python
import typing
if typing.TYPE_CHECKING:
    from hassette.core.command_executor import CommandExecutor
```

Do NOT use `from __future__ import annotations` (repo-wide ban — `rules/common/python.md`); the
string-literal forward ref `"CommandExecutor"` on each function's `executor` parameter is how the
rest of this codebase handles this (see `command_executor.py`'s existing `TYPE_CHECKING` block
for `Hassette`/`AppManifest`).

Import what these functions need: `sqlite3`, `time`, `asyncio`, `contextlib`, `dataclasses`
(`dataclass`, `field`, `replace as dataclass_replace`), `ExecutionRecord`,
`HassetteExecutionCompletedEvent`, etc. — check the original imports in `command_executor.py`
for the full set each moved function actually uses.

### 3. Rewrite `src/hassette/core/command_executor.py`

Remove everything moved in steps 1-2 (the four pipeline constants, `RetryableBatch`,
`build_record`'s body, `enqueue_record`'s body, `drain_and_persist`'s body, `flush_queue`'s body,
`persist_batch`'s body, `handle_fk_violation`'s body, `emit_completion_events`'s body). Do NOT
remove `log_timeout_rate_limited` or its two constants — leave that method and
`_TIMEOUT_WARN_SUPPRESS_SECS`/`_TIMEOUT_WARN_CACHE_MAX` exactly as they are today.

Add imports for the new modules:

```python
from hassette.core import execution_pipeline
from hassette.core.execution_record_builder import build_execution_record
from hassette.core.execution_pipeline import (
    RetryableBatch as RetryableBatch,
    _MAX_RETRY_COUNT as _MAX_RETRY_COUNT,
    _UNOWNED_WARN_RATE_LIMIT_SECS as _UNOWNED_WARN_RATE_LIMIT_SECS,
)
```

(The `as X` form on the last three is deliberate — it's ruff's recognized explicit-re-export
idiom, so it doesn't trip the unused-import lint. Confirmed direct-import call sites:
`tests/unit/core/test_command_executor_pipeline_queue.py:21` —
`from hassette.core.command_executor import _MAX_RETRY_COUNT, CommandExecutor, RetryableBatch`;
`tests/unit/core/test_command_executor_pipeline_serve.py:22` —
`from hassette.core.command_executor import _UNOWNED_WARN_RATE_LIMIT_SECS, CommandExecutor`.)

Replace the removed methods with thin delegating wrappers, in the same relative position in the
class body:

```python
def build_record(self, cmd, result, execution_start_ts, execution_id) -> ExecutionRecord:
    """Build a unified ExecutionRecord from the execution result and command.

    Delegates to execution_record_builder.build_execution_record().
    """
    return build_execution_record(
        cmd, result, execution_start_ts, execution_id, session_id=self.hassette.try_session_id()
    )

def enqueue_record(self, record) -> None:
    """Enqueue a record, dropping and logging if the queue is full. Delegates to execution_pipeline."""
    execution_pipeline.enqueue_record(self, record)

async def drain_and_persist(self, first_item=None) -> None:
    """Drain up to 100 queue items and persist them to DB. Delegates to execution_pipeline."""
    await execution_pipeline.drain_and_persist(self, first_item=first_item)

async def flush_queue(self) -> None:
    """Drain and persist ALL remaining items in the write queue. Delegates to execution_pipeline."""
    await execution_pipeline.flush_queue(self)

async def persist_batch(self, records, *, retry_count=0) -> None:
    """Write a batch of unified execution records to the DB. Delegates to execution_pipeline."""
    await execution_pipeline.persist_batch(self, records, retry_count=retry_count)

async def handle_fk_violation(self, records) -> None:
    """Handle an IntegrityError by re-inserting records with FK fallback. Delegates to execution_pipeline."""
    await execution_pipeline.handle_fk_violation(self, records)

async def emit_completion_events(self, records) -> None:
    """Emit bus topic events for persisted execution records. Delegates to execution_pipeline."""
    await execution_pipeline.emit_completion_events(self, records)
```

`log_timeout_rate_limited` is left in place, unchanged, at its original position in the class
body — it is not one of the removed methods.

Keep full type hints on these wrapper signatures matching the originals (the abbreviated
signatures above are for brevity in this prompt — copy the real parameter and return types from
the current `command_executor.py`).

`serve()` and `_execute()` are **not modified in their call sites** — they already call
`self.drain_and_persist(...)`, `self.flush_queue()`, `self.build_record(...)`,
`self.log_timeout_rate_limited(...)`, and `self.enqueue_record(...)` today, and that is exactly
what they must keep doing (per the calling-convention constraint above). The only thing that
changes about `serve()`/`_execute()` is that those method calls now dispatch into the thin
wrappers defined in step 3 above instead of directly into inline method bodies — no line in
`serve()` or `_execute()` itself needs to change.

Keep `ExecutionMarker`, `log_timeout_rate_limited()` and its constants, and everything else
(`__init__`, `config_log_level`, `serve()`, `execute()`, `_execute()`, `bind_execution_context()`,
`unbind_execution_context()`, `execute_handler()`, `execute_job()`, `invoke_error_handler()`,
`register_listener()`, `register_job()`, `upsert_app_manifest()`, `mark_job_removed()`,
`mark_job_status()`, `mark_listener_cancelled()`, `reconcile_registrations()`,
`record_blocking_event()`, `get_drop_counters()`, `get_error_handler_failures()`) exactly as they
are today — do not touch them.

### 4. Verify

Run the affected test files and the linters (see Verify section below). If pyright flags a
forward-reference issue on the `"CommandExecutor"` string annotations in `execution_pipeline.py`,
confirm the `TYPE_CHECKING` import block is present — this mirrors the pattern already used for
`Hassette`/`AppManifest` in the original `command_executor.py`.

Pay special attention to `test_command_executor_pipeline_queue.py` and
`test_command_executor_pipeline_serve.py` — these are the files with the monkeypatch sites the
calling-convention constraint protects. If any test in these two files fails with an assertion
about an empty/missing call list (e.g. `assert len(drain_calls) >= 2` failing with `drain_calls == []`),
that is the signature of a bare module-function call slipping in somewhere — grep
`execution_pipeline.py` for any call of the form `persist_batch(executor` / `drain_and_persist(executor` /
`flush_queue(executor` / `handle_fk_violation(executor` / `emit_completion_events(executor` (i.e.
missing the `.` after `executor`) and fix it to `executor.<method>(...)`.

## Verify

- [ ] FR#1/FR#2: `uv run pytest tests/unit/core/test_command_executor.py tests/unit/core/test_command_executor_error_handler.py tests/unit/core/test_command_executor_execution_id.py tests/unit/core/test_command_executor_pipeline_persist.py tests/unit/core/test_command_executor_pipeline_queue.py tests/unit/core/test_command_executor_pipeline_serve.py -v` passes with zero failures.
- [ ] AC#3: `uv run pytest tests/integration/test_command_executor.py tests/integration/test_command_executor_error_handler.py -v` passes with zero failures.
- [ ] AC#3: `git diff --stat -- tests/unit/core/test_command_executor*.py tests/integration/test_command_executor*.py tests/unit/core/_fixtures_command_executor.py` shows no output (zero test-file changes).
- [ ] FR#3/FR#5/FR#6: `grep -n "class RetryableBatch\|def build_execution_record\|def enqueue_record\|def drain_and_persist\|def flush_queue\|def persist_batch\|def handle_fk_violation\|def emit_completion_events" src/hassette/core/execution_record_builder.py src/hassette/core/execution_pipeline.py` shows each symbol defined in the expected file.
- [ ] FR#4: `grep -n "def log_timeout_rate_limited" src/hassette/core/command_executor.py` still shows it defined there (not moved); `ls src/hassette/core/timeout_warning.py` reports "No such file" (module was not created).
- [ ] FR#5/FR#8: `grep -nE "[^.](persist_batch|drain_and_persist|flush_queue|handle_fk_violation|emit_completion_events)\(executor" src/hassette/core/execution_pipeline.py` returns no matches (confirms no bare module-function call slipped in — every internal call is `executor.<method>(...)`, not `<method>(executor, ...)`).
- [ ] FR#6: `python -c "from hassette.core.command_executor import RetryableBatch, _MAX_RETRY_COUNT, _UNOWNED_WARN_RATE_LIMIT_SECS, ExecutionMarker"` succeeds with no ImportError.
- [ ] AC#1: `wc -l src/hassette/core/command_executor.py` reports under 800.
- [ ] AC#2: `wc -l src/hassette/core/execution_record_builder.py src/hassette/core/execution_pipeline.py` each report under 400.
- [ ] AC#4: `uv run nox -s dev` passes with no new failures relative to the pre-change baseline.
- [ ] AC#5: `prek -a && prek pyright -a --stage pre-push` passes clean.
- [ ] AC#6: `git status --porcelain -- src/hassette/core/bus_service.py src/hassette/core/scheduler_service.py src/hassette/bus/invocation.py` shows no output (untouched).
