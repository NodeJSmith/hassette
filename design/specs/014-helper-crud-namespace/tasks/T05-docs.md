---
task_id: "T05"
title: "Update docs and docstrings for new helper API shape"
status: "planned"
depends_on: ["T01", "T03"]
implements: ["FR#9", "AC#6"]
---

## Summary

Update all documentation artifacts to reflect the new `api.helpers.*` API shape. This includes the managing-helpers docs page, its type-checked snippet files, the vacation-mode recipe, docstring cross-references in source code, and the CLAUDE.md architecture description.

## Target Files

- modify: `docs/pages/core-concepts/api/managing-helpers.md`
- modify: `docs/pages/core-concepts/api/snippets/managing-helpers/crud_operations.py`
- modify: `docs/pages/core-concepts/api/snippets/managing-helpers/create_helper.py`
- modify: `docs/pages/core-concepts/api/snippets/managing-helpers/counter_shortcuts.py`
- modify: `docs/pages/core-concepts/api/snippets/managing-helpers/testing_harness.py`
- modify: `docs/pages/recipes/vacation-mode-toggle.md`
- modify: `docs/pages/core-concepts/api/index.md`
- modify: `src/hassette/exceptions.py`
- modify: `src/hassette/models/states/counter.py`
- modify: `CLAUDE.md`
- read: `docs/pages/core-concepts/api/snippets/managing-helpers/timer_call_service.py`
- read: `docs/pyrightconfig.json`

## Prompt

Update all documentation to use the new `api.helpers.*` call sites. Read the design doc's `## Documentation Updates` section.

**Docs site pages:**

1. `docs/pages/core-concepts/api/managing-helpers.md` — the primary helpers doc:
   - Update all method references (e.g., `list_input_booleans()` → `api.helpers.list("input_boolean")`)
   - Rewrite the method reference table (currently lists flat method names per domain) — replace with the 7 `HelperClient` method signatures and explain the dispatch pattern
   - Update prose describing the API (e.g., "call `self.api.create_input_boolean`" → "call `self.api.helpers.create`")
   - Note the import requirement for params models

2. `docs/pages/core-concepts/api/snippets/managing-helpers/crud_operations.py`:
   - Update `self.api.list_input_booleans()` → `self.api.helpers.list("input_boolean")`
   - Update `self.api.update_input_boolean(...)` → `self.api.helpers.update(...)`
   - Update `self.api.delete_input_boolean(...)` → `self.api.helpers.delete("input_boolean", ...)`
   - Update `self.api.create_input_boolean(...)` → `self.api.helpers.create(...)`

3. `docs/pages/core-concepts/api/snippets/managing-helpers/create_helper.py`:
   - Update `self.api.create_input_boolean(...)` → `self.api.helpers.create(...)`

4. `docs/pages/core-concepts/api/snippets/managing-helpers/counter_shortcuts.py`:
   - Update `self.api.increment_counter(...)` → `self.api.helpers.increment(...)`
   - Update `self.api.create_counter(...)` → `self.api.helpers.create(...)`

5. `docs/pages/core-concepts/api/snippets/managing-helpers/testing_harness.py`:
   - Update recording API assertions to use the new shape
   - `harness.api_recorder.assert_call_count("create_input_boolean", 1)` → update method name
   - `harness.api_recorder.list_input_booleans()` → `harness.api_recorder.helpers.list("input_boolean")`

6. `docs/pages/recipes/vacation-mode-toggle.md`:
   - Update `self.api.create_input_boolean` reference to `self.api.helpers.create`

7. `docs/pages/core-concepts/api/index.md`:
   - Check for and update any references to flat helper methods

8. Read `docs/pages/core-concepts/api/snippets/managing-helpers/timer_call_service.py` — verify it doesn't reference flat helper methods (it likely uses `call_service()` directly and needs no change)

**Source docstring cross-references (gap check findings):**

9. `src/hassette/exceptions.py:101` — the `FailedMessageError` docstring has an example using `api.update_input_boolean(...)`. Update to `api.helpers.update(...)`.

10. `src/hassette/models/states/counter.py:26` — docstring references `Api.list_counters`/`create_counter`/`update_counter`. Update to `api.helpers.list("counter")`/`api.helpers.create(...)`/`api.helpers.update(...)`.

**CLAUDE.md:**

11. Update the Architecture section's `Api` description to mention the `helpers` attribute pattern.

**Type-check verification:**

12. Run `cd docs && pyright --project pyrightconfig.json` to verify all snippets type-check with the new call sites.

## Focus

- The doc snippets are type-checked in CI via `docs/pyrightconfig.json` — they must import `HelperClient` types correctly and use the exact method signatures
- `timer_call_service.py` uses `call_service()` directly — likely no change, but read it to confirm
- The managing-helpers.md page has a method reference table at lines 117-124 — this needs a complete rewrite, not just name substitution
- The testing_harness.py snippet uses `assert_call_count` with method name strings — these strings must match the new method names used by `RecordingHelperClient`
- Check `docs/pages/core-concepts/api/index.md` for any flat method references in the API overview

## Verify

- [ ] FR#9: No doc file references old flat method names — `grep -rl 'create_input_boolean\|list_input_booleans\|increment_counter' docs/` returns empty
- [ ] AC#6: `cd docs && pyright --project pyrightconfig.json` exits 0
