# Tests: unit/bus

## Available fixtures (this directory's conftest.py)

- `hassette_with_bus` — function-scoped `Hassette` with a live `Bus`; overrides the module-scoped `test_utils` version because these tests mutate listener state per-test
- `bus` — the `Bus` resource off `hassette_with_bus`, with `parent` set via `make_mock_parent`

## Shared helpers

- `from hassette.test_utils.factories import make_mock_parent` — owning-App stand-in, used to set `bus.parent`
- `mock_add_listener(bus)` (local contextmanager) — swaps `bus.bus_service.add_listener` for an `AsyncMock`, restores on exit

## Key conventions

- `hassette_with_bus` is intentionally function-scoped, not module-scoped — see the fixture docstring before "fixing" the scope mismatch with other harness fixtures.

## File-local helpers

These live at module scope in their own test file, not in `conftest.py` — a reader scanning `conftest.py` alone won't find them. Each collapses a setup pattern that only repeats within that one file (per `.claude/rules/test-conventions.md`, shared placement is reserved for patterns reused across 3+ files):

- `test_invocation.py` — `invoke_and_get_cmd(*, listener=None, config_resolver=None, executor=None, event=None, topic="test.topic", is_synthetic=False)`: builds and fires an `invoke_fn` via `build_tracked_invoke_fn`, returning the resulting `InvokeHandler` command. Fills in sane defaults for any argument not overridden.
- `test_handler_invoker.py` — `make_invoker(options=None, handler=simple_handler, kwargs=None, task_bucket=None, error_handler=None)`: builds a `HandlerInvoker` via `HandlerInvoker.create()`, filling in a fresh `make_task_bucket()` and default `ListenerOptions()` when not overridden.
- `test_duration_hold.py` — `make_listener_with_mock_timer(entity_id="light.kitchen", duration=60.0, task_bucket=None)`: builds a `Listener` with `duration_config` set and a `MagicMock` attached as its timer. Returns `(listener, mock_timer, task_bucket)`; pass a `task_bucket` in when a test needs to reuse the same bucket for the listener and its owning manager/router.
- `test_duration_timer.py` — `start_timer(duration=0.5, predicates=None, create_cancel_sub=None)`: builds a `DurationTimer` via the file's existing `make_timer()` and starts it with a no-op `on_fire` callback, for tests that only care about lifecycle state (`is_active`, `cancel`, cancellation subscriptions). `make_timer_with_fired_event(duration=0.05)`: builds a `DurationTimer` plus an unset `fired` `asyncio.Event` and its `on_fire` callback, without starting the timer, for tests that need to assert `is_active` state before calling `timer.start()` themselves.
