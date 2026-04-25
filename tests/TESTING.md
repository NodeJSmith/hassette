# Test Infrastructure Guide

## Harness Builder API

`HassetteHarness` provides a fluent builder for composing test environments. Dependencies are resolved automatically at startup.

```python
from hassette.test_utils import HassetteHarness

# Builder chains — bus and scheduler are auto-added because state_proxy depends on both
async with HassetteHarness(config).with_state_proxy() as harness:
    hassette = harness.hassette
```

### Available components

| Method                   | Component                            | Auto-pulls           |
| ------------------------ | ------------------------------------ | -------------------- |
| `.with_bus()`            | Event bus + BusService               | —                    |
| `.with_scheduler()`      | SchedulerService + Scheduler         | —                    |
| `.with_api_mock()`       | Mock HTTP server + ApiResource + Api | —                    |
| `.with_state_proxy()`    | StateProxy                           | `bus`, `scheduler`                |
| `.with_state_registry()` | STATE_REGISTRY + TYPE_REGISTRY       | —                    |
| `.with_file_watcher()`   | FileWatcherService                   | —                    |
| `.with_app_handler()`    | AppHandler                           | `bus`, `scheduler`, `state_proxy` |

## Choosing a Mock Strategy

Two parallel systems exist for different testing needs:

| Scenario                                         | Tool                              | Why                                              |
| ------------------------------------------------ | --------------------------------- | ------------------------------------------------ |
| Bus routing, scheduler firing, state propagation | `HassetteHarness`                 | Wires real components — catches integration bugs |
| HTTP endpoints, HTML responses, WebSocket frames | `create_hassette_stub()`          | MagicMock stub — fast, no real services needed   |
| RuntimeQueryService + event buffer               | `create_mock_runtime_query_service()` | Bypasses `__init__`, wires to the stub       |
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
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service

stub = create_hassette_stub(states={"light.kitchen": {...}})
runtime = create_mock_runtime_query_service(stub)
app = create_fastapi_app(stub)
```

## Fixture Naming Conventions

### Harness fixtures (`src/hassette/test_utils/fixtures.py`)

- `hassette_harness` — factory that creates a bare `HassetteHarness` with a fresh TCP port
- `hassette_with_*` — pre-configured harness fixtures (e.g., `hassette_with_bus`, `hassette_with_state_proxy`); all yield `HassetteHarness` directly

  Exception: `hassette_with_mock_api` yields `tuple[Api, SimpleTestServer]` — a different pattern used only by API-level tests.

### Web mock fixtures

- `mock_hassette` — MagicMock Hassette created via `create_hassette_stub()` (local to each test file)
- `runtime_query_service` — RuntimeQueryService wired to the mock, via `create_mock_runtime_query_service()` (shared in `tests/integration/conftest.py`)
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

### Autouse cleanup — `cleanup_harness` in `tests/integration/conftest.py`

A single `cleanup_harness` autouse fixture resets module-scoped harness state before each test. It lives in `tests/integration/conftest.py` (not in the plugin module) to avoid interfering with sync Playwright e2e tests.

```python
@pytest.fixture(autouse=True)
async def cleanup_harness(request: pytest.FixtureRequest) -> None:
    for name in _MODULE_SCOPED_HARNESS_FIXTURES & set(request.fixturenames):
        harness: HassetteHarness = request.getfixturevalue(name)
        await harness.reset()
```

`_MODULE_SCOPED_HARNESS_FIXTURES` covers the 6 module-scoped harness fixtures:
`hassette_with_nothing`, `hassette_with_bus`, `hassette_with_scheduler`,
`hassette_with_file_watcher`, `hassette_with_state_proxy`,
`hassette_with_state_registry`.

Function-scoped fixtures (`hassette_with_app_handler`,
`hassette_with_app_handler_custom_config`) are excluded — they are recreated
fresh for each test, so no cleanup is needed.

`HassetteHarness.reset()` resets each active component independently:

| Component      | Reset action                                              |
| -------------- | --------------------------------------------------------- |
| `state_proxy`  | Full shutdown/initialize cycle via `reset_state_proxy()`  |
| `bus`          | All listeners removed via `reset_bus()`                   |
| `scheduler`    | All jobs removed via `reset_scheduler()`                  |
| `api_mock`     | Expectations cleared via `reset_mock_api()`               |

Bus and Scheduler are siblings of StateProxy — not children of it. Resetting
StateProxy does not clear bus listeners or scheduler jobs, so each component is
always reset explicitly when active. The cost is negligible (one
`remove_all_listeners()` + one `_remove_all_jobs()` call per test at most).

Reset functions are defined in `src/hassette/test_utils/reset.py`.

## Available Factories

### `create_hassette_stub(**kwargs)` — `test_utils/web_mocks.py`

Builds a fully-wired MagicMock Hassette stub for web/API tests. Handles all `hassette.<public> = hassette._<private>` wiring, state proxy side effects, and snapshot plumbing.

### `create_mock_runtime_query_service(mock_hassette, **kwargs)` — `test_utils/web_mocks.py`

Builds a RuntimeQueryService bypassing `__init__`. Use `use_real_lock=False` for session-scoped fixtures on Python 3.12+.

### `create_test_fastapi_app(mock_hassette, *, log_handler=None)` — `test_utils/web_mocks.py`

Thin wrapper around `create_fastapi_app()` with optional log handler patch.

### `make_manifest(**kwargs)` — `test_utils/web_helpers.py`

Builds an `AppManifestInfo` with sensible defaults.

### `make_full_snapshot(manifests)` — `test_utils/web_helpers.py`

Builds an `AppFullSnapshot` from a list of manifests with auto-computed status counts.

### `make_listener_metric(listener_id, owner, topic, handler_method, ...)` — `test_utils/web_helpers.py`

Builds a mock listener metric with `.to_dict()` and direct attribute access.

### `make_job(**kwargs)` — `test_utils/web_helpers.py`

Builds a `SimpleNamespace` scheduler job with sensible defaults (job_id, name, owner, next_run, repeat, trigger).

### `setup_registry(hassette, manifests)` — `test_utils/web_helpers.py`

Configures the mock registry to return a proper `AppFullSnapshot`.

## Shared Integration Fixtures

`tests/integration/conftest.py` provides:

- **`cleanup_harness`** — single autouse fixture that resets all active module-scoped harness components before each test by calling `harness.reset()` on each matching fixture
- **`runtime_query_service`** — shared across integration web test files; each file defines its own `mock_hassette`
- **`app`** — FastAPI application instance
- **`client`** — httpx `AsyncClient`

## RecordingApi Assertion Methods

`RecordingApi` (used via `harness.api_recorder`) provides three assertion methods for verifying calls. The default match is **partial** — prefer `assert_called_partial` when you want to make that intent explicit in test code.

### `assert_called(method, **kwargs)` — partial match (default)

Passes if at least one recorded call for `method` contains **all** specified `kwargs` with matching values. Extra kwargs in the recorded call are ignored.

```python
await api.turn_off("light.x")
# Recorded: {"entity_id": "light.x", "domain": "homeassistant"}

api.assert_called("turn_off", entity_id="light.x")          # passes — partial match
api.assert_called("turn_off", entity_id="light.x", domain="homeassistant")  # also passes
```

### `assert_called_partial(method, **kwargs)` — partial match (explicit alias)

Identical to `assert_called`. Use this name when you want to be explicit that partial matching is intentional — for example, when the recorded call has many kwargs but you only care about one.

```python
api.assert_called_partial("call_service", domain="light")    # partial — ignores other kwargs
```

### `assert_called_exact(method, **kwargs)` — exact match (no extra kwargs allowed)

Passes only when the recorded call's `kwargs` dict is **exactly equal** to the provided `kwargs` — no extra keys are allowed. Use this when you need to verify that the method was called with *only* the specified arguments and nothing else.

```python
await api.turn_off("light.x")
# Recorded: {"entity_id": "light.x", "domain": "homeassistant"}

api.assert_called_exact("turn_off", entity_id="light.x")                    # FAILS — "domain" is extra
api.assert_called_exact("turn_off", entity_id="light.x", domain="homeassistant")  # passes
```

### When to use each

| Use case | Method |
|---|---|
| Verify a call happened with key arguments (ignore extras) | `assert_called` or `assert_called_partial` |
| Make partial-match intent explicit in test code | `assert_called_partial` |
| Verify no unexpected arguments were passed | `assert_called_exact` |

**Default is partial.** If you use `assert_called("turn_on", entity_id="light.x")` and the call also recorded `brightness=200`, the assertion still passes. Use `assert_called_exact` if that extra argument should be flagged as unexpected.
