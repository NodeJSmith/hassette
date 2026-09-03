# Tests: integration/telemetry

## Available fixtures (this directory's conftest.py)

- `db_hassette` — override of `integration/conftest.py::db_hassette` with `web_api={"run": True}` so telemetry endpoints are reachable
- `db` — initialized `DatabaseService` + seeded session row, from `tests/integration/conftest.py`
- `query_service` — `TelemetryQueryService` wired to `db_hassette.database_service`, `__init__` bypassed

## Shared helpers

- `from tests.support.mock_hassette import make_mock_hassette` — base builder this directory's `db_hassette` wraps

Everything else lives in this directory's `helpers.py`. Check it before writing a local helper:

- `DbFixture` — the `db` fixture's type, `tuple[DatabaseService, int]`. Annotate `db:` parameters with this, not the raw tuple.
- `open_db_with_session(hassette)` / `running_command_executor(hassette)` — DB + seeded session, and an initialized `CommandExecutor` as an async context manager. Both are for fixtures that need their own instance instead of the shared `db` fixture.
- `insert_listener` / `insert_job` / `insert_invocation` / `insert_execution` — single-row inserts.
- `insert_listener_and_job` / `insert_tiered_listeners` / `insert_app_listener_pair` — the three multi-row setups the UNION and tier-scoping tests share.
- `only_row(query)` — await a query and return its one row, asserting there is exactly one.
- `recent_activity(query_service, ...)` — `get_app_recent_activity()` with defaults for the four arguments a given test usually doesn't vary.
- `error_row(...)` / `SINCE_WINDOW_ERROR_ROWS` / `assert_last_error_row_coherence(...)` / `assert_no_last_error(row)` — building and asserting `last_error_*` data.
- `fetch_blocking_events(db_svc)` / `drain_db_writes(db_svc)` — read all `blocking_events` rows, and block until the DB write queue has drained a just-recorded event, for the blocking-IO detection tests.

## Key conventions

- Always override `db_hassette` locally when a test needs the web API reachable — don't set `web_api.run` on the shared `integration/conftest.py` version.
- `tools/check_duplicate_code.py` scans this directory. Where repetition is genuinely parallel test structure — the same setup varying only the data each case probes — wrap **every** occurrence in `# dup-ignore-start: <specific reason>` / `# dup-ignore-end`; partial annotation does not suppress the finding.
