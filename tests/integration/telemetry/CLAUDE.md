# Tests: integration/telemetry

## Available fixtures (this directory's conftest.py)

- `db_hassette` — override of `integration/conftest.py::db_hassette` with `web_api={"run": True}` so telemetry endpoints are reachable
- `db` — initialized `DatabaseService` + seeded session row, from `tests/integration/conftest.py`
- `query_service` — `TelemetryQueryService` wired to `db_hassette.database_service`, `__init__` bypassed

## Shared helpers

- `from hassette.test_utils.mock_hassette import make_mock_hassette` — base builder this directory's `db_hassette` wraps

## Key conventions

- Always override `db_hassette` locally when a test needs the web API reachable — don't set `web_api.run` on the shared `integration/conftest.py` version.
