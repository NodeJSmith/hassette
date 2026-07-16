---
task_id: "T02"
title: "Update codegen to generate HelperClient sync facades"
status: "planned"
depends_on: ["T01", "T03"]
implements: ["FR#7", "FR#9", "AC#5"]
---

## Summary

Extend the sync facade generator to produce `HelperClientSyncFacade` and `RecordingHelperClientSyncFacade`. Add `generate_sync_helpers()` and `generate_sync_recording_helpers()` to the codegen pipeline, update the CLI to include a `helpers` target, and regenerate `sync.py` and `test_utils/sync_facade.py`. Update `ApiSyncFacade`'s class header to wire `self.helpers`.

## Target Files

- modify: `codegen/src/hassette_codegen/sync_facade/generic.py`
- modify: `codegen/src/hassette_codegen/sync_facade/recording.py`
- modify: `codegen/src/hassette_codegen/sync_facade/cli.py`
- modify: `codegen/src/hassette_codegen/sync_facade/__main__.py`
- create: `src/hassette/api/sync_helpers.py`
- modify: `src/hassette/api/sync.py`
- modify: `src/hassette/test_utils/sync_facade.py`
- read: `src/hassette/api/helpers.py`
- read: `src/hassette/test_utils/recording_api.py`
- read: `codegen/src/hassette_codegen/sync_facade/ast_utils.py`

## Prompt

Extend the sync facade codegen to handle `HelperClient`. Read the design doc's `## Architecture → Codegen changes` section.

**generic.py changes:**

1. Add `HELPERS_HEADER` string constant — module-level imports for `HelperClientSyncFacade`. Follow the `HEADER` pattern (hand-maintained import block). Import all helper model types (`Create*Params`, `Update*Params`, `*Record` from `hassette.models.helpers`) and `HelperDomain` from `hassette.api.helpers`.

2. Add `HELPERS_CLASS_HEADER` string constant — the `HelperClientSyncFacade(Resource)` class definition with `__init__`, `on_initialize`, and `config_log_level`. The `__init__` takes `hassette` and `helpers` keyword arg, stores `self._helpers`. Follow the `CLASS_HEADER` pattern exactly.

3. Add `generate_sync_helpers(helpers_path: Path) -> str` — calls `_generate_facade(helpers_path, "HelperClient", header=HELPERS_HEADER, class_header=HELPERS_CLASS_HEADER, wrapped_attr="_helpers")`.

4. Update the `HEADER` and `CLASS_HEADER` for `ApiSyncFacade`:
   - Remove helper model imports from `HEADER` (they're no longer needed on `ApiSyncFacade` — they move to `HELPERS_HEADER`)
   - Add `from hassette.api.sync_helpers import HelperClientSyncFacade` to `HEADER`
   - Add `self.helpers = self.add_child(HelperClientSyncFacade, helpers=self._api.helpers)` to `CLASS_HEADER`'s `__init__` — this wires the nested sync facade via `add_child`, which registers it in `self.children` for lifecycle management (direct construction with `parent=` skips this registration and the facade never gets `on_initialize`/`mark_ready` called)

**recording.py changes:**

5. Add `generate_sync_recording_helpers()` following the same pattern as `generate_sync_recording()` but pointing at the new `RecordingHelperClient` class (from T03).

**cli.py / __main__.py changes:**

6. Add `helpers` as a generation target in the CLI. Follow the existing pattern for `api`, `bus`, `scheduler` targets. The `--target all` flag must include `helpers`.

**Regenerate:**

7. Run `uv run python codegen/src/hassette_codegen/sync_facade/ --target all` to regenerate all sync facades. Commit the regenerated `sync.py` and `test_utils/sync_facade.py`.

**Important:** The old 35 flat helper methods will be gone from `Api` (removed in T01), so the regenerated `sync.py` will naturally omit them. The new `HelperClientSyncFacade` methods appear in a separate generated class/file.

## Focus

- The generator finds classes by exact name match in `module.body` (`generic.py:275-282`) — `HelperClient` must be a top-level class in `helpers.py`
- `is_wrappable` in `ast_utils.py` excludes methods starting with `_` and lifecycle methods — verify `list`, `create`, `update`, `delete`, `increment`, `decrement`, `reset` all pass this filter
- The `HEADER` imports are hand-maintained string literals — if a method's type annotation references a type not in the header, the generated file fails to import (caught by the drift gate)
- `recording.py`'s generator correlates `Api.foo` and `RecordingApi.foo` by name — `HelperClient.foo` and `RecordingHelperClient.foo` must use identical method names
- The `--check` flag on the CLI does a diff check — `uv run python codegen/src/hassette_codegen/sync_facade/ --target all --check` must exit 0 after regeneration
- `HelperClientSyncFacade` goes into `src/hassette/api/sync_helpers.py` (a separate file, following the one-file-per-facade convention seen with `api/sync.py`, `bus/sync.py`, `scheduler/sync.py`)

## Verify

- [ ] FR#7: `HelperClientSyncFacade` class exists in generated output with `list`, `create`, `update`, `delete`, `increment`, `decrement`, `reset` methods wrapping via `task_bucket.run_sync()`
- [ ] FR#9: Regenerated `sync.py` and `test_utils/sync_facade.py` no longer contain any of the 35 flat helper method wrappers — `grep -c 'def list_input_\|def create_input_\|def update_input_\|def delete_input_\|def list_counter\|def create_counter\|def update_counter\|def delete_counter\|def list_timer\|def create_timer\|def update_timer\|def delete_timer\|def increment_counter\|def decrement_counter\|def reset_counter' src/hassette/api/sync.py src/hassette/test_utils/sync_facade.py` returns 0
- [ ] AC#5: `uv run python codegen/src/hassette_codegen/sync_facade/ --target all --check` exits 0
