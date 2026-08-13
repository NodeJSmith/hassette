---
task_id: "T03"
title: "Extract file-local helpers in test_invocation.py and test_handler_invoker.py"
status: "planned"
depends_on: []
implements: ["FR#5", "FR#6", "AC#1", "AC#3"]
---

## Target Files

- modify: `tests/unit/bus/test_invocation.py`
- modify: `tests/unit/bus/test_handler_invoker.py`

## Prompt

These are the two largest contributors to `tests/unit/bus/`'s 50 duplicate-code clusters (~15 and
~6 respectively, per `design.md`'s investigation). Read both files in full before editing.

**`test_invocation.py`**: nearly every test repeats this shape (see lines 19-58 for two adjacent
examples):

```python
executor = make_mock_executor()
config_resolver = MagicMock(return_value=X)
listener = create_listener(topic="test.topic", ...)
event = make_mock_event()

invoke_fn = build_tracked_invoke_fn(
    listener=listener,
    event=event,
    topic="test.topic",
    executor=executor,
    config_resolver=config_resolver,
)
await invoke_fn()

cmd = executor.execute.call_args[0][0]
assert isinstance(cmd, InvokeHandler)
```

Add one file-local async helper — e.g. `async def invoke_and_get_cmd(listener, config_resolver=None, executor=None, event=None, topic="test.topic") -> InvokeHandler` — that builds sane defaults for
whichever args aren't overridden, calls `build_tracked_invoke_fn` + `await invoke_fn()`, and returns
the extracted `cmd` (already asserted to be an `InvokeHandler`, or leave that assertion to the
caller — check whether every test needs it). Some tests need to inspect `executor`/`config_resolver`
afterward (e.g. `config_resolver.assert_not_called()`), so the helper should accept them as
optional params and return (or otherwise expose) whichever mocks the caller passed in or the helper
created, so post-call assertions still work.

**`test_handler_invoker.py`**: nearly every test in `TestHandlerInvokerCreate` repeats:

```python
task_bucket = make_task_bucket()
options = ListenerOptions(...)

invoker = HandlerInvoker.create(
    task_bucket=task_bucket,
    handler=simple_handler,
    kwargs=None,
    options=options,
)
```

Add one file-local helper — e.g. `def make_invoker(options: ListenerOptions | None = None, handler=simple_handler, kwargs=None, task_bucket=None) -> HandlerInvoker` — that fills in sane defaults and
calls `HandlerInvoker.create(...)`. Check whether later test classes in the file (beyond
`TestHandlerInvokerCreate`) repeat the same shape too — read the whole file, not just the excerpt
above.

Both helpers are **file-local** — do not add them to `tests/unit/bus/conftest.py` or
`src/hassette/test_utils/`, per `context.md`'s constraints. Preserve every test's actual assertions
exactly — this is a pure structural refactor, not a behavior change.

## Verify

- [ ] FR#5: `test_invocation.py` has one file-local helper collapsing the build-invoke-extract
      pattern; grep for `build_tracked_invoke_fn(` afterward and confirm remaining direct calls (if
      any) are ones the helper genuinely can't serve.
- [ ] FR#6: `test_handler_invoker.py` has one file-local helper collapsing the
      task_bucket+options+`HandlerInvoker.create` pattern.
- [ ] AC#1 (partial): run `uv run python tools/check_duplicate_code.py 2>&1 | grep -B1 -A5 "test_invocation.py\|test_handler_invoker.py"` and confirm the clusters purely internal to these two files are gone.
- [ ] AC#3: `uv run pytest tests/unit/bus/test_invocation.py tests/unit/bus/test_handler_invoker.py -n 4` passes with zero failures, and neither file's helper accidentally drops or adds a
      `@pytest.mark.parametrize` case or test function — spot-check by comparing
      `uv run pytest tests/unit/bus/test_invocation.py tests/unit/bus/test_handler_invoker.py --collect-only -q | tail -1` against the pre-edit count for just these two files (record it before
      editing if not already known).
