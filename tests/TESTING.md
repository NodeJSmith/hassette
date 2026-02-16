# Test Infrastructure Guide

## Harness Builder API

`HassetteHarness` provides a fluent builder for composing test environments. Dependencies are resolved automatically at startup.

```python
from hassette.test_utils.harness import HassetteHarness

# Builder chains — bus is auto-added because state_proxy depends on it
async with HassetteHarness(config).with_state_proxy().with_scheduler() as harness:
    hassette = harness.hassette
```

### Available components

| Method                   | Component                            | Auto-pulls           |
| ------------------------ | ------------------------------------ | -------------------- |
| `.with_bus()`            | Event bus + BusService               | —                    |
| `.with_scheduler()`      | SchedulerService + Scheduler         | —                    |
| `.with_api_mock()`       | Mock HTTP server + ApiResource + Api | —                    |
| `.with_state_proxy()`    | StateProxy                           | `bus`                |
| `.with_state_registry()` | STATE_REGISTRY + TYPE_REGISTRY       | —                    |
| `.with_file_watcher()`   | FileWatcherService                   | —                    |
| `.with_app_handler()`    | AppHandler                           | `bus`, `state_proxy` |

## Fixture Naming Conventions

### Harness fixtures (`src/hassette/test_utils/fixtures.py`)

- `hassette_harness` — factory that creates a bare `HassetteHarness` with a fresh TCP port
- `hassette_with_*` — pre-configured harness fixtures (e.g., `hassette_with_bus`, `hassette_with_state_proxy`)

### Web mock fixtures (local to each test file)

- `mock_hassette` — MagicMock Hassette created via `create_mock_hassette()`
- `data_sync_service` — DataSyncService wired to the mock, via `create_mock_data_sync_service()`
- `app` — FastAPI application instance
- `client` — httpx `AsyncClient` or Starlette `TestClient`

### Component extractors (local fixtures)

- Named after the component: `bus`, `state_proxy`, `websocket_service`

## Scoping Rules

| Scope        | When to use                                       | Example                                               |
| ------------ | ------------------------------------------------- | ----------------------------------------------------- |
| **session**  | Immutable data, expensive one-time setup          | `state_change_events`, e2e `mock_hassette`            |
| **module**   | Components with reset/cleanup between tests       | `hassette_with_bus`, `hassette_with_state_proxy`      |
| **function** | Mutable config or components that can't be reused | `hassette_with_app_handler`, web test `mock_hassette` |

Module scope with autouse cleanup gives 5-10x speedup over function scope. Prefer module scope when possible.

## Cleanup Patterns

### `preserve_config()` — for config mutation in module-scoped fixtures

```python
from hassette.test_utils.harness import preserve_config

with preserve_config(hassette.config):
    hassette.config.some_setting = "temporary"
    # ... test runs ...
# config is restored after the block
```

### `cleanup_state_proxy_fixture` — autouse async reset

Defined in `fixtures.py`, resets state proxy before each test when `hassette_with_state_proxy` is used.

### e2e sync override

Playwright tests are synchronous. `tests/e2e/conftest.py` overrides the async `cleanup_state_proxy_fixture` with a sync no-op.

## Available Factories

### `create_mock_hassette(**kwargs)` — `test_utils/mock_hassette.py`

Builds a fully-wired MagicMock Hassette. Handles all `hassette.<public> = hassette._<private>` wiring, state proxy side effects, and snapshot plumbing.

### `create_mock_data_sync_service(mock_hassette, **kwargs)` — `test_utils/mock_hassette.py`

Builds a DataSyncService bypassing `__init__`. Use `use_real_lock=False` for session-scoped fixtures on Python 3.12+.

### `create_test_fastapi_app(mock_hassette, *, log_handler=None)` — `test_utils/mock_hassette.py`

Thin wrapper around `create_fastapi_app()` with optional log handler patch.

### `make_manifest(**kwargs)` — `test_utils/web_helpers.py`

Builds an `AppManifestInfo` with sensible defaults.

### `make_full_snapshot(manifests)` — `test_utils/web_helpers.py`

Builds an `AppFullSnapshot` from a list of manifests with auto-computed status counts.

### `make_listener_metric(listener_id, owner, topic, handler_name, ...)` — `test_utils/web_helpers.py`

Builds a mock listener metric with `.to_dict()` and direct attribute access.

### `setup_registry(hassette, manifests)` — `test_utils/web_helpers.py`

Configures the mock registry to return a proper `AppFullSnapshot`.
