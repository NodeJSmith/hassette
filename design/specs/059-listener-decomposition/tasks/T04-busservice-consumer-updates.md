---
task_id: "T04"
title: "Update BusService and CommandExecutor for sub-struct field access"
status: "done"
depends_on: ["T01", "T02", "T03"]
implements: ["FR#10", "AC#9", "AC#10"]
---

## Summary
Update all BusService methods and CommandExecutor to read from sub-structs instead of flat Listener fields. Replace `BusService._create_cancel_listener()` with calls to `Listener.create_cancel_listener()`. Wire DurationConfig.attach_timer() in `add_listener()`. Update the test harness mock executor. Add the ListenerRegistration parity test.

## Prompt
Read the design doc sections "BusService consumer updates", "CommandExecutor._execute_handler()", "Test harness updates", and "ListenerRegistration parity test".

**Step 1: Update BusService.add_listener()** in `src/hassette/core/bus_service.py`:
- Duration timer wiring: change from `listener._duration_timer = DurationTimer(...)` to `listener.duration_config.attach_timer(task_bucket, make_cancel_sub, on_cancel)` when `listener.duration_config is not None`
- The `make_cancel_sub` closure now calls `Listener.create_cancel_listener()` instead of `Listener.create()`
- `app_key` access: `listener.app_key` → `listener.identity.app_key`
- `owner_id` access: `listener.owner_id` → `listener.identity.owner_id`

**Step 2: Update BusService._dispatch():**
- Duration check: `if listener.duration is not None and listener._duration_timer is not None` → `if listener.duration_config is not None` (then assert `listener.duration_config.timer` inside)
- Handler dispatch: `listener.dispatch(invoke_fn)` → `listener.invoker.dispatch(invoke_fn)`
- Once check: `listener.once` → `listener.options.once`
- Entity ID: `listener.entity_id` → `listener.duration_config.entity_id`

**Step 3: Update BusService._immediate_fire_task():**
- `listener.duration` → `listener.duration_config.duration`
- `listener.is_attribute_listener` → `listener.duration_config.is_attribute_listener`
- `listener.entity_id` → `listener.duration_config.entity_id`
- `listener._duration_timer` → `listener.duration_config.timer`
- `listener.immediate` → `listener.duration_config.immediate`

**Step 4: Update BusService._register_then_add_route():**
- ListenerRegistration construction: read identity fields from `listener.identity.*`, options from `listener.options.*`
- `listener.once` → `listener.options.once`

**Step 5: Update BusService._make_tracked_invoke_fn():**
- `listener.timeout_disabled` → `listener.options.timeout_disabled`
- `listener.timeout` → `listener.options.timeout`
- Error handler: `listener.invoker._app_error_handler_resolver` (intentional cross-module private access — BusService is the framework orchestrator that wires and reads this field; the underscore signals "not user-facing", not "not framework-accessible")

**Step 6: Replace _create_cancel_listener():**
- The method body is replaced by calling `Listener.create_cancel_listener()` (from T01)
- The cancel subscription's `Subscription` construction passes an already-resolved Future as `registration_task`
- The existing `assert main_listener._duration_timer is not None` must be updated — after refactor, the timer is on `main_listener.duration_config._timer` and is set during `attach_timer()`
- **Timing note (critical):** The `make_cancel_sub` callback is passed INTO `DurationTimer.__init__` but is NOT called during `__init__`. It is called during `DurationTimer.start()`, which happens later in `BusService._dispatch()` or `_immediate_fire_task()`. By the time `start()` fires, `attach_timer()` has already stored the timer reference in `duration_config._timer`. Therefore `assert main_listener.duration_config._timer is not None` holds when `make_cancel_sub` runs. Verify this empirically during implementation by adding a temporary debug log in `make_cancel_sub`.

**Step 7: Update CommandExecutor._execute_handler()** in `src/hassette/core/command_executor.py`:
- `cmd.listener.app_key` → `cmd.listener.identity.app_key`
- `cmd.listener.instance_index` → `cmd.listener.identity.instance_index`
- `cmd.listener.invoke(cmd.event)` → `cmd.listener.invoker.invoke(cmd.event)`
- `cmd.listener.error_handler` → `cmd.listener.invoker.error_handler`

**Step 8: Update test harness** in `src/hassette/test_utils/harness.py`:
- `cmd.listener.error_handler` → `cmd.listener.invoker.error_handler`
- `cmd.listener.invoke(cmd.event)` → `cmd.listener.invoker.invoke(cmd.event)`

**Step 9: Add ListenerRegistration parity test** at `tests/unit/bus/test_registration_parity.py`:
- Assert all fields on ListenerRegistration have a source on ListenerIdentity or ListenerOptions
- Use explicit exemption list for computed/runtime fields (e.g., `listener_id`, `human_description`)
- Follow the pattern in `tests/integration/test_recording_api_protocol_parity.py`

**Step 10: Write test for cancel-listener factory:**
- Test `Listener.create_cancel_listener()` produces a listener with `source_tier="framework"`
- Test it works without a Bus instance
- Test the cancel subscription gets an already-resolved Future

## Focus
- `bus_service.py` has ~50 field access sites that change. Work through them methodically — the Explore agent enumerated every line.
- The `_create_cancel_listener` assert at line 176 (`assert main_listener._duration_timer is not None`) is called from the `make_cancel_sub` callback during DurationTimer construction. After refactor, the timer reference is set inside `attach_timer()` which calls `DurationTimer(...)`. The callback `create_cancel_sub` is passed INTO DurationTimer's constructor. DurationTimer's `start()` method calls `self._create_cancel_sub()` — so the callback fires AFTER construction, during `start()`, not during `__init__`. The assert on `main_listener.duration_config._timer` should hold because `attach_timer()` stores the timer reference before `start()` is ever called.
- `command_executor.py` has 4 access sites (lines 425, 426, 453, 457). Straightforward path updates.
- `harness.py` has 3 access sites (lines 610, 612, 616). Same pattern as command_executor.

## Verify
- [ ] FR#10: Listener.create_cancel_listener() produces a functioning listener without Bus; source_tier is "framework"
- [ ] AC#9: cancel_listener = Listener.create_cancel_listener(task_bucket, owner_id, topic, handler, entity_id, predicate) succeeds without Bus instance
- [ ] AC#10: parity test exists and passes — every ListenerRegistration field maps to a ListenerIdentity or ListenerOptions field (with explicit exemptions)
