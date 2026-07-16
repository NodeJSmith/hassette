---
task_id: "T04"
title: "Migrate all test call sites to new HelperClient shape"
status: "planned"
depends_on: ["T01", "T02", "T03"]
implements: ["FR#9", "AC#3", "AC#7"]
---

## Summary

Update all test files that call the old flat helper methods to use the new `api.helpers.*` shape. This is primarily a mechanical call-site migration — the test behaviors stay the same, only the API access path changes. Also update the two hardcoded method-name lists in completeness/parity tests.

## Target Files

- modify: `tests/integration/test_api_helpers.py`
- modify: `tests/unit/test_recording_api_helpers.py`
- modify: `tests/unit/test_recording_sync_facade.py`
- modify: `tests/unit/test_forgotten_await_completeness.py`
- modify: `tests/unit/test_recording_api_write_parity.py`
- read: `tests/unit/test_api_helper_models.py`
- read: `src/hassette/api/helpers.py`

## Prompt

Migrate all test call sites from the old flat API to the new `api.helpers.*` shape. Read the design doc's `## Test Strategy` section.

**Call site migrations (3 test files):**

1. `tests/integration/test_api_helpers.py` (~44 tests):
   - `api.list_input_booleans()` → `api.helpers.list("input_boolean")`
   - `api.create_input_boolean(params)` → `api.helpers.create(params)`
   - `api.update_input_boolean(id, params)` → `api.helpers.update(id, params)`
   - `api.delete_input_boolean(id)` → `api.helpers.delete("input_boolean", id)`
   - Same pattern for all 8 domains
   - `api.increment_counter(eid)` → `api.helpers.increment(eid)`
   - `api.decrement_counter(eid)` → `api.helpers.decrement(eid)`
   - `api.reset_counter(eid)` → `api.helpers.reset(eid)`

2. `tests/unit/test_recording_api_helpers.py` (~21 tests):
   - Same migration pattern but via `recording_api.helpers.*`
   - Check if tests access `recording_api.helper_definitions` directly — update to `recording_api.helpers.helper_definitions`

3. `tests/unit/test_recording_sync_facade.py` (~23 tests):
   - Sync facade call sites change to match the regenerated facade shape
   - `facade.list_input_booleans()` → `facade.helpers.list("input_boolean")` (or whatever the sync facade exposes)

**Hardcoded name list updates (2 test files):**

4. `tests/unit/test_forgotten_await_completeness.py`:
   - `DOCUMENTED_EXCLUSIONS[Api]` contains the 35 flat method names — remove them all
   - Add `HelperClient` to the exclusion dict if any of its methods need exclusion (check if overloaded methods are flagged by the forgotten-await detector)

5. `tests/unit/test_recording_api_write_parity.py`:
   - `KNOWN_READ_METHODS` contains the 8 `list_*` names — update to reflect the new shape
   - The parity test verifies `RecordingApi` implements every `Api` write method — update to check `RecordingHelperClient` implements every `HelperClient` method

**No changes needed:**

6. `tests/unit/test_api_helper_models.py` — tests Pydantic models directly, not Api methods. Read it to confirm no call-site references, then skip.

**Run tests after migration:**

7. Run `uv run nox -s dev` to verify all tests pass.

## Focus

- The migration is mechanical but the volume is large (~91 test functions) — be thorough. Search for every occurrence of the old method names in each file
- `test_recording_api_helpers.py` may reference `recorder.helper_definitions` directly (for seeding assertions) — check if this path changed in T03
- `test_forgotten_await_completeness.py` uses `inspect.getmembers` to find async methods — verify `HelperClient`'s overloaded methods aren't falsely flagged
- `test_recording_api_write_parity.py` introspects `Api` and `RecordingApi` to find method sets — the introspection logic may need updating since methods moved to sub-objects
- `test_recording_sync_facade.py` tests the generated sync facade — it depends on T02's regenerated output

## Verify

- [ ] FR#9: No test file references the old flat method names — `grep -rl 'list_input_\|create_input_\|update_input_\|delete_input_\|list_counter\|create_counter\|update_counter\|delete_counter\|list_timer\|create_timer\|update_timer\|delete_timer\|increment_counter\|decrement_counter\|reset_counter' tests/` returns only `test_bus_dispatch_semaphore.py` (false positive in test name) and `test_api_helper_models.py` (tests models, not Api)
- [ ] AC#3: `uv run nox -s dev` passes with 0 failures
- [ ] AC#7: `prek -a` exits 0 (re-check after all test migrations)
