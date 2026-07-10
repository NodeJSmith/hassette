# Test Conventions

Closes the discovery gap for test infrastructure: this file is loaded on every session, so it is the one-hop pointer to the shared factories and fixtures. The full reference — mock-strategy rationale, scoping rules, factory signatures, mocking-at-boundaries rules — lives in `tests/TESTING.md`. Read that file for anything not covered here.

## Before writing a local factory (BLOCKING)

Before defining a local `make_*` or `build_*` function in a test file, check `src/hassette/test_utils/factories.py` and `src/hassette/test_utils/helpers.py` for an existing factory. Also check `src/hassette/test_utils/web_helpers.py` for web-layer factories. A name match against the shared registry is treated as a duplicate even without an import — `tools/check_test_factories.py` (pre-commit hook) flags local `def make_*`/`def build_*` definitions that shadow a shared factory name, unless annotated `# factory-local: <reason>` for a genuinely different return type or purpose.

If a matching factory exists, import it instead of redefining it. If it doesn't exist and the same shape is needed in 3+ files, add it to `factories.py` (or `web_helpers.py` for web-layer models) rather than letting a fourth local copy accumulate.

## Choosing a mock strategy

Full decision table: `tests/TESTING.md` (Choosing a Mock Strategy, lines 27-37). Quick version:

- **Bus routing, scheduler firing, state propagation** — use `HassetteHarness`. Wires real components, catches integration bugs.
- **Unit test needing a hassette mock with real config validation** — use `make_mock_hassette()`. Sealed by default, no drift from real `HassetteConfig`.
- **HTTP endpoints, HTML responses, WebSocket frames** — use `create_hassette_stub()`. MagicMock stub, fast, no real services.

## Canonical factories and where they live

`src/hassette/test_utils/factories.py` — registration dataclasses and command/job objects:

- `make_listener_registration(**kw)` — `ListenerRegistration`
- `make_job_registration(**kw)` — `ScheduledJobRegistration`
- `make_invoke_handler_cmd(**kw)` — `MagicMock(spec=InvokeHandler)`
- `make_scheduled_job(**kw)` — real `ScheduledJob`, for unit/scheduler tests
- `make_mock_executor()` — `MagicMock` with `execute = AsyncMock()`
- `make_mock_listener(**kw)` — `MagicMock` stand-in for a `Listener` (invoke wiring, identity fields, registration fields)
- `make_scheduler(**kw)` — real `Scheduler` via dynamic subclass, mocked service; params: `wire_dequeue`, `source_tier`, `app_key`
- `make_mock_event()` — `MagicMock(spec=Event)`
- `make_recording_api(states=None)` — `RecordingApi` wired to a mock hassette + state proxy
- `make_hassette_event(topic=..., data=...)` — `Event` carrying a `HassettePayload`
- `make_hass_event(event_type=..., data=..., origin=...)` — `Event` carrying a `HassPayload` (Home Assistant origin)
- `make_mock_parent(**kw)` — `MagicMock` standing in for an owning App resource

`src/hassette/test_utils/helpers.py` — event/state builders and misc test helpers:

- `create_listener(**kw)`, `create_state_change_event(**kw)`, `create_call_service_event(**kw)`
- `make_state_dict(**kw)`, `make_light_state_dict(**kw)`, `make_sensor_state_dict(**kw)`, `make_switch_state_dict(**kw)`
- `make_typed_state(state_class, state_dict)`, `make_task_bucket()`
- `make_crashed_event(**kw)` — `HassetteServiceEvent` with CRASHED status for service-watcher/session tests
- `noop()` — sync no-op, default handler for `create_listener()` and scheduler job tests
- `async_noop()` — async no-op, call it to get a coroutine object (e.g. `bucket.spawn(async_noop())`)

`src/hassette/test_utils/web_helpers.py` — web/API response and snapshot models:

- `make_manifest(**kw)` — `AppManifestInfo`; `make_full_snapshot(manifests)` — `AppFullSnapshot`
- `make_job(**kw)` — `SimpleNamespace` job stub for serialization tests
- `make_real_job(**kw)` — real `ScheduledJob` for web-layer behavior tests

See `tests/TESTING.md` (`make_*/create_*/build_*` naming convention) for how to tell `make_scheduled_job`, `make_real_job`, and `make_job` apart — they build different things despite the similar names.

## 10+ most-used `test_utils` symbols

Ranked by import count across `tests/`, with the shortest working import path:

1. `make_mock_hassette` — `from hassette.test_utils import make_mock_hassette`
2. `HassetteHarness` — `from hassette.test_utils import HassetteHarness`
3. `wait_for` — `from hassette.test_utils import wait_for`
4. `create_listener` — `from hassette.test_utils import create_listener`
5. `noop` — `from hassette.test_utils.helpers import noop`
6. `make_state_dict` — `from hassette.test_utils import make_state_dict`
7. `create_state_change_event` — `from hassette.test_utils import create_state_change_event`
8. `make_scheduled_job` — `from hassette.test_utils import make_scheduled_job`
9. `TEST_TOKEN` — `from hassette.test_utils.config import TEST_TOKEN`
10. `AppTestHarness` — `from hassette.test_utils import AppTestHarness`
11. `make_mock_parent` — `from hassette.test_utils import make_mock_parent`
12. `TEST_SOURCE_LOCATION` — `from hassette.test_utils.config import TEST_SOURCE_LOCATION`

## Directory-level pointers

If a `CLAUDE.md` exists in the test directory you're working in, read it first — it lists that directory's actual fixtures and any module-specific convention. Directories with one today: `tests/unit/bus/`, `tests/unit/core/`, `tests/integration/bus/`, `tests/integration/web_api/`, `tests/integration/telemetry/`.
