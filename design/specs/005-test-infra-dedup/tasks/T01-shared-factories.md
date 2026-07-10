---
task_id: "T01"
title: "Add 6 shared factories to test_utils/factories.py"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#6"]
---

## Summary
Add the 6 new shared factory functions to `src/hassette/test_utils/factories.py` and wire them into the export chain. These factories are the foundation — all subsequent migration tasks import from them. No local definitions are deleted yet; this task only creates the shared versions.

## Target Files
- modify: `src/hassette/test_utils/factories.py`
- modify: `src/hassette/test_utils/__init__.py`
- modify: `src/hassette/test_utils/_internal/__init__.py`
- read: `src/hassette/test_utils/config.py`
- read: `src/hassette/scheduler/triggers.py`
- read: `src/hassette/types/enums.py`
- read: `src/hassette/events/base.py`
- read: `src/hassette/conversion/__init__.py`
- read: `src/hassette/core/state_proxy.py`
- read: `src/hassette/test_utils/mock_hassette.py`
- read: `src/hassette/test_utils/recording_api.py`
- read: `tests/unit/test_recording_api.py`
- read: `tests/unit/test_recording_api_helpers.py`
- read: `tests/unit/test_recording_sync_facade.py`

## Prompt
Add 6 factory functions to `src/hassette/test_utils/factories.py`, following the existing keyword-only style with sensible defaults. See `context.md` → Convention Examples for the exact pattern.

**Factories to add:**

1. `make_scheduled_job(**kw) -> ScheduledJob` — keyword-only args: `job` (default `lambda: None`), `name` (`"test_job"`), `owner_id` (`"test_owner"`), `next_run` (`date_utils.now()`), `trigger`, `group`, `jitter`, `timeout`, `timeout_disabled`, `error_handler`, `mode`, `db_id`, `predicate`. Returns a real `ScheduledJob`. Import `ScheduledJob` from `hassette.scheduler.classes` and trigger types from `hassette.scheduler.triggers`.

2. `make_mock_executor() -> MagicMock` — no args. Returns `MagicMock()` with `execute = AsyncMock()`.

3. `make_mock_event() -> MagicMock` — no args. Returns `MagicMock(spec=Event)`. Import `Event` from `hassette.events.base`.

4. `make_recording_api(states=None) -> RecordingApi` — returns a `RecordingApi` wired to `make_mock_hassette(sealed=False)` with `state_registry = STATE_REGISTRY` and an `AsyncMock(spec=StateProxy)` whose `.states` is `states or {}` and `.is_ready` returns `True`. Import `RecordingApi` from `hassette.test_utils.recording_api`, `make_mock_hassette` from `hassette.test_utils.mock_hassette`, `STATE_REGISTRY` from `hassette.conversion`, `StateProxy` from `hassette.core.state_proxy`.

5. `make_hassette_event(topic="hassette.ready", data=None) -> Event` — returns `Event(topic=topic, payload=HassettePayload(data=data))`. Import `HassettePayload` from `hassette.events.base`.

6. `make_mock_parent(*, app_key="test_app", index=0, unique_name="test_app.0", source_tier="app", class_name="TestApp", app_config=None) -> MagicMock` — returns a `MagicMock` with all 6 attributes set. The canonical definition to match is `tests/unit/conftest.py:85`.

**Export wiring:**
- Add all 6 to `src/hassette/test_utils/_internal/__init__.py` re-exports (import from `..factories`)
- Add all 6 to `src/hassette/test_utils/__init__.py` — as Tier 2 re-exports (NOT in `__all__`), consistent with how existing web_helpers factories are exported

## Focus
- The existing 3 factories in `factories.py` import `DEFAULT_TEST_APP_KEY` and `TEST_SOURCE_LOCATION` from `test_utils.config` — use these shared constants where applicable in new factories.
- `make_recording_api` is the most complex — study the 3 existing local versions to get the mock wiring right: `tests/unit/test_recording_api.py`, `tests/unit/test_recording_api_helpers.py`, `tests/unit/test_recording_sync_facade.py`.
- `make_mock_parent` has 4 distinct field-set shapes across 8 migration sites — the shared version includes all 6 fields with defaults so every variant is subsumed.
- `_internal/__init__.py` does NOT currently import from `factories.py` — you'll need to add the import line.

## Verify
- [ ] FR#1: `make_scheduled_job()` exists in `factories.py`, returns a real `ScheduledJob`, accepts all listed keyword-only args with defaults
- [ ] FR#2: `make_mock_executor()` exists in `factories.py`, returns `MagicMock` with `execute = AsyncMock()`
- [ ] FR#3: `make_mock_event()` exists in `factories.py`, returns `MagicMock(spec=Event)`
- [ ] FR#4: `make_recording_api()` exists in `factories.py`, returns a real `RecordingApi` wired to mocks
- [ ] FR#5: `make_hassette_event()` exists in `factories.py`, returns `Event` with `HassettePayload`
- [ ] FR#6: `make_mock_parent()` exists in `factories.py`, returns `MagicMock` with 6 attributes
