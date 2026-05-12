---
task_id: "T02"
title: "Add ContextVar-based correlation IDs at dispatch"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#3", "AC#1", "AC#2", "AC#5"]
---

## Summary
Bind app identity and execution correlation IDs to every log record via structlog context vars. After this task, every log emitted during a handler invocation carries `execution_id`, `app_key`, `instance_name`, and `instance_index`. Lifecycle hook logs carry app identity without execution_id. Framework logs carry neither. The existing `CURRENT_EXECUTION_ID` context var is reused.

## Prompt
1. Add a structlog processor `add_execution_id` to the processor chain configured in T01's `enable_logging()`:
   ```python
   def add_execution_id(logger, method_name, event_dict):
       event_dict["execution_id"] = CURRENT_EXECUTION_ID.get(None)
       return event_dict
   ```
   Insert this in the shared processor list in `src/hassette/logging_.py`, after `TimeStamper` and before `wrap_for_formatter`.

2. Add a `logging.Filter` to the `hassette` logger directly (not the QueueHandler — that doesn't exist until T03). The Filter stamps `record.execution_id`, `record.app_key`, `record.instance_name`, `record.instance_index` from context vars, and `record.seq` from a monotonic counter (`itertools.count(1)`), before the record leaves the calling context. The `seq` counter MUST be assigned here (not in `LogCaptureHandler.emit()`) because with T03's QueueHandler pipeline, both `LogCaptureHandler` and `LogPersistenceHandler` receive the same record — `seq` must be present before enqueue so both handlers see it and the DB's `seq NOT NULL` constraint is satisfied. Move the `_seq` counter from `LogCaptureHandler` to this Filter. This Filter is critical for stdlib `logging.getLogger()` callers whose records bypass the structlog processor chain's contextvars merge. When T03 adds QueueHandler, the Filter stays on the logger (upstream of the QueueHandler), preserving the correct read timing.

3. Add context var binding in `src/hassette/core/command_executor.py`:
   - In `_execute_handler()` (around line 418), after `CURRENT_EXECUTION_ID.set(execution_id)`, add:
     ```python
     structlog.contextvars.bind_contextvars(
         app_key=cmd.listener.app_key,  # or however app_key is available on the cmd
         instance_name=<resolve from registration>,
         instance_index=<resolve from registration>,
     )
     ```
   - In the `finally` block (line 456), after `CURRENT_EXECUTION_ID.reset(token)`, add `structlog.contextvars.clear_contextvars()`.
   - Apply the same pattern to `_execute_job()` (around line 471/505).
   - Check what identity fields are available on `cmd: InvokeHandler` and `cmd: ExecuteJob`. The `cmd` objects carry listener/job references which have `app_key` and `instance_index` from registration. You may need to look at `register_listener()` (line 538) and `register_job()` (line 554) to see how these are passed.

4. Add context var binding in `src/hassette/core/app_lifecycle_service.py`:
   - In `initialize_instances()` (around line 117), before each lifecycle hook call (`on_initialize`, `on_ready`), bind `app_key`, `instance_name`, `instance_index` via `structlog.contextvars.bind_contextvars()`.
   - After each hook returns, call `structlog.contextvars.clear_contextvars()`.
   - Apply the same pattern in `shutdown_instances()` (around line 201) before `on_shutdown` calls.
   - These hooks are sequential (one app at a time), so there is no concurrency risk.

5. Update `LogEntry` dataclass in `src/hassette/logging_.py`:
   - Add fields: `execution_id: str | None = None`, `instance_name: str | None = None`, `instance_index: int | None = None`, `source_tier: str | None = None`
   - Update `to_dict()` to include the new fields.

6. Update `LogCaptureHandler.emit()` to populate the new `LogEntry` fields from the record's attributes (stamped by the Filter or processor chain).

7. Write unit tests:
   - Test that a log emitted during a mock handler execution carries `execution_id`, `app_key`, `instance_name`, `instance_index`.
   - Test that a log emitted outside execution context has `execution_id=None` and `source_tier="framework"`.
   - Test that `clear_contextvars()` prevents leakage between executions.
   - Test that a log emitted during a lifecycle hook carries `app_key` but not `execution_id`.
   - Test that a child task spawned via `asyncio.create_task()` during execution inherits the `execution_id` (verifies FR#3 — create a task inside a mock handler, emit a log from it, confirm the execution_id matches the parent).

## Focus
- `CURRENT_EXECUTION_ID` is defined at `src/hassette/context.py:17`. It uses `ContextVar.set()/reset()` — the correct pattern. The new context var bindings use structlog's `bind_contextvars()`/`clear_contextvars()` which is a different mechanism (dict-based, not token-based). Both coexist.
- `InvokeHandler` and `ExecuteJob` command types are in `src/hassette/core/commands.py` (or wherever the command types are defined). Check what fields carry app identity.
- `register_listener_meta()` at `command_executor.py:551` shows that `registration.app_key` and `registration.instance_index` are available at registration time. These same values need to be available at execution time via the `cmd` object.
- The `finally` block in `_execute_handler()` (line 456) and `_execute_job()` (line 505) is the critical cleanup point. `clear_contextvars()` MUST go here to prevent leakage.
- `app_lifecycle_service.py:303-311` is where instances are iterated and initialized. The `inst` object has `inst.instance_name`, `inst.app_config.instance_name`, and the `app_key` is passed as a parameter.

## Verify
- [ ] FR#1: Log records during handler execution carry execution_id matching the invocation's UUID
- [ ] FR#2: Log records outside execution context have execution_id=None and source_tier="framework"
- [ ] FR#3: A child task spawned via asyncio.create_task() during execution inherits the execution_id
- [ ] AC#1: Query logs by execution_id returns only that invocation's records, no cross-contamination
- [ ] AC#2: Framework-level records have no correlation identifier and source_tier="framework"
- [ ] AC#5: A stdlib logger produces structured output with correlation identifiers during handler execution
