# Context: Test Mock Consolidation

## Problem & Motivation
~15 test files define their own factory functions for constructing mock hassette objects, with ~7 more importing them — ~22 files involved in the named factory pattern. Beyond these, ~12 additional files define inline `mock_hassette` fixtures with 4-12+ manually-set config attributes. Each factory has drifted: identical fields carry different values across files, and every new config field requires touching every factory. A well-designed hermetic config factory (`make_test_config()`) already exists in `src/hassette/test_utils/config.py` but is unused by these factories. The goal is to consolidate everything into a single shared `make_mock_hassette()` factory that uses real Pydantic-validated config, eliminating drift and reducing maintenance to a single file.

## Visual Artifacts
None.

## Key Decisions
1. The new factory uses `make_test_config()` for real config validation combined with `AsyncMock` for non-config attributes — not pure MagicMock (catches invalid/phantom fields) and not real Hassette (too many __init__ side effects for unit tests).
2. `data_dir` defaults to `tempfile.mkdtemp()` so unit tests don't need `tmp_path`. Integration tests that need DB isolation pass `tmp_path` explicitly.
3. `seal()` is called by default after wiring attributes — prevents phantom attribute auto-vivification. Tests needing extra attributes pass `sealed=False`.
4. `make_ws_hassette_stub()` is a thin preset wrapper, not a separate factory — it calls `make_mock_hassette()` with 13 WebSocket config field overrides.
5. The `_migrated_db_template` fixture needs exactly 4 explicit overrides: `database.max_size_mb=0`, `database.telemetry_write_queue_max=500`, `lifecycle.resource_shutdown_timeout_seconds=5`, `web_api.run=True`. The other 11 values match defaults.
6. Database-backed fixtures use name `db_hassette`; lightweight stubs use `mock_hassette` — distinct at grep time.
7. `make_test_config()`'s shared mutable cell needs a `threading.Lock` before this migration promotes it to canonical usage.

## Constraints & Anti-Patterns
- Do NOT modify `create_hassette_stub()` in `test_utils/web_mocks.py` — that's out of scope (web/API mock factory, separate follow-up).
- Do NOT change test assertions or test function names.
- Do NOT migrate `test_hassette_timeout_warning.py` — it uses `object.__new__(Hassette)` to bypass `__init__` and is the wrong pattern for `make_mock_hassette()`.
- Do NOT promote `bus_test_helpers.py` to shared utilities.
- Do NOT address `caplog` test usage (tracked in #473).
- Tests that mutate `hassette.config.X` after construction will break with real frozen config — these must pass the value as a config override at construction time instead. **Pre-migration audit required:** before migrating each file, grep for `hassette.config.*` and `executor.hassette.config.*` assignment sites within that file, extract the assigned values, and cross-reference against `ge`/`le`/`gt`/`lt` constraints in `src/hassette/config/models.py`. Tests assigning values outside Pydantic constraint ranges must retain a mock config layer for that field or the constraint must be relaxed.
- Tests that assert `config.reload()` was called need `hassette.config.reload = Mock()` patched on top of the real config.
- The factory must work without `asyncio.get_running_loop()` when `set_loop=False` (needed for session-scoped fixtures that run outside an event loop).

## Design Doc References
- "## Architecture" — factory signature, non-config attribute list, consolidated fixtures, naming convention
- "## Edge Cases" — session-scoped fixtures, config mutation, config.reload(), config_dir, seal() behavior
- "## Key Constraints" — import-time side effects, MagicMock→real config breakage, session-scope event loop
- "## Convention Examples" — 4 examples showing before/after patterns

## Convention Examples
### Hermetic config factory (the foundation)

**Source:** `src/hassette/test_utils/config.py`

```python
def make_test_config(*, data_dir: Path | str, **overrides: Any) -> HassetteConfig:
    defaults: dict[str, Any] = {
        "token": "test-token",
        "base_url": "http://test.invalid:8123",
        "data_dir": data_dir,
        "disable_state_proxy_polling": True,
        "app": {"autodetect": False},
        "web_api": {"run": False},
        "run_app_precheck": False,
    }
    merged = {**defaults, **overrides}

    cls, cell = _get_hermetic_hassette_config_cls()
    cell[0] = merged
    return cls()
```

### Current unit test factory (what we're replacing)

**Source:** `tests/unit/resources/conftest.py`

```python
def _make_hassette_stub(*, strict_lifecycle: bool = False) -> AsyncMock:
    hassette = AsyncMock()
    hassette.config.logging.log_level = "DEBUG"
    hassette.config.strict_lifecycle = strict_lifecycle
    hassette.config.data_dir = "/tmp/hassette-test"
    hassette.config.default_cache_size = 1024
    hassette.config.lifecycle.resource_shutdown_timeout_seconds = 1
    # ... 10 more lines of manual config
    hassette.ready_event = asyncio.Event()
    hassette.ready_event.set()
    hassette._loop_thread_id = threading.get_ident()
    hassette.loop = asyncio.get_running_loop()
    hassette._scheduler_service.register_removal_callback = Mock()
    # ... more service stubs
    return hassette
```

DO: Use `make_mock_hassette(strict_lifecycle=True)` — one line, validated config.
DON'T: Manually set config fields on a mock — they drift and bypass validation.
