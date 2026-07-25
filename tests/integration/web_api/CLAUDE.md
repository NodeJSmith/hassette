# Tests: integration/web_api

## Available fixtures (this directory's conftest.py)

- `mock_hassette` — `create_hassette_stub()` MagicMock stub seeded with `light.kitchen` / `sensor.temp` states and an `AppStatusSnapshot`
- `runtime_query_service` — `create_mock_runtime_query_service(mock_hassette)`
- `app` — FastAPI app via `create_fastapi_app(mock_hassette)`
- `client` — httpx2 `AsyncClient` wrapping `app` via `ASGITransport`

## Shared helpers

- `make_log_record(seq, **kw)` (local, deliberately — see `# factory-local:` annotation) — builds a raw log record dict for log-endpoint tests; derives `timestamp` from `seq` so ordering tests get distinct, predictable timestamps. Shadows `hassette.test_utils.factories.make_log_record`, which uses a fixed `timestamp=0.0` default and does not fit this file's ordering tests.

## Key conventions

- `app`/`client`/`runtime_query_service` live here (not `tests/integration/conftest.py`) because their sole dependency, `mock_hassette`, is web-test-specific.
