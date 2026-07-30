---
task_id: "T04"
title: "Decouple runtime query from app bootstrap"
status: "planned"
depends_on: ["T03"]
implements: ["FR#6", "FR#26", "AC#18"]
---

## Summary
Make the dashboard/runtime-query path independent from app bootstrap while preserving current health semantics and shutdown tolerance. This task removes `RuntimeQueryService`'s lifecycle dependency on `AppHandler`, keeps pre-bootstrap registry metadata queryable, and hardens websocket/web-test stubs that currently assume live apps already exist. It preserves the existing UI contract: the dashboard serves, app counts can be zero before bootstrap, and no new dashboard-specific lifecycle phases are introduced.

## Target Files
- modify: `src/hassette/core/runtime_query_service.py`
- modify: `src/hassette/core/web_api_service.py`
- modify: `src/hassette/test_utils/web_mocks.py`
- modify: `tests/unit/core/test_runtime_query_service.py`
- modify: `tests/integration/web_api/conftest.py`
- modify: `tests/integration/web_api/test_endpoints.py`
- modify: `tests/integration/web_api/test_ws_endpoint.py`
- read: `src/hassette/core/app_handler.py`
- read: `src/hassette/web/routes/health.py`
- read: `src/hassette/web/routes/ws.py`

## Prompt
Implement the `RuntimeQueryService.depends_on` and dashboard-independence parts of the `## Architecture -> AppBootstrapCoordinator Resource` and `## Architecture -> Health Semantics` sections.

In `src/hassette/core/runtime_query_service.py`, remove the lifecycle dependency on `AppHandler` while preserving safe access to the already-constructed registry and status snapshot. Before bootstrap release, `overlay_manifest_rows()` and `get_registry_only_apps()` should continue to expose configured registry metadata, `get_app_status_snapshot()` may be empty, `get_system_status()` should report zero live apps, and `collect_boot_issues()` should only report issues represented in the registry. Keep shutdown tolerant of concurrent AppHandler teardown: no exceptions, no dependence on a final app-stopped broadcast.

Only make code changes in `src/hassette/core/web_api_service.py` if the dependency graph or ready-path assumptions need adjustment after removing `AppHandler` from RuntimeQueryService startup. Update web test stubs and route-level tests so mocked RuntimeQueryService/Hassette objects accurately model pre-bootstrap app counts, status snapshots, and websocket-connected payloads without inventing new response schema fields.

## Focus
- `src/hassette/core/runtime_query_service.py` currently depends on `AppHandler`; that transitively delays `WebApiService`, which violates the approved architecture.
- Reverse-dependency gaps to include here: `src/hassette/test_utils/web_mocks.py`, `tests/integration/web_api/conftest.py`, `tests/integration/web_api/test_endpoints.py`, and `tests/integration/web_api/test_ws_endpoint.py` all stub app snapshots and websocket health for the web layer.
- `src/hassette/web/routes/health.py` and `src/hassette/web/routes/ws.py` already consume `RuntimeQueryService.get_system_status()`; preserve their schema and status meanings rather than adding dashboard-only phases.
- Preserve the design's shutdown tolerance note: registry reads and websocket broadcasts must remain safe while AppHandler is concurrently tearing down.

## Verify
- [ ] FR#6: RuntimeQueryService and WebApiService can serve dashboard/API requests while apps wait indefinitely for Home Assistant prerequisites.
- [ ] FR#26: Health remains `starting` before first external readiness, `degraded` after losing a prior ready connection, and `ok` while externally connected.
- [ ] AC#18: Before app bootstrap, `overlay_manifest_rows()` and `get_registry_only_apps()` return configured metadata, `get_app_status_snapshot()` may be empty, `get_system_status()` reports `app_count=0`, and concurrent AppHandler teardown raises no observer exception.
