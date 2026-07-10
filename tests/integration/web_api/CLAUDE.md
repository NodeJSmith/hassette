# Tests: integration/web_api

## Available fixtures (this directory's conftest.py)
- `mock_hassette` — `create_hassette_stub()` MagicMock stub seeded with `light.kitchen` / `sensor.temp` states and an `AppStatusSnapshot`
- `runtime_query_service` — `create_mock_runtime_query_service(mock_hassette)`
- `app` — FastAPI app via `create_fastapi_app(mock_hassette)`
- `client` — httpx2 `AsyncClient` wrapping `app` via `ASGITransport`

## Shared helpers
- `make_log_record(seq, **kw)` (local) — builds a raw log record dict for log-endpoint tests

## Key conventions
- `app`/`client`/`runtime_query_service` live here (not `tests/integration/conftest.py`) because their sole dependency, `mock_hassette`, is web-test-specific.
