---
task_id: "T04"
title: "Remove get_state_value_typed and update docs"
status: "planned"
depends_on: []
implements: ["FR#9", "FR#10", "AC#4", "AC#5", "AC#6"]
---

## Summary
Remove `Api.get_state_value_typed` and all its mirrors (sync, recording, sync facade). This method returns `Any` and cannot deliver the typed value its name promises. Update tests that reference it and remove its documentation. Users should use `get_state().value` (typed model) or `get_state_value()` (raw string) instead.

## Target Files
- modify: `src/hassette/api/api.py`
- modify: `src/hassette/api/sync.py`
- modify: `src/hassette/test_utils/recording_api.py`
- modify: `src/hassette/test_utils/sync_facade.py`
- modify: `tests/unit/test_recording_sync_facade.py`
- modify: `tests/unit/test_forgotten_await_completeness.py`
- modify: `tests/unit/test_recording_api_write_parity.py`
- modify: `tests/unit/test_recording_api.py`
- modify: `docs/pages/core-concepts/api/methods.md`
- modify: `docs/pages/testing/factories.md`
- delete: `docs/pages/core-concepts/api/snippets/api_get_state_value_typed.py`
- read: `design/specs/008-standardize-naming-v1/design.md`
- read: `design/specs/008-standardize-naming-v1/tasks/context.md`

## Prompt
Remove `get_state_value_typed` from the API surface and all supporting code.

**Step 1: Remove method implementations**

- `src/hassette/api/api.py`: Delete the `get_state_value_typed` method (starts around line 716).
- `src/hassette/api/sync.py`: Delete the sync mirror (starts around line 345).
- `src/hassette/test_utils/recording_api.py`: Delete the protocol stub (line 192), remove from the call-logging list (line 354), and update the error message string (line 926) that mentions it — remove `get_state_value_typed` from the list while keeping `get_state_value` and `get_attribute`.
- `src/hassette/test_utils/sync_facade.py`: Delete the `NotImplementedError` stub (around line 262).

**Step 2: Update tests**

- `tests/unit/test_recording_sync_facade.py`: Delete the test `test_sync_get_state_value_typed_raises_not_implemented` (around line 250).
- `tests/unit/test_forgotten_await_completeness.py`: Remove `"get_state_value_typed"` from the completeness list (line 156).
- `tests/unit/test_recording_api_write_parity.py`: Remove `"get_state_value_typed"` from the parity list (line 31).
- `tests/unit/test_recording_api.py`: Update the docstring of `test_getattr_tailored_message_for_state_conversion` (line 399) to remove the `get_state_value_typed` mention. The test itself exercises `get_state_value` which is NOT being removed — keep the test, only update the docstring.

**Step 3: Update documentation**

- `docs/pages/core-concepts/api/methods.md`:
  - Remove `get_state_value_typed` from the "Which method to use" table (line 14)
  - Update the cross-reference from `get_state()` docs (line 43) — remove the mention of `get_state_value_typed()` and recommend `get_state().value` instead
  - Delete the full `### get_state_value_typed(entity_id)` section (lines 78–89)
- `docs/pages/testing/factories.md`: Remove line 174 that mentions `get_state_value_typed()`.
- Delete the snippet file: `docs/pages/core-concepts/api/snippets/api_get_state_value_typed.py`

**Step 4: Verify no stale references**
```bash
grep -rn 'get_state_value_typed' src/ tests/ docs/
```
This should return zero matches.

## Focus
- `test_recording_api.py:test_getattr_tailored_message_for_state_conversion` — this test exercises `get_state_value`, NOT `get_state_value_typed`. Only update its docstring to remove the `get_state_value_typed` mention. Do NOT delete the test.
- `recording_api.py` has THREE references: the protocol stub (line 192), the call-logging list (line 354), and the error message string (line 926). All three need updating.
- The methods.md snippet include (`--8<--`) references the snippet file — deleting the file without removing the include directive will break the docs build.
- Read each file before editing to find exact locations — line numbers are approximate.

## Verify
- [ ] FR#9: `get_state_value_typed` method is removed from `api.py`, `sync.py`, `recording_api.py`, and `sync_facade.py`
- [ ] FR#10: Documentation no longer references `get_state_value_typed`; the snippet file is deleted; `methods.md` points users to `get_state().value` and `get_state_value()` as alternatives
- [ ] AC#4: `grep -rn 'get_state_value_typed' src/ tests/ docs/` returns no matches
- [ ] AC#5: `uv run nox -s dev` passes and `prek -a` is clean (cross-cutting gate — verified after all tasks complete)
- [ ] AC#6: Commit uses `refactor!:` prefix with `BREAKING CHANGE:` footer covering all four changes (cross-cutting gate — applied at commit/PR time)
