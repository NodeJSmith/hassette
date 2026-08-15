# Tests: integration/web_api

## Available fixtures (this directory's conftest.py)

- `mock_hassette` — `create_hassette_stub()` MagicMock stub seeded with `light.kitchen` / `sensor.temp` states and an `AppStatusSnapshot`
- `runtime_query_service` — `create_mock_runtime_query_service(mock_hassette)`
- `app` — FastAPI app via `create_fastapi_app(mock_hassette)`
- `client` — httpx2 `AsyncClient` wrapping `app` via `ASGITransport`

## Shared helpers (this directory's conftest.py)

- `get_json(client, url, *, expect_status=200)` — GET, assert the status, return the decoded body. Replaces the `response = await client.get(...)` / `assert response.status_code == ...` / `data = response.json()` triple. Tests needing the `Response` itself (headers, `.text`, cookies) still call `client.get` directly.
- `telemetry_error(message=DB_LOCKED_MSG)` — an `AsyncMock` raising `TelemetryUnavailableError`; assign it onto the query-service method under test so the method name stays greppable at the call site.
- `DB_LOCKED_MSG` — the stand-in storage failure message DB-degradation tests raise.
- `HEALTH_PATH`, `APP_HEALTH_PATH`, `APP_GRID_PATH`, `TELEMETRY_STATUS_PATH` — route paths hit by tests in more than one file; import these rather than redefining the literal locally.
- `set_websocket_state(mock_hassette, *, connected, ever_connected)` / `set_app_status_snapshot(mock_hassette, *, running, failed)` — drive the health/system-status inputs.
- `make_log_record(seq, **kw)` (local, deliberately — see `# factory-local:` annotation) — builds a raw log record dict for log-endpoint tests; derives `timestamp` from `seq` so ordering tests get distinct, predictable timestamps. Shadows `hassette.test_utils.factories.make_log_record`, which uses a fixed `timestamp=0.0` default and does not fit this file's ordering tests.

## File-local helpers

Each of these collapses one file's repeated arrange/act shape; they stay file-local because no
second file drives the same endpoint.

- `test_api_app_config.py` — `get_app_config(...)`, `get_global_config(...)`, `manifest_entry(...)`, `config_toml_section(...)`
- `test_api_app_source.py` — `get_app_source(client, mock_hassette, *, app_dir, full_path)`
- `test_execution_endpoint.py` — `get_execution_logs(...)`
- `test_dashboard_api.py` — `get_health_with_status(client, mock_hassette, **status_fields)`
- `test_telemetry.py` — `assert_forwarded_to_service(...)`, `LISTENER_DEFAULTS`
- `test_telemetry_route.py` — `make_live_job(db_id, name, **kw)`, `get_enriched_job_row(...)`
- `test_trigger_job.py` — `post_trigger(...)`, `make_registered_job(...)`
- `test_ws_endpoint.py` — `subscribed_ws(client, **subscribe_data)`, `put_message(...)`, `expect_message(ws, type)`

## Key conventions

- `app`/`client`/`runtime_query_service` live here (not `tests/integration/conftest.py`) because their sole dependency, `mock_hassette`, is web-test-specific.
- Build `ListenerSummary`, `Execution`, and `AppInstanceInfo` test data through the shared factories (`make_listener_summary`, `make_execution`, `make_app_instance_info`) rather than the model constructors — the raw constructors are 10-30 keyword arguments of which a test typically asserts on two.
