# Test Infrastructure Guide

## Harness Builder API

`HassetteHarness` provides a fluent builder for composing test environments. Dependencies are resolved automatically at startup.

```python
from hassette.test_utils import HassetteHarness

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

## Choosing a Mock Strategy

Two parallel systems exist for different testing needs:

| Scenario                                         | Tool                              | Why                                              |
| ------------------------------------------------ | --------------------------------- | ------------------------------------------------ |
| Bus routing, scheduler firing, state propagation | `HassetteHarness`                 | Wires real components — catches integration bugs |
| HTTP endpoints, HTML responses, WebSocket frames | `create_hassette_stub()`          | MagicMock stub — fast, no real services needed   |
| DataSyncService + event buffer                   | `create_mock_data_sync_service()` | Bypasses `__init__`, wires to the stub           |
| FastAPI app from a stub                          | `create_test_fastapi_app()`       | Thin wrapper with optional log handler patch     |

### `HassetteHarness` — real components

Use when you need real event delivery, scheduling, or state propagation:

```python
from hassette.test_utils import HassetteHarness

async with HassetteHarness(config).with_bus().with_scheduler() as harness:
    hassette = harness.hassette
    # Real bus, real scheduler — events flow end-to-end
```

### `create_hassette_stub()` — MagicMock stub

Use when you only need HTTP/WS responses and don't care about internal wiring:

```python
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_data_sync_service

stub = create_hassette_stub(states={"light.kitchen": {...}})
ds = create_mock_data_sync_service(stub)
app = create_fastapi_app(stub)
```

## Fixture Naming Conventions

### Harness fixtures (`src/hassette/test_utils/fixtures.py`)

- `hassette_harness` — factory that creates a bare `HassetteHarness` with a fresh TCP port
- `hassette_with_*` — pre-configured harness fixtures (e.g., `hassette_with_bus`, `hassette_with_state_proxy`)

### Web mock fixtures

- `mock_hassette` — MagicMock Hassette created via `create_hassette_stub()` (local to each test file)
- `data_sync_service` — DataSyncService wired to the mock, via `create_mock_data_sync_service()` (shared in `tests/integration/conftest.py`)
- `app` — FastAPI application instance (shared in `tests/integration/conftest.py`, can be overridden locally)
- `client` — httpx `AsyncClient` (shared in `tests/integration/conftest.py`, can be overridden locally)

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
from hassette.test_utils import preserve_config

with preserve_config(hassette.config):
    hassette.config.some_setting = "temporary"
    # ... test runs ...
# config is restored after the block
```

### Autouse cleanup fixtures — `tests/integration/conftest.py`

Four autouse fixtures reset module-scoped harness state before each test. They live in `tests/integration/conftest.py` (not in the plugin module) to avoid interfering with sync Playwright e2e tests.

| Fixture                       | Resets                                                | Covers fixtures                                                                                              |
| ----------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `cleanup_state_proxy_fixture` | State cache + bus listeners via `reset_state_proxy()` | `hassette_with_state_proxy`                                                                                  |
| `cleanup_bus_fixture`         | All bus listeners via `reset_bus()`                   | `hassette_with_bus`, `hassette_with_scheduler`, `hassette_with_file_watcher`, `hassette_with_state_registry` |
| `cleanup_scheduler_fixture`   | All scheduler jobs via `reset_scheduler()`            | `hassette_with_scheduler`                                                                                    |
| `cleanup_mock_api_fixture`    | Mock server expectations via `reset_mock_api()`       | `hassette_with_mock_api`                                                                                     |

Reset functions are defined in `src/hassette/test_utils/reset.py`.

## Available Factories

### `create_hassette_stub(**kwargs)` — `test_utils/web_mocks.py`

Builds a fully-wired MagicMock Hassette stub for web/API tests. Handles all `hassette.<public> = hassette._<private>` wiring, state proxy side effects, and snapshot plumbing.

### `create_mock_data_sync_service(mock_hassette, **kwargs)` — `test_utils/web_mocks.py`

Builds a DataSyncService bypassing `__init__`. Use `use_real_lock=False` for session-scoped fixtures on Python 3.12+.

### `create_test_fastapi_app(mock_hassette, *, log_handler=None)` — `test_utils/web_mocks.py`

Thin wrapper around `create_fastapi_app()` with optional log handler patch.

### `make_manifest(**kwargs)` — `test_utils/web_helpers.py`

Builds an `AppManifestInfo` with sensible defaults.

### `make_full_snapshot(manifests)` — `test_utils/web_helpers.py`

Builds an `AppFullSnapshot` from a list of manifests with auto-computed status counts.

### `make_listener_metric(listener_id, owner, topic, handler_name, ...)` — `test_utils/web_helpers.py`

Builds a mock listener metric with `.to_dict()` and direct attribute access.

### `make_old_app_instance(**kwargs)` — `test_utils/web_helpers.py`

Builds a `SimpleNamespace` app entry for old-style `AppHandler.get_status_snapshot()` snapshots. Includes `owner_id` (defaults to `None`).

### `make_old_snapshot(running=None, failed=None, only_app=None)` — `test_utils/web_helpers.py`

Builds an outer `SimpleNamespace` for `AppHandler.get_status_snapshot()`. Auto-computes counts. Defaults to one running app when both `running` and `failed` are `None`.

### `make_job(**kwargs)` — `test_utils/web_helpers.py`

Builds a `SimpleNamespace` scheduler job with sensible defaults (job_id, name, owner, next_run, repeat, trigger).

### `setup_registry(hassette, manifests)` — `test_utils/web_helpers.py`

Configures the mock registry to return a proper `AppFullSnapshot`.

## Shared Integration Fixtures

`tests/integration/conftest.py` provides:

- **Autouse cleanup fixtures** — `cleanup_state_proxy_fixture`, `cleanup_bus_fixture`, `cleanup_scheduler_fixture`, `cleanup_mock_api_fixture` (reset module-scoped harness state between tests)
- **`data_sync_service`** — shared across integration web test files; each file defines its own `mock_hassette`
- **`app`** — FastAPI application instance
- **`client`** — httpx `AsyncClient`
