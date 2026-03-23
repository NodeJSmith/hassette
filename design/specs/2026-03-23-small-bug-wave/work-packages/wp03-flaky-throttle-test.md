# WP03: Fix flaky throttle test (#340)

**Lane:** todo
**Closes:** #340

## Summary

Rewrite `test_throttle_tracks_time_correctly` to mock `time.monotonic` instead of using real `asyncio.sleep` calls with sub-100ms margins. The test was testing asyncio scheduler timing, not throttle logic.

## Acceptance Criteria

- [ ] Test uses `@patch("hassette.bus.rate_limiter.time.monotonic")` (module-scoped)
- [ ] No `asyncio.sleep` calls in the test — time is advanced via `mock_time.return_value`
- [ ] Test passes deterministically under `pytest-xdist` parallel execution
- [ ] Test still verifies: first call executes, call within throttle window is dropped, call after throttle window executes

## Files to Change

| File | Change |
|------|--------|
| `tests/integration/test_listeners.py` | Rewrite `test_throttle_tracks_time_correctly` (lines 241-260) |

## Test Pattern

```python
@patch("hassette.bus.rate_limiter.time.monotonic")
async def test_throttle_tracks_time_correctly(self, mock_time, bucket_fixture):
    calls = []
    async def handler(event): calls.append(event.data)

    mock_time.return_value = 0.0
    adapter = create_adapter(handler, bucket_fixture, throttle=0.05)

    await adapter.call(mock_event("1"))       # t=0.0, executes
    assert calls == ["1"]

    mock_time.return_value = 0.03             # t=30ms, within throttle
    await adapter.call(mock_event("2"))
    assert calls == ["1"]                     # still throttled

    mock_time.return_value = 0.06             # t=60ms, past throttle
    await adapter.call(mock_event("3"))
    assert calls == ["1", "3"]                # executes
```

## Verification

```bash
# Run the specific test
uv run pytest tests/integration/test_listeners.py::TestHandlerAdapter::test_throttle_tracks_time_correctly -v

# Run under xdist to verify no flakiness
uv run pytest tests/integration/test_listeners.py -v -n auto --dist loadscope
```
