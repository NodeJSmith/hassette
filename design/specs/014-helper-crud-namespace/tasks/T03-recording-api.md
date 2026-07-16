---
task_id: "T03"
title: "Refactor RecordingApi to expose RecordingHelperClient"
status: "done"
depends_on: ["T01"]
implements: ["FR#8", "FR#9"]
---

## Summary

Extract `RecordingHelperClient` from `RecordingApi`, moving the 35 flat helper method stubs and implementations behind a `helpers` attribute. Reuse the existing generic `_list_helper`, `_create_helper`, `_update_helper`, `_delete_helper` methods and the `RECORD_TYPE_TO_DOMAIN` dispatch table. Update the `ApiProtocol` to replace 35 flat stubs with a `helpers` property.

## Target Files

- modify: `src/hassette/test_utils/recording_api.py`
- read: `src/hassette/api/helpers.py`
- read: `src/hassette/models/helpers/__init__.py`

## Prompt

Refactor `src/hassette/test_utils/recording_api.py` to match the new `HelperClient` shape. Read the design doc's `## Architecture → Recording API changes` section.

**RecordingHelperClient class:**

1. Create a `RecordingHelperClient` class within `recording_api.py` (not a separate file — keep it co-located with `RecordingApi`).

2. Move ownership of `helper_definitions` from `RecordingApi` to `RecordingHelperClient`. `RecordingApi.__init__` currently initializes `self.helper_definitions = {d: {} for d in SUPPORTED_HELPER_DOMAINS}` — move this to `RecordingHelperClient.__init__`.

3. Move the generic helper methods (`_list_helper`, `_create_helper`, `_update_helper`, `_delete_helper`, `_new_helper_id`) to `RecordingHelperClient`. These are currently at `recording_api.py:642-750`.

4. `RecordingHelperClient` exposes 7 public methods matching `HelperClient`:
   - `list(domain)` — delegates to `_list_helper`
   - `create(params)` — delegates to `_create_helper`, dispatching on `type(params)` via `RECORD_TYPE_TO_DOMAIN`
   - `update(helper_id, params)` — delegates to `_update_helper`
   - `delete(domain, helper_id)` — delegates to `_delete_helper`
   - `increment(entity_id)` — records call, delegates to parent `RecordingApi.call_service`
   - `decrement(entity_id)` — same
   - `reset(entity_id)` — same

5. Keep `RECORD_TYPE_TO_DOMAIN`, `SUPPORTED_HELPER_DOMAINS`, and `slugify_helper_name` at module level — they're shared infrastructure.

6. `RecordingHelperClient` needs access to `RecordingApi`'s `calls` list for recording. Pass the parent `RecordingApi` as an `__init__` parameter.

**RecordingApi changes:**

7. Remove all 35 flat helper method implementations (lines 752-915). Remove the 3 counter shortcut implementations.

8. Add `self.helpers = RecordingHelperClient(self)` in `RecordingApi.__init__`.

9. `seed_helper()` — check if it references `self.helper_definitions` directly. If so, update to delegate to `self.helpers.helper_definitions`.

**ApiProtocol changes:**

10. Update the protocol class (at `recording_api.py:129`) to replace the 35 flat method stubs (lines 244-294) with a `helpers` property/attribute stub matching the `HelperClient` interface.

**Preserve behavioral invariants:**
- `input_select` deep-copy behavior (`deep_copy=True` in `RECORD_TYPE_TO_DOMAIN`)
- `FailedMessageError` with `code="not_found"` on missing helper IDs
- Call recording via `self.calls.append(ApiCall(...))`
- `slugify_helper_name` for ID generation on create

## Focus

- The `RecordingApi` has a `calls: list[ApiCall]` field — `RecordingHelperClient` needs to append to the same list, so it needs a reference to the parent
- `seed_helper()` at `recording_api.py:390-410` sets up initial state in `self.helper_definitions` — trace all callers to ensure they work with the new `self.helpers.helper_definitions` path
- The `ApiProtocol` at line 129 is used for type checking in tests — verify it has the right shape after updating
- `RECORD_TYPE_TO_DOMAIN` is also used by the `seed_helper()` method (line 394-395) and the validation check at line 87-88 — these must still work

## Verify

- [ ] FR#8: `RecordingApi.helpers` returns a `RecordingHelperClient` with `list`, `create`, `update`, `delete`, `increment`, `decrement`, `reset` methods
- [ ] FR#9: `RecordingApi` has no flat helper methods — `grep -c 'async def \(list_input\|create_input\|update_input\|delete_input\|list_counter\|create_counter\|update_counter\|delete_counter\|list_timer\|create_timer\|update_timer\|delete_timer\|increment_counter\|decrement_counter\|reset_counter\)' src/hassette/test_utils/recording_api.py` returns 0
