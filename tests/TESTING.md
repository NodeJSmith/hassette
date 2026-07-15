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

| Method                   | Component                            | Auto-pulls                        |
| ------------------------ | ------------------------------------ | --------------------------------- |
| `.with_bus()`            | Event bus + BusService               | —                                 |
| `.with_scheduler()`      | SchedulerService + Scheduler         | —                                 |
| `.with_api_mock()`       | Mock HTTP server + ApiResource + Api | —                                 |
| `.with_state_proxy()`    | StateProxy                           | `bus`, `scheduler`                |
| `.with_state_registry()` | STATE_REGISTRY + TYPE_REGISTRY       | —                                 |
| `.with_file_watcher()`   | FileWatcherService                   | —                                 |
| `.with_app_handler()`    | AppHandler                           | `bus`, `scheduler`, `state_proxy` |

## Choosing a Mock Strategy

Two parallel systems exist for different testing needs:

| Scenario                                            | Tool                                  | Why                                                  |
| --------------------------------------------------- | ------------------------------------- | ---------------------------------------------------- |
| Bus routing, scheduler firing, state propagation    | `HassetteHarness`                     | Wires real components — catches integration bugs     |
| Unit tests needing a hassette mock with real config | `make_mock_hassette()`                | Real Pydantic validation, sealed by default, no drift |
| HTTP endpoints, HTML responses, WebSocket frames    | `create_hassette_stub()`              | MagicMock stub — fast, no real services needed       |
| RuntimeQueryService + event buffer                  | `create_mock_runtime_query_service()` | Bypasses `__init__`, wires to the stub               |
| FastAPI app from a stub                             | `create_test_fastapi_app()`           | Thin wrapper with optional log handler patch         |

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

- `mock_hassette` — in unit/integration non-web tests: lightweight hassette mock via `make_mock_hassette()` from `hassette.test_utils`; in web/API tests: MagicMock stub via `create_hassette_stub()` (defined locally per file, out of scope for consolidation)
- `db_hassette` — database-backed hassette mock with `premigrated_db_path`, also via `make_mock_hassette()`
- `runtime_query_service` — RuntimeQueryService wired to the mock, via `create_mock_runtime_query_service()` (shared in `tests/integration/web_api/conftest.py`)
- `app` — FastAPI application instance (shared in `tests/integration/web_api/conftest.py`, can be overridden locally)
- `client` — httpx2 `AsyncClient` (shared in `tests/integration/web_api/conftest.py`, can be overridden locally)

### Component extractors (local fixtures)

- Named after the component: `bus`, `state_proxy`, `websocket_service`

## Scoping Rules

| Scope        | When to use                                       | Example                                               |
| ------------ | ------------------------------------------------- | ----------------------------------------------------- |
| **session**  | Immutable data, expensive one-time setup          | `state_change_events`, e2e `mock_hassette`            |
| **module**   | Components with reset/cleanup between tests       | `hassette_with_bus`, `hassette_with_state_proxy`      |
| **function** | Mutable config or components that can't be reused | `hassette_with_app_handler_custom_config`, web test `mock_hassette` |

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
    for name in _HARNESS_FIXTURES & set(request.fixturenames):
        harness: HassetteHarness = request.getfixturevalue(name)
        await harness.reset()
```

`_HARNESS_FIXTURES` covers the 7 module-scoped harness fixtures:
`hassette_with_sync_executor`, `hassette_with_bus`,
`hassette_with_scheduler`, `hassette_with_file_watcher`,
`hassette_with_state_proxy`, `hassette_with_state_registry`,
`hassette_with_app_handler`.

Function-scoped fixtures (`hassette_with_app_handler_custom_config`) are
excluded — they are recreated fresh for each test, so no cleanup is needed.

`HassetteHarness.reset()` resets each active component independently:

| Component      | Reset action                                              |
| -------------- | --------------------------------------------------------- |
| `app_handler`  | Stop/clear/re-bootstrap cycle via `reset_app_handler()`   |
| `state_proxy`  | Full shutdown/initialize cycle via `reset_state_proxy()`  |
| `bus`          | All listeners removed via `reset_bus()`                   |
| `scheduler`    | All jobs removed via `reset_scheduler()`                  |
| `api_mock`     | Expectations cleared via `reset_mock_api()`               |

Bus and Scheduler are siblings of StateProxy — not children of it. Resetting
StateProxy does not clear bus listeners or scheduler jobs, so each component is
always reset explicitly when active. The cost is negligible (one
`remove_all_listeners()` + one `_remove_all_jobs()` call per test at most).

Reset functions are defined in `src/hassette/test_utils/reset.py`.

## Factory Naming Convention (`make_*` / `create_*` / `build_*`)

The `make_`/`create_`/`build_` prefix signals what a factory returns, not just that it builds something:

- **`make_<real object>()`** — returns a real, fully-constructed instance of the production type. `make_scheduled_job()` returns a real `ScheduledJob` for unit/scheduler tests that exercise `ScheduledJob` behavior directly (`__post_init__`, `matches()`, `sort_index`). `make_real_job()` (`web_helpers.py`) also returns a real `ScheduledJob`, but with web-layer defaults (`app_key`, `instance_index`) for tests that exercise web-layer behavior against a real job.
- **`make_<name>()` returning `SimpleNamespace`** — a duck-typed stand-in, not a real instance. `make_job()` (`web_helpers.py`) returns a `SimpleNamespace` job for serialization tests that only need attribute access, not real `ScheduledJob` methods.
- **`make_mock_*()`** — always returns a `Mock`/`MagicMock`/`AsyncMock`. `make_mock_executor()`, `make_mock_event()`, `make_mock_parent()` never construct the real production type.

Three factories share the word "job" but return three different things — check the return type, not just the name, before reusing one: `make_scheduled_job()` (real `ScheduledJob`, scheduler-test defaults), `make_real_job()` (real `ScheduledJob`, web-test defaults), `make_job()` (`SimpleNamespace`, serialization tests).

Similarly, `make_manifest()` in `web_helpers.py` returns `AppManifestInfo` (the runtime snapshot model) — this is a different type from local `make_manifest()` helpers in `test_config_classes.py` and `test_app_factory_lifecycle.py` that build `AppManifest` (the config-layer registration model). Those stay local; they are not consolidation targets.

## Before Writing a New Factory

1. Check `src/hassette/test_utils/factories.py` for an existing factory returning the type you need.
2. Check `src/hassette/test_utils/helpers.py` for event/state builders and misc helpers.
3. Check `src/hassette/test_utils/web_helpers.py` for web/API response and snapshot factories.
4. If a matching factory exists, import it — don't redefine it locally, even with a different name for the same shape.
5. If it doesn't exist and you need it in 3+ files, add it to the appropriate shared file instead of writing a fourth local copy.
6. If the factory is genuinely local — a different return type, a narrower purpose than any shared factory with a similar name — annotate the `def` line with `# factory-local: <reason>` so `tools/check_test_factories.py` doesn't flag it as shadowing.

## Available Factories

### `make_mock_hassette(**config_overrides)` — `test_utils/mock_hassette.py`

Builds a sealed `AsyncMock` hassette with real Pydantic-validated config via `make_test_config()`. Accepts any `HassetteConfig` field as a keyword override. Non-config attributes (`ready_event`, `shutdown_event`, service stubs, etc.) are wired automatically.

### `make_ws_hassette_stub(**kwargs)` — `test_utils/mock_hassette.py`

Thin wrapper around `make_mock_hassette()` with WebSocket config fields pre-set to fast values for retry/timeout testing (sub-millisecond backoff waits, low-single-digit-second connection/heartbeat timeouts).

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

### `make_job(**kwargs)` — `test_utils/web_helpers.py`

Builds a `SimpleNamespace` scheduler job with sensible defaults (job_id, name, owner, next_run, repeat, trigger).

### `make_real_job(**kwargs)` — `test_utils/web_helpers.py`

Builds a real `ScheduledJob` with web-layer defaults (`app_key`, `instance_index`). Use for web-layer tests that exercise real `ScheduledJob` behavior; use `make_job()` instead for pure serialization tests.

### `make_scheduled_job(**kwargs)` — `test_utils/factories.py`

Builds a real `ScheduledJob` for unit/scheduler tests, with every field overridable (`job`, `name`, `owner_id`, `next_run`, `trigger`, `group`, `jitter`, `timeout`, `timeout_disabled`, `error_handler`, `mode`, `db_id`, `predicate`).

### `make_mock_executor()` — `test_utils/factories.py`

Builds a `MagicMock` with `execute = AsyncMock()`, standing in for a `CommandExecutor`.

### `make_mock_event()` — `test_utils/factories.py`

Builds a `MagicMock(spec=Event)`.

### `make_recording_api(states=None)` — `test_utils/factories.py`

Builds a `RecordingApi` wired to an unsealed `make_mock_hassette()` (with the real `STATE_REGISTRY`) and an `AsyncMock(spec=StateProxy)` whose `.states` is seeded from `states` and `.is_ready()` returns `True`.

### `make_hassette_event(topic="hassette.ready", data=None)` — `test_utils/factories.py`

Builds an `Event` carrying a `HassettePayload`.

### `make_mock_parent(**kwargs)` — `test_utils/factories.py`

Builds a `MagicMock` standing in for an owning `App` resource, with `app_key`, `index`, `unique_name`, `source_tier`, `class_name`, and `app_config` all set. Callers that only care about a subset of these get harmless extra attributes.

## Shared Integration Fixtures

`tests/integration/conftest.py` provides:

- **`cleanup_harness`** — single autouse fixture that resets all active module-scoped harness components before each test by calling `harness.reset()` on each matching fixture

`tests/integration/web_api/conftest.py` provides:

- **`runtime_query_service`** — shared across integration web test files; each file defines its own `mock_hassette`
- **`app`** — FastAPI application instance
- **`client`** — httpx2 `AsyncClient`

## RecordingApi Assertion Methods

`RecordingApi` (used via `harness.api_recorder`) provides assertion methods for verifying calls. The default match is **partial** — prefer `assert_called_partial` when you want to make that intent explicit in test code. The negative and counting assertions (`assert_not_called`, `assert_call_count`) accept optional `kwargs` using the same partial-match semantics.

### `assert_called(method, **kwargs)` — partial match (default)

Passes if at least one recorded call for `method` contains **all** specified `kwargs` with matching values. Extra kwargs in the recorded call are ignored.

```python
await api.turn_off("light.x")
# Recorded: {"entity_id": "light.x", "domain": "light"}

api.assert_called("turn_off", entity_id="light.x")          # passes — partial match
api.assert_called("turn_off", entity_id="light.x", domain="light")  # also passes
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
# Recorded: {"entity_id": "light.x", "domain": "light"}

api.assert_called_exact("turn_off", entity_id="light.x")                    # FAILS — "domain" is extra
api.assert_called_exact("turn_off", entity_id="light.x", domain="light")  # passes
```

### `assert_not_called(method, **kwargs)` — negative assertion

Without `kwargs`, passes only if `method` was never called at all. With `kwargs`, passes if no recorded call matches all given kwargs — partial matching, consistent with `assert_called`. This lets you assert a method was never called for a specific target even when it was called for others.

```python
await api.turn_off("light.living_room")

api.assert_not_called("turn_off", entity_id="light.kitchen")  # passes — no call for light.kitchen
api.assert_not_called("turn_off")                             # FAILS — turn_off was called
```

### `assert_call_count(method, count, **kwargs)` — counting assertion

Without `kwargs`, counts all calls to `method`. With `kwargs`, counts only calls matching all given kwargs — partial matching, consistent with `assert_called`.

```python
await api.turn_on("light.kitchen")
await api.turn_on("light.kitchen")
await api.turn_on("light.bedroom")

api.assert_call_count("turn_on", 3)                             # passes — all calls
api.assert_call_count("turn_on", 2, entity_id="light.kitchen")  # passes — matching calls only
```

### When to use each

| Use case | Method |
|---|---|
| Verify a call happened with key arguments (ignore extras) | `assert_called` or `assert_called_partial` |
| Make partial-match intent explicit in test code | `assert_called_partial` |
| Verify no unexpected arguments were passed | `assert_called_exact` |
| Verify a method (or a specific call) never happened | `assert_not_called` |
| Verify how many times a method (or a specific call) happened | `assert_call_count` |

**Default is partial.** If you use `assert_called("turn_on", entity_id="light.x")` and the call also recorded `brightness=200`, the assertion still passes. Use `assert_called_exact` if that extra argument should be flagged as unexpected. The same partial-match semantics apply to the optional `kwargs` on `assert_not_called` and `assert_call_count`.

---

## Mocking at Boundaries

### The MUT-vs-collaborator rule

Mock external boundaries and the method-under-test's collaborators — never the method under test (MUT) itself. Patching the MUT removes the very code being tested and produces a test that can never fail for the right reason.

**Allowed:** mock `hassette.api.get_states_raw` (an external HA boundary), mock `subscribe_events` when the MUT is `start_recv_and_subscribe` (a collaborator called by the MUT).

**Prohibited:** mock `start_recv_and_subscribe` when testing `serve` (you would be patching away the code under test).

### WebsocketService connection tests — `build_fake_ws`

Connection-layer tests for `WebsocketService` run the real connection method against a fake aiohttp websocket. Import `build_fake_ws` from `hassette.test_utils` and construct the fake session inline:

```python
from unittest.mock import AsyncMock, MagicMock

from hassette.test_utils import build_fake_ws


async def test_connect_ws_sets_ws_and_authenticates(websocket_service):
    fake_ws = build_fake_ws()
    fake_session = MagicMock()
    fake_session.ws_connect = AsyncMock(return_value=fake_ws)

    websocket_service.authenticate = AsyncMock()

    await websocket_service.connect_ws(fake_session)  # real connect_ws (the MUT) runs

    assert websocket_service._ws is fake_ws
```

`build_fake_ws()` returns a thin `ClientWebSocketResponse` stub (a `SimpleNamespace` cast) whose `send_json` / `receive_json` / `receive` / `close` methods are `AsyncMock`s and carries no Home Assistant protocol knowledge. Mocking only `session.ws_connect` (the aiohttp boundary) keeps the real `connect_ws` running. The fake session is built inline per test — it is not exported from `hassette.test_utils`.

---

## Coverage Measurement

### Why local `pytest --cov` reports lower numbers than CI

`pytest --cov` (via pytest-cov) starts coverage tracing in `pytest_configure` — after `tests/conftest.py` has already imported hassette at module scope. Every module-level statement (imports, dataclass field declarations, `def` lines) executed during that early import is permanently invisible to coverage. This underreports by 15-40 percentage points per module.

CI uses `COVERAGE_PROCESS_START` + a `.pth` file (installed by the nox coverage sessions) that starts tracing at interpreter startup — before anything imports. This gives accurate numbers.

To get accurate local coverage, use the nox session:

```bash
uv run nox -s tests_with_coverage -p 3.14
```

Or replicate the approach manually:

```bash
# Install the .pth file (one-time per venv)
SITE=$(python -c "import site; print(site.getsitepackages()[0])")
echo "import coverage; coverage.process_startup()" > "$SITE/coverage_subprocess.pth"

# Run with COVERAGE_PROCESS_START (works with xdist)
COVERAGE_PROCESS_START=pyproject.toml COVERAGE_FILE=.coverage \
  uv run pytest tests/unit tests/integration -n 4 -q
uv run coverage combine && uv run coverage report
```

### What's excluded from coverage

Codegen and pure-data modules are excluded in both `pyproject.toml` (`[tool.coverage.run] omit`) and `.github/codecov.yml` (`ignore`). See the comments in those files for the full list and rationale.

---

## E2E Seed Data Resilience Convention

All E2E test assertions that depend on seed data values **must** use computed constants, not hand-written literals.

### Rule

Any assertion that verifies a value that comes from seed data (telemetry counts, invocation totals, error counts, source locations) must reference a constant from `tests/e2e/mock_fixtures.py` rather than embedding the number or string directly in the test.

**Wrong** (breaks silently when seed data changes):
```python
expect(counts).to_contain_text("30 inv")
```

**Right** (self-updating, single source of truth):
```python
expect(counts).to_contain_text(f"{LISTENER_MY_APP_1_TOTAL_INVOCATIONS} inv")
```

### Constant naming

Module-level constants in `mock_fixtures.py` use tier-qualified names:

| Prefix | Source |
|---|---|
| `LISTENER_` | `build_listener_telemetry()` |
| `JOB_` | `build_job_telemetry()` |

All constants reference builder output objects — never hand-written literals. Add new constants only when an E2E test needs them — speculatively deriving every possible value creates dead code.

### Computation-verifying tests

For tests that verify a formula (not just a displayed value), import the backend helper and use it to derive the expected string. This ensures the test exercises the actual production formula:

```python
from hassette.web.telemetry_helpers import compute_error_rate
from tests.e2e.mock_fixtures import LISTENER_MY_APP_1_TOTAL_INVOCATIONS, ...
```

### What does NOT need constants

Static UI text assertions (page titles, column headers, labels like "Error Rate", "Status") must **not** use constants — they test UI copy, not seed data.

### Acid test

Before merging changes that touch seed data: change a value in `mock_fixtures.py` (e.g., `total_invocations` from 10 to 15), run `uv run nox -s e2e`, confirm all tests pass, then revert.

---

## Frontend Testing (Vitest + MSW)

Frontend tests live in `frontend/src/` alongside the source files they test.
Run them with `cd frontend && npx vitest run`.

### Mocking Layer Rule

Three mocking strategies exist. Choose based on what you are testing:

| What you are testing | Strategy | When to use |
| --- | --- | --- |
| Component rendering given known data | `vi.mock(hook)` | Unit tests for visual output — loading states, conditional rendering, formatting |
| Data-fetching behavior (loading states, error responses, API shape validation) | MSW via `server.use(...)` | Components that call `fetch` and need realistic HTTP responses |
| Hook internals (signal identity, reconnect lifecycle, dependency tracking) | Direct fetcher injection via `fetcher` parameter | Tests for `useApi`, `useScopedApi`, and similar hooks that accept a `fetcher` arg |

**Never mix strategies within a single test file** — pick the one matching the abstraction level being tested.

Explicitly excluded from MSW migration:
- `api/client.test.ts` — tests client-level error parsing (422 detail extraction, 500 message fallback, non-JSON statusText fallback). Retains direct `globalThis.fetch = vi.fn()` because it tests the fetch-adjacent layer.
- `hooks/use-api.test.ts` and `hooks/use-scoped-api.test.ts` — inject a `vi.fn()` fetcher directly into the hook. They never call `fetch` and MSW has nothing to intercept.

### MSW Usage Patterns

**Global setup** (`src/test-setup.ts`): The MSW Node server is created in `src/test/server.ts` and its lifecycle is managed in `test-setup.ts` — started in `beforeAll`, reset in `afterEach`, and closed in `afterAll`. This applies automatically to every test file.

**Default handlers** (`src/test/handlers.ts`): Every endpoint in `src/api/endpoints.ts` has a default handler that returns an empty but valid response shape. Tests that need specific data override the default for that test:

```ts
import { server } from "../../../test/server";
import { http, HttpResponse } from "msw";
import type { components } from "../../../api/generated-types";

it("shows app name from API", async () => {
  server.use(
    http.get("/api/apps/manifests", () =>
      HttpResponse.json<components["schemas"]["AppManifestListResponse"]>({
        total: 1, running: 1, failed: 0, stopped: 0, disabled: 0, blocked: 0,
        manifests: [{ app_key: "my_app", display_name: "My App", ... }],
        only_app: null,
      })
    )
  );

  // render component and assert ...
});
```

`server.use(...)` overrides are scoped to the test. `afterEach` in the global setup calls `server.resetHandlers()`, so overrides don't bleed between tests.

**`onUnhandledRequest` policy**: Set to `'error'` — any unhandled request causes the test to fail immediately. If a new endpoint is added to `endpoints.ts`, a corresponding handler must be added to `handlers.ts`.

### Factory Functions

Shared factories live in `src/test/factories.ts`. Use them instead of per-file factory objects.

Each factory:
- Returns a complete, valid object satisfying the generated type
- Accepts `Partial<T>` overrides for per-test customization
- Uses TypeScript `satisfies` so missing required fields from `generated-types.ts` cause compile errors

```ts
import { createAppGridEntry, createHandlerError } from "../../test/factories";

// Minimal — uses all defaults
const app = createAppGridEntry();

// Override specific fields
const failedApp = createAppGridEntry({ status: "failed", total_errors: 5 });
const err = createHandlerError({ error_type: "TimeoutError", app_key: "my_app" });
```

Available factories: `createManifest`, `createManifestList`, `createAppGridEntry`, `createListener`, `createJob`, `createHealthData`, `createKpis`, `createHandlerError`, `createJobError`, `createLogEntry`, `createSession`, `createTelemetryStatus`.

### Render Helper

Components that call `useAppState()` (reads from `AppStateContext`) need the context provider. Use `renderWithAppState` from `src/test/render-helpers.tsx`:

```tsx
import { renderWithAppState } from "../../test/render-helpers";

it("shows degraded banner when telemetry is down", () => {
  const { getByText } = renderWithAppState(<MyComponent />, {
    stateOverrides: { telemetryDegraded: signal(true) },
  });
  expect(getByText("Telemetry unavailable")).toBeDefined();
});
```

Components that do not call `useAppState()` can use `render` from `@testing-library/preact` directly.

---

## System Tests

System tests run against a real Home Assistant Docker container. They verify end-to-end behavior that cannot be tested with mock infrastructure: WebSocket connectivity, event delivery, reconnection recovery, state synchronization, and scheduler execution under real timing.

### How to Run

```bash
# Via nox (recommended — matches CI)
uv run nox -s system

# Direct pytest invocation
timeout 300 uv run pytest -m system -v -x -n 0
```

The `-n 0` flag is required — system tests must run serially because they share the session-scoped `ha_container` fixture (a single Docker container). Parallel execution would cause tests to interfere with each other.

### Organization

One file per user-visible subsystem:

| File | What it tests |
|---|---|
| `test_startup.py` | Hassette startup lifecycle, session creation, entity visibility |
| `test_bus.py` | Event bus: state-change handlers, attribute-change, glob patterns, debounce, throttle, immediate, duration |
| `test_scheduler.py` | Scheduler: run_in, run_every, run_daily, cron triggers, job groups, jitter |
| `test_state_proxy.py` | State proxy: initial cache, live updates, typed StateManager access |
| `test_api.py` | HA REST/WebSocket API: get_state, call_service, fire_event |
| `test_app_lifecycle.py` | App lifecycle hooks: on_initialize, on_shutdown |
| `test_reconnection.py` | WebSocket reconnection: disconnect detection, reconnect with subscriptions, state proxy refresh |
| `test_shutdown.py` | Graceful shutdown: session status, resource teardown |
| `test_web_api.py` | Web API endpoints: health, apps, config, telemetry, WebSocket events |

### Infrastructure

`tests/system/conftest.py` provides the following fixtures and helpers:

**Session-scoped fixtures:**
- `ha_container` — starts the HA Docker container before the session and tears it down after. Yields the base URL (`http://localhost:18123`).
- `system_app_dir` — returns `Path` to `tests/system/apps/`.

**Config factories:**
- `make_system_config(ha_url, tmp_path)` — returns a `HassetteConfig` pointing at the system test HA instance with `run_web_api=False`.
- `make_web_system_config(ha_url, tmp_path)` — returns `(config, base_url)` with `run_web_api=True` and a dynamically assigned port.

**Context manager:**
- `startup_context(config, timeout=30)` — async context manager that starts Hassette in the background, waits until fully connected (session created, WebSocket ready, event subscriptions active), yields the `Hassette` instance, and shuts it down on exit.

**Test helpers:**
- `toggle_and_capture(bus, api, entity_id, *, service_domain, service_action, timeout)` — registers a `bus.on_state_change` handler, calls `api.call_service` to toggle an entity, and waits until at least one event is captured. Returns the list of captured `RawStateChangeEvent` objects.
- `wait_for_web_server(base_url, *, timeout)` — polls the `/api/health` endpoint until the web server responds (used for web API tests).

### App Fixtures

Committed apps in `tests/system/apps/` cover common patterns:

| File | Purpose |
|---|---|
| `trivial_app.py` | Minimal `App` subclass with no side effects |
| `bus_handler_app.py` | App that registers bus handlers and captures events |
| `config_app.py` | App with a custom `AppConfig` for config-loading tests |

For test-specific variants, write an inline app to `tmp_path` and point `config.app_dir` at it. `autodetect_apps=True` is required when using `app_dir`.

### Key Conventions

- **All tests are async** — use `async def test_*`.
- **`pytestmark = [pytest.mark.system]`** — every test file must declare this at module level so the marker is applied to all tests in the file.
- **All polling via `wait_for`** — never use `asyncio.sleep` as a substitute for a readiness check. Use `wait_for(predicate, timeout=..., desc=...)` from `hassette.test_utils`.
- **No caplog assertions** — test observable behavior (events received, state values, return values), not log output. Log messages are implementation details.
- **Tests are independent of execution order** — each test creates its own `HassetteConfig` and `startup_context`. No shared mutable state between tests.
- **Container name is `hassette-system-ha`** — used for `docker restart` in reconnection tests. Defined in `tests/system/docker-compose.yml`. We use `restart` instead of `pause`/`unpause` because `pause` freezes the process without closing TCP connections, requiring a WebSocket keepalive timeout before disconnect is detected. `restart` immediately closes the connection and is a more realistic failure scenario (HA restarting after an update).
- **Subprocess calls use `check=True`** — all `subprocess.run` calls that invoke docker commands must pass `check=True` so failures are immediately visible as errors, not silent no-ops.
- **Reconnection timeouts are generous** — use at least 15s for disconnect detection and 30s for reconnect confirmation to accommodate container startup latency.
