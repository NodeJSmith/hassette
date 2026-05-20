---
task_id: "T01"
title: "Create make_mock_hassette() factory and thread safety"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "AC#8"]
---

## Summary
Create the shared `make_mock_hassette()` factory function and `make_ws_hassette_stub()` preset wrapper in a new module `src/hassette/test_utils/mock_hassette.py`. Add thread safety to `make_test_config()`'s shared mutable cell. Export both new functions from `src/hassette/test_utils/__init__.py`. This is the foundation that all subsequent migration tasks depend on.

## Prompt
Create a new file `src/hassette/test_utils/mock_hassette.py` with two functions:

### `make_mock_hassette()`

Signature (from design doc "Architecture" section):
```python
def make_mock_hassette(
    *,
    data_dir: Path | str | None = None,
    set_ready: bool = True,
    set_loop: bool = True,
    sealed: bool = True,
    **config_overrides: Any,
) -> AsyncMock:
```

Implementation:
1. If `data_dir is None`, generate via `tempfile.mkdtemp()`.
2. Call `make_test_config(data_dir=data_dir, **config_overrides)` to get a real validated `HassetteConfig`.
3. Create `hassette = AsyncMock()`.
4. Set `hassette.config = config` (the real config object).
5. Wire all non-config attributes listed in the design doc "Architecture" section under "Non-configuration attributes wired by default" — see context.md for the full list of 13 attributes.
6. For `hassette.loop`: use `asyncio.get_running_loop()` if `set_loop=True`, else `None`.
7. For `hassette.ready_event`: create `asyncio.Event()` and call `.set()` if `set_ready=True`.
8. If `sealed=True`, call `seal(hassette)` from `unittest.mock`.

### `make_ws_hassette_stub()`

A thin wrapper around `make_mock_hassette()` that bakes in the 13 WebSocket config fields for sub-millisecond retry/timeout testing. Accept `strict_lifecycle: bool = False` as an optional parameter (one of the two WS test files passes this).

Extract the exact 13 field values from `tests/unit/core/test_ws_connection_state.py` lines 19-55 — these are the canonical WebSocket test config values. Pass them as `**config_overrides` to `make_mock_hassette()`.

### Thread safety for `make_test_config()`

In `src/hassette/test_utils/config.py`, protect the global `_HermeticHassetteConfigPair` with a module-level `threading.Lock`. Wrap the read-check-write in `_get_hermetic_hassette_config_cls()` and the `cell[0] = merged` + `cls()` sequence in `make_test_config()` with the lock.

### Exports

In `src/hassette/test_utils/__init__.py`:
- Add `make_mock_hassette` to Tier 1 (`__all__`) — this is a documented end-user API.
- Add `make_ws_hassette_stub` as a Tier 2 re-export (not in `__all__`) — internal test infrastructure.

Import pattern: `from .mock_hassette import make_mock_hassette as make_mock_hassette` (Tier 1) and `from .mock_hassette import make_ws_hassette_stub as make_ws_hassette_stub` (Tier 2).

## Focus
- The existing `make_test_config()` is at `src/hassette/test_utils/config.py:54`. Its cell pattern uses a global `_HermeticHassetteConfigPair` at line 18 — the Lock must protect both the lazy init in `_get_hermetic_hassette_config_cls()` (lines 31-33) and the `cell[0] = merged; cls()` sequence (lines 107-108).
- The `__init__.py` has a clear Tier 1 / Tier 2 structure — Tier 1 imports come from submodules (`.config`, `.app_harness`, etc.) and are listed in `__all__`. Tier 2 re-exports come from `._internal` with `X as X` pattern. New imports from `.mock_hassette` follow the Tier 1 submodule pattern.
- `seal()` is from `unittest.mock` — import it alongside `AsyncMock` and `Mock`.
- The 13 WS config fields set values like `0.001` for timeouts — they must remain as floats, not rounded.
- `set_loop=False` is critical for the `_migrated_db_template` session-scoped fixture which runs outside an event loop via `asyncio.new_event_loop()`.

## Verify
- [ ] FR#1: `make_mock_hassette()` returns an `AsyncMock` with `.config` set to a real `HassetteConfig` instance (not MagicMock)
- [ ] FR#2: Passing `strict_lifecycle=True` to `make_mock_hassette()` produces a config where `config.strict_lifecycle is True`
- [ ] FR#3: The returned mock has all 13 non-config attributes wired (ready_event, shutdown_event, event_streams_closed, _loop_thread_id, loop, _scheduler_service callbacks, _bus_service methods, session_id, database_service, wait_for_ready, children)
- [ ] AC#8: `make_ws_hassette_stub()` is importable from `hassette.test_utils` and returns a mock with WebSocket config fields set to sub-millisecond values
