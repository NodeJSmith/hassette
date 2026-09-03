---
task_id: "T01"
title: "Create hassette.testing package with Tier 1 public API"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#4", "FR#8"]
---

## Summary

Create the `src/hassette/testing/` package with 16 modules containing all Tier 1 public API symbols. This is the destination package that ships in the wheel and becomes the sole public test API namespace. The package includes public modules (exported via `__all__`), private implementation modules (`_`-prefixed, depended on by public modules), and the Tier 1 pytest fixtures. The old `test_utils` package continues to exist during this task — deletion happens in T05.

## Target Files

- create: `src/hassette/testing/__init__.py`
- create: `src/hassette/testing/app_harness.py`
- create: `src/hassette/testing/recording_api.py`
- create: `src/hassette/testing/api_call.py`
- create: `src/hassette/testing/config.py`
- create: `src/hassette/testing/exceptions.py`
- create: `src/hassette/testing/event_capture.py`
- create: `src/hassette/testing/fixtures.py`
- create: `src/hassette/testing/_simulation.py`
- create: `src/hassette/testing/_time_control.py`
- create: `src/hassette/testing/_sync_facade.py`
- create: `src/hassette/testing/_factories.py`
- create: `src/hassette/testing/_harness.py`
- create: `src/hassette/testing/_reset.py`
- create: `src/hassette/testing/_server.py`
- create: `src/hassette/testing/_ws_mocks.py`
- read: `src/hassette/test_utils/__init__.py`
- read: `src/hassette/test_utils/app_harness.py`
- read: `src/hassette/test_utils/recording_api.py`
- read: `src/hassette/test_utils/api_call.py`
- read: `src/hassette/test_utils/config.py`
- read: `src/hassette/test_utils/exceptions.py`
- read: `src/hassette/test_utils/event_capture.py`
- read: `src/hassette/test_utils/fixtures.py`
- read: `src/hassette/test_utils/harness.py`
- read: `src/hassette/test_utils/simulation.py`
- read: `src/hassette/test_utils/time_control.py`
- read: `src/hassette/test_utils/sync_facade.py`
- read: `src/hassette/test_utils/helpers.py`
- read: `src/hassette/test_utils/reset.py`
- read: `src/hassette/test_utils/test_server.py`
- read: `src/hassette/test_utils/ws_mocks.py`
- read: `design/specs/108-testing-infra-split/design.md`

## Prompt

Create the `src/hassette/testing/` package by moving and organizing modules from `src/hassette/test_utils/` according to the design doc's `## Architecture → Module mapping (authoritative)` table.

### Module moves (whole-file, no splits)

These source modules move entirely to `hassette.testing/` as their destination name. Copy the file content, then update any internal imports from `hassette.test_utils.<module>` to `hassette.testing.<module>` (or `hassette.testing._<module>` for private modules). Keep `from hassette.test_utils` imports to *other* modules unchanged for now — the codemod in T03 handles those.

| Source → Destination |
|---|
| `app_harness.py` → `app_harness.py` |
| `recording_api.py` → `recording_api.py` |
| `api_call.py` → `api_call.py` |
| `config.py` → `config.py` |
| `exceptions.py` → `exceptions.py` |
| `event_capture.py` → `event_capture.py` |
| `time_control.py` → `_time_control.py` |
| `sync_facade.py` → `_sync_facade.py` |
| `reset.py` → `_reset.py` |
| `test_server.py` → `_server.py` |
| `ws_mocks.py` → `_ws_mocks.py` |

### Modules requiring splits or folds

1. **`harness.py` → `_harness.py`**: Copy the entire file EXCEPT `preserve_config`. `preserve_config` goes to `tests/support/harness.py` (T02's job). The `_harness.py` file keeps `HassetteHarness`, `wait_for`, `build_harness`, and all supporting code. Update internal imports to reference `hassette.testing._reset`, `hassette.testing._server`, `hassette.testing._ws_mocks`.

2. **`helpers.py` → `_factories.py`** (Tier 1 factories only): Extract these 8 functions into `_factories.py`: `create_state_change_event`, `create_call_service_event`, `make_state_dict`, `make_light_state_dict`, `make_sensor_state_dict`, `make_switch_state_dict`, `make_typed_state`, `make_full_state_change_event`. Include any imports and module-level constants these functions depend on.

3. **`simulation.py` → `_simulation.py`**: Copy the entire file. Additionally, fold in `create_component_loaded_event` and `create_service_registered_event` from `helpers.py` (these are ~16-line functions `_simulation.py` uses). This avoids an extra private module.

4. **`fixtures.py` → `fixtures.py`** (Tier 1 only): Extract only `dummy_cache`, `event_capture`, and `build_harness` fixture functions. These are the fixtures that ship in the wheel for app authors. The remaining fixtures (`hassette_harness`, `hassette_with_*`, etc.) go to `tests/support/fixtures.py` (T02's job).

### `__init__.py`

Create `src/hassette/testing/__init__.py` with re-exports and `__all__`. Follow the pattern in the current `test_utils/__init__.py` (self-alias `X as X` for re-exports to satisfy ruff). The `__all__` must contain exactly the 21 Tier 1 symbols listed in the design doc's `### Tier 1 symbol set` section:

```python
__all__ = [
    "ApiCall",
    "AppConfigurationError",
    "AppTestHarness",
    "DrainError",
    "DrainFailure",
    "DrainTimeout",
    "EventCapture",
    "HassetteHarness",
    "RecordingApi",
    "build_harness",
    "create_call_service_event",
    "create_state_change_event",
    "dummy_cache",
    "make_full_state_change_event",
    "make_light_state_dict",
    "make_sensor_state_dict",
    "make_state_dict",
    "make_switch_state_dict",
    "make_test_config",
    "make_typed_state",
    "wait_for",
]
```

Import sources for the re-exports:
- `ApiCall` from `.api_call`
- `AppConfigurationError`, `AppTestHarness` from `.app_harness`
- `DrainError`, `DrainFailure`, `DrainTimeout` from `.exceptions`
- `EventCapture` from `.event_capture`
- `HassetteHarness`, `wait_for` from `._harness`
- `RecordingApi` from `.recording_api`
- `build_harness`, `dummy_cache` from `.fixtures`
- `create_call_service_event`, `create_state_change_event`, `make_full_state_change_event`, `make_light_state_dict`, `make_sensor_state_dict`, `make_state_dict`, `make_switch_state_dict`, `make_typed_state` from `._factories`
- `make_test_config` from `.config`

### Internal import updates

When creating each file, update imports that reference other modules *within the same package* to use the new paths. For example, if `app_harness.py` imports from `hassette.test_utils.simulation`, change it to `from hassette.testing._simulation import ...`. Leave imports to modules outside this package (e.g., `hassette.core`, `hassette.bus`) unchanged. Leave imports referencing modules that will live in `tests/support/` (e.g., `hassette.test_utils.factories`) unchanged for now — the codemod handles those.

## Focus

- The `_harness.py` file is the most complex because it imports from `_reset`, `_server`, and `_ws_mocks`. Read `src/hassette/test_utils/harness.py` carefully to identify all its internal dependencies before creating `_harness.py`.
- `app_harness.py` imports from `simulation`, `time_control`, `sync_facade`, `harness`, and `config`. All of these become `_simulation`, `_time_control`, `_sync_facade`, `_harness`, and `config` in the new package.
- `fixtures.py` Tier 1 split: `build_harness` is a context manager that creates a `HassetteHarness`. It imports from `harness.py`. In the new package, it imports from `._harness`.
- `recording_api.py` imports from `sync_facade` which becomes `_sync_facade`, and from `api_call` which stays `api_call`.
- The `RecordingHelperClient` class in `recording_api.py` must ride along — it's part of the same module.
- Do NOT create a `py.typed` marker or modify `pyproject.toml` package discovery — `hassette.testing` is a sub-package of `hassette` and is automatically included.

## Verify

- [ ] FR#1: `python -c "from hassette.testing import AppTestHarness, RecordingApi, HassetteHarness, wait_for, build_harness, EventCapture, make_full_state_change_event"` succeeds
- [ ] FR#2: `python -c "from hassette.testing import make_mock_hassette"` raises `ImportError`
- [ ] FR#4: `python -c "import hassette.testing; assert len(hassette.testing.__all__) == 21"` succeeds
- [ ] FR#8: `python -c "from hassette.testing.fixtures import dummy_cache, event_capture, build_harness"` succeeds
