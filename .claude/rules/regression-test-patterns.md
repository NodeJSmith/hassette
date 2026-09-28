---
paths:
  - "tests/**"
---

# Regression Test Patterns

Patterns for tests that pin a bug before fixing it. Hassette's hard bugs are startup races, timing, and subtle state issues — categories where "it seemed to work" is not evidence.

## Startup races

Gate a dependency with `asyncio.Event`, and have the mock signal a second event the instant it's awaited. Wait on that signal before asserting the task is blocked. Do **not** use `await asyncio.sleep(0)` to "let the task reach the block" — a single scheduler tick races the code under test, so the assertion passes or fails by luck.

```python
gate = asyncio.Event()
entered = asyncio.Event()

async def blocked_wait(_):
    entered.set()             # signal the moment the dependency is awaited
    await gate.wait()

mock_service.wait_for_ready = AsyncMock(side_effect=blocked_wait)
task = asyncio.create_task(executor.register_listener(...))
await asyncio.wait_for(entered.wait(), timeout=1)  # deterministic: task reached the block
assert not task.done()                             # the gate is actually blocking it
gate.set()
result = await task
assert result > 0                                  # registration succeeded after unblocking
```

## Config-driven real-clock timeouts

A test that overrides a production timeout (e.g. `websocket.total_timeout_seconds`) races that value in real wall-clock time against any deliberate delay in the same test — an `asyncio.wait_for(..., timeout=1)` inside `pytest.raises(TimeoutError)` proving something hasn't happened yet, an `asyncio.sleep()`, or scheduling overhead. With under a second of margin, CI's noisier scheduling eventually eats it, even if the test passes locally for months.

To reproduce, drive the overridden timeout down until it fails on any machine (e.g. `0`) and confirm the failure matches CI. To fix, widen the override to give the deliberate hold generous headroom — the Pydantic field default (e.g. `HassetteConfig`'s `total_timeout_seconds` of 30) is usually right, since it's already the framework's "reasonable real-world chance to finish." Do not shrink the competing delay instead; the delay is the thing under test.

## Sentinel filtering

Verify that records with unregistered IDs (`listener_id=0`, `job_id=0`, `session_id=0`) are silently dropped and not written to the database.

## Error isolation

Confirm that exceptions raised inside `execute()` do not propagate out of the method; the caller (TaskBucket) must not crash.
