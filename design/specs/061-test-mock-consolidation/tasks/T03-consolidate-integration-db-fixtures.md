---
task_id: "T03"
title: "Consolidate initialized_db and update DB template fixture"
status: "done"
depends_on: ["T01"]
implements: ["FR#4", "FR#5", "FR#7", "AC#2", "AC#7"]
---

## Summary
Consolidate the 4 duplicate `initialized_db` fixture definitions into a single fixture in `tests/integration/conftest.py`. Update the session-scoped `_migrated_db_template` fixture to use `make_mock_hassette()` instead of its 14-line MagicMock config block. Create a `db_hassette` fixture for database-backed integration tests, distinct from the lightweight `mock_hassette` name.

## Prompt
### Consolidate `initialized_db`

Four files define identical `initialized_db` async fixtures:
- `tests/integration/test_command_executor.py:48`
- `tests/integration/test_dispatch_unification.py:67`
- `tests/integration/test_command_executor_error_handler.py:51`
- `tests/integration/test_registration.py:60`

Each creates a `DatabaseService`, runs `on_initialize()` + `on_shutdown()`, inserts a session row, and yields `(db_service, session_id)`.

Create a single `initialized_db` fixture in `tests/integration/conftest.py` that:
1. Depends on a new `db_hassette` fixture (see below)
2. Creates a `DatabaseService(db_hassette, parent=db_hassette)`
3. Runs the init/shutdown/session-insert pattern
4. Yields `(db_service, session_id)`
5. Sets `db_hassette.session_id` and `db_hassette.database_service` after DB init (matching the pattern in the duplicates)

Delete the 4 local `initialized_db` fixtures from each test file. Pytest auto-discovers from conftest — no import changes needed.

### Create `db_hassette` fixture

Add a `db_hassette` fixture in `tests/integration/conftest.py` that:
```python
@pytest.fixture
def db_hassette(premigrated_db_path: Path) -> AsyncMock:
    return make_mock_hassette(data_dir=premigrated_db_path.parent)
```

This provides a mock hassette with a pre-migrated DB path and real validated config. The name `db_hassette` (not `mock_hassette`) distinguishes it from lightweight unit test stubs (FR#7).

### Update `_migrated_db_template`

Replace the 14-line MagicMock config block in `tests/integration/conftest.py:89-113` with:
```python
mock = make_mock_hassette(
    data_dir=tmpl_dir,
    set_loop=False,
    database={"max_size_mb": 0, "telemetry_write_queue_max": 500},
    lifecycle={"resource_shutdown_timeout_seconds": 5},
    web_api={"run": True},
)
```

Four values differ from defaults and are preserved as explicit overrides:
- `database.max_size_mb=0` — disables size failsafe (default: 500)
- `database.telemetry_write_queue_max=500` — smaller queue (default: 1000)
- `lifecycle.resource_shutdown_timeout_seconds=5` — faster shutdown (default: 10)
- `web_api.run=True` — `make_test_config()` defaults this to `False`

Keep the rest of the fixture body (`DatabaseService` creation, `loop.run_until_complete`, etc.) unchanged.

### Update `mock_hassette` fixtures in the 4 test files

Each of the 4 files defines its own `mock_hassette(premigrated_db_path)` fixture. These should either:
- Be replaced by usage of the shared `db_hassette` fixture (if the config overrides match)
- Be retained with `make_mock_hassette()` calls if they have unique config needs

Read each file's `mock_hassette` fixture to determine which config fields it sets, compare against `make_mock_hassette()` defaults, and decide.

After all changes, run `timeout 300 uv run pytest tests/integration/ -x -n 2` to verify.

## Focus
- The `_migrated_db_template` fixture at `tests/integration/conftest.py:88-124` runs OUTSIDE an event loop — it manually creates `asyncio.new_event_loop()`. `set_loop=False` is critical.
- `premigrated_db_path` fixture at line 127 copies the template DB to `tmp_path`. The `db_hassette` fixture should use `premigrated_db_path.parent` as `data_dir` so the DB path resolves correctly.
- The 4 duplicate `initialized_db` fixtures all have the same signature: `async def initialized_db(mock_hassette: MagicMock) -> AsyncIterator[tuple[DatabaseService, int]]`. When consolidated, the parameter name changes from `mock_hassette` to `db_hassette`.
- `tests/integration/conftest.py` already imports `DatabaseService` (used by `_migrated_db_template`). Add `from hassette.test_utils import make_mock_hassette` to the imports.
- The `mock_hassette` fixtures in the 4 test files set DB-related config (retention_days, queue sizes, etc.). Compare each against model defaults — most will match and need no overrides.

## Verify
- [ ] FR#4: `initialized_db` fixture exists in `tests/integration/conftest.py` and yields `(DatabaseService, int)`
- [ ] FR#5: `_migrated_db_template` uses `make_mock_hassette()` with real validated config, not MagicMock attribute assignment
- [ ] FR#7: Database-backed fixtures use `db_hassette` name, not `mock_hassette`
- [ ] AC#2: `grep -rn 'def initialized_db' tests/` returns exactly one result (in `tests/integration/conftest.py`)
- [ ] AC#7: `grep -rn 'def db_hassette' tests/` returns result in `tests/integration/conftest.py`; no integration test uses `mock_hassette` for DB-backed tests
