# Design: Namespace Helper CRUD Behind Api.helpers

**Date:** 2026-07-16
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-07-16-helper-crud-api-shape/research.md

## Problem

The `Api` class exposes 35 flat helper CRUD methods (8 domains × 4 ops + 3 counter shortcuts) at `src/hassette/api/api.py:989-1477`. These methods bloat the public API surface — `Api` has grown to ~72 public methods, making autocomplete noisy and the class hard to navigate. This violates the minimize-public-API-surface principle and the 800-line file cap (api.py is 1477 lines). The v1.0 API freeze is approaching, so the shape must be right before it becomes a compatibility commitment.

## Goals

- Reduce Api's helper-related public surface from 35 methods to 1 property (`helpers`)
- Preserve full type safety: typed inputs via params models, typed return values via `@overload` declarations
- Close #422 (Split api.py into focused submodules) for the helper CRUD portion
- Update all downstream surfaces: codegen, recording API, sync facades, tests, and docs

## Non-Goals

- No compatibility shims — this is a breaking change per repo convention
- No changes to the helper Pydantic models (`src/hassette/models/helpers/`) — they are reused as-is
- No changes to `_ws_helper_call()` — the shared WS infrastructure function stays in `api.py`

## User Scenarios

### App author: automation developer

- **Goal:** Create, read, update, and delete HA helper entities from app code
- **Context:** During `on_initialize()` or in event handlers

#### Provision a helper on first run

1. **List existing helpers**
   - Calls: `records = await self.api.helpers.list("input_boolean")`
   - Sees: list of `InputBooleanRecord` instances (typed return via overload)
   - Decides: whether the target helper already exists

2. **Create if missing**
   - Calls: `record = await self.api.helpers.create(CreateInputBooleanParams(name="vacation_mode", initial=True))`
   - Sees: `InputBooleanRecord` returned (typed return via overload on params type)
   - Then: caches `record.id` for subsequent operations

#### Increment a counter on every event

1. **Increment counter state**
   - Calls: `await self.api.helpers.increment("counter.motion_count")`
   - Then: counter entity value increases by its configured step

## Functional Requirements

- **FR#1** `Api` exposes a `helpers` attribute returning a `HelperClient` instance. The `HelperClient` class lives in `src/hassette/api/helpers.py`. Wired as `self.helpers = self.add_child(HelperClient, api=self)` in `Api.__init__`, matching the `self.sync` convention.
- **FR#2** `HelperClient.list(domain)` accepts a `HelperDomain` literal union and returns the domain-specific `list[Record]` type via `@overload` declarations. 8 overloads, one per domain.
- **FR#3** `HelperClient.create(params)` accepts a `Create*Params` model and returns the domain-specific `Record` type via `@overload` declarations. The params model type is the dispatch key — `type(params)` resolves to the domain string and record type via a registry. 8 overloads.
- **FR#4** `HelperClient.update(helper_id, params)` accepts a helper ID string and an `Update*Params` model, returning the domain-specific `Record` type via `@overload`. 8 overloads.
- **FR#5** `HelperClient.delete(domain, helper_id)` accepts a `HelperDomain` literal and helper ID string, returns `None`. 8 overloads (for consistency, though return type doesn't vary).
- **FR#6** `HelperClient.increment(entity_id)`, `HelperClient.decrement(entity_id)`, and `HelperClient.reset(entity_id)` wrap counter service calls, moved from flat `Api` methods.
- **FR#7** The sync facade generator produces a `HelperClientSyncFacade` class that wraps all `HelperClient` methods via `task_bucket.run_sync()`. `ApiSyncFacade` exposes `self.helpers` returning this facade.
- **FR#8** `RecordingApi` exposes a `helpers` attribute returning a `RecordingHelperClient` that records calls and operates on in-memory `helper_definitions`, preserving existing test recording behavior.
- **FR#9** All 35 flat helper methods are removed from `Api`, `ApiSyncFacade`, `RecordingApi`, `RecordingSyncFacade`, and the `Api` protocol stubs.
- **FR#10** The `HelperClient` and all overloads pass pyright strict mode (`prek pyright -a --stage pre-push`).

## Edge Cases

- **Unknown domain string to `list()` or `delete()`**: `HelperDomain` is a `Literal` union — pyright rejects invalid strings at type-check time. At runtime, the registry lookup raises `KeyError` with context.
- **Unknown params type to `create()` or `update()`**: `type(params)` not in registry raises `KeyError`. This only happens if someone constructs a model that isn't in the registry — a programming error, not a runtime edge case.
- **`input_datetime` validation**: `CreateInputDatetimeParams` has a `model_validator` requiring `has_date or has_time`. This validation happens in the params model before `HelperClient` touches it — no change needed.

## Acceptance Criteria

- **AC#1** `Api` has no public methods matching `list_input_*`, `create_input_*`, `update_input_*`, `delete_input_*`, `list_counter*`, `create_counter`, `update_counter`, `delete_counter`, `list_timer*`, `create_timer`, `update_timer`, `delete_timer`, `increment_counter`, `decrement_counter`, `reset_counter`. Verified by: `grep -c 'async def \(list_input\|create_input\|update_input\|delete_input\|list_counter\|create_counter\|update_counter\|delete_counter\|list_timer\|create_timer\|update_timer\|delete_timer\|increment_counter\|decrement_counter\|reset_counter\)' src/hassette/api/api.py` returns 0. (FR#9)
- **AC#2** `Api.helpers` returns a `HelperClient` instance. Verified by: `grep -c 'self\.helpers = self\.add_child(HelperClient' src/hassette/api/api.py` returns 1. (FR#1)
- **AC#3** All existing helper CRUD tests pass with updated call sites. Verified by: `uv run nox -s dev` passes. (FR#1-FR#9)
- **AC#4** Pyright strict mode passes. Verified by: `prek pyright -a --stage pre-push` exits 0. (FR#10)
- **AC#5** Codegen drift check passes. Verified by: `uv run python codegen/src/hassette_codegen/sync_facade/ --target all --check` exits 0. (FR#7)
- **AC#6** Doc snippets type-check. Verified by: `cd docs && pyright --project pyrightconfig.json` exits 0.
- **AC#7** All pre-commit hooks pass. Verified by: `prek -a` exits 0.

## Key Constraints

- The sync facade generator (`codegen/sync_facade/generic.py:_generate_facade`) walks a single `ast.ClassDef` by exact name match. `HelperClient` must be defined in its own source file so the generator can find it independently — it cannot be an inner class of `Api`.
- Overloads are hand-maintained, not generated. HA helper schemas change roughly once a year (3 schema-affecting commits across all 8 domains in the last 2 years). Codegen for overloads would add generator complexity for negligible maintenance savings.
- `HelperClient` must be a `Resource` subclass (not a plain object) because the sync facade pattern requires `task_bucket` for `run_sync()`. It is added as a child of `Api` via `self.helpers = self.add_child(HelperClient, api=self)`.
- The `list()` and `delete()` methods dispatch on a `HelperDomain` literal string (not a params model) because they have no params object to derive the domain from. This creates a minor asymmetry with `create()` and `update()` (which dispatch on `type(params)`), but it is ergonomically natural.

## Dependencies and Assumptions

- Assumes no external consumers import the 35 flat methods by name. Hassette is a framework whose callers are user apps not in this repo — there is no public PyPI API stability commitment pre-v1.0.
- CI workflows (`lint.yml`, `tests.yml`) run the codegen drift check and doc snippet type-checking automatically — no workflow changes needed.

## Architecture

### New file: `src/hassette/api/helpers.py`

Contains `HelperClient(Resource)` with:

**Type definitions:**
```python
HelperDomain = Literal[
    "input_boolean", "input_number", "input_text", "input_select",
    "input_datetime", "input_button", "counter", "timer",
]
```

**Registry (dispatch table):**
```python
# Maps Create*Params type → (domain_string, Record type, id_key_name)
CREATE_DISPATCH: dict[type, tuple[str, type, str]] = {
    CreateInputBooleanParams: ("input_boolean", InputBooleanRecord, "input_boolean_id"),
    CreateCounterParams: ("counter", CounterRecord, "counter_id"),
    # ... 8 entries
}

# Maps Update*Params type → same tuple
UPDATE_DISPATCH: dict[type, tuple[str, type, str]] = { ... }

# Maps domain string → Record type (for list)
DOMAIN_DISPATCH: dict[str, type] = {
    "input_boolean": InputBooleanRecord,
    # ... 8 entries
}

# Maps domain string → WS id key name (for update/delete)
# Uniform pattern: "{domain}_id" (e.g. "input_boolean_id", "counter_id", "timer_id")
ID_KEYS: dict[str, str] = {
    "input_boolean": "input_boolean_id",
    # ... 8 entries
}
```

**Methods with overloads:**
```python
class HelperClient(Resource):
    _api: "Api"

    def __init__(self, hassette, *, api, parent=None):
        super().__init__(hassette, parent=parent)
        self._api = api

    async def on_initialize(self):
        mark_ready(self, reason="Helper client initialized")

    # --- list: dispatches on Literal domain string ---
    @overload
    async def list(self, domain: Literal["input_boolean"]) -> list[InputBooleanRecord]: ...
    @overload
    async def list(self, domain: Literal["counter"]) -> list[CounterRecord]: ...
    # ... 8 overloads
    async def list(self, domain: HelperDomain) -> list[BaseModel]:
        record_type = DOMAIN_DISPATCH[domain]
        val = await _ws_helper_call(self._api, domain, "list")
        items = _expect_list(val, f"{domain}/list")
        return [record_type.model_validate(item) for item in items]

    # --- create: dispatches on type(params) ---
    @overload
    async def create(self, params: CreateInputBooleanParams) -> InputBooleanRecord: ...
    @overload
    async def create(self, params: CreateCounterParams) -> CounterRecord: ...
    # ... 8 overloads
    async def create(self, params: BaseModel) -> BaseModel:
        domain, record_type, _id_key = CREATE_DISPATCH[type(params)]
        val = await _ws_helper_call(self._api, domain, "create", **params.model_dump(exclude_unset=True))
        record = record_type.model_validate(_expect_dict(val, f"{domain}/create"))
        self._api.logger.info("Created %s helper %r", domain, record.id)
        return record

    # --- update: dispatches on type(params) ---
    @overload
    async def update(self, helper_id: str, params: UpdateInputBooleanParams) -> InputBooleanRecord: ...
    # ... 8 overloads
    async def update(self, helper_id: str, params: BaseModel) -> BaseModel:
        domain, record_type, id_key = UPDATE_DISPATCH[type(params)]
        val = await _ws_helper_call(self._api, domain, "update", **{id_key: helper_id}, **params.model_dump(exclude_unset=True))
        record = record_type.model_validate(_expect_dict(val, f"{domain}/update"))
        self._api.logger.debug("Updated %s helper %r", domain, helper_id)
        return record

    # --- delete: dispatches on Literal domain string ---
    @overload
    async def delete(self, domain: Literal["input_boolean"], helper_id: str) -> None: ...
    # ... 8 overloads (return type doesn't vary, but overloads validate domain at type-check time)
    async def delete(self, domain: HelperDomain, helper_id: str) -> None:
        id_key = ID_KEYS[domain]  # e.g. "input_boolean_id", "counter_id"
        await _ws_helper_call(self._api, domain, "delete", **{id_key: helper_id})
        self._api.logger.debug("Deleted %s helper %r", domain, helper_id)

    # --- counter shortcuts ---
    async def increment(self, entity_id: str) -> None: ...
    async def decrement(self, entity_id: str) -> None: ...
    async def reset(self, entity_id: str) -> None: ...
```

### Changes to `src/hassette/api/api.py`

- Remove all 35 helper methods (lines 989-1477)
- Add `HelperClient` import and wiring in `__init__`:
  ```python
  from hassette.api.helpers import HelperClient
  # in __init__:
  self.helpers = self.add_child(HelperClient, api=self)
  ```
- `_ws_helper_call`, `_expect_list`, `_expect_dict` stay in `api.py` — they're used by `HelperClient` via import

### Codegen changes

Add `generate_sync_helpers(helpers_path: Path)` to `generic.py`, following the existing pattern:
- New `HELPERS_HEADER` and `HELPERS_CLASS_HEADER` string constants for `HelperClientSyncFacade`
- `HelperClientSyncFacade` wraps `HelperClient` methods via `self._helpers` attribute
- Update `cli.py` to include `helpers` as a generation target
- Update `ApiSyncFacade` (in the `CLASS_HEADER`) to wire `self.helpers = self.add_child(HelperClientSyncFacade, helpers=self._api.helpers)` in `__init__`, using `add_child` for lifecycle registration

The `recording.py` generator needs a parallel change: `generate_sync_recording_helpers` produces `RecordingHelperClientSyncFacade` from `RecordingHelperClient`.

### Recording API changes

`RecordingHelperClient` in `src/hassette/test_utils/recording_api.py`:
- Owns `helper_definitions` (moved from `RecordingApi`)
- Implements the same 7 methods as `HelperClient` (list, create, update, delete, increment, decrement, reset)
- Reuses the existing `_list_helper`, `_create_helper`, `_update_helper`, `_delete_helper` generic methods and `RECORD_TYPE_TO_DOMAIN` dispatch table (already generic today)
- `RecordingApi.helpers` returns this object
- Remove the 35 flat helper method stubs from the `RecordingApi` protocol and implementation

## Implementation Preferences

No specific implementation preferences — follow codebase conventions.

## Replacement Targets

| Old code | Replaced by | Action |
|---|---|---|
| 32 flat CRUD methods on `Api` (api.py:989-1427) | `HelperClient.list/create/update/delete` | Remove outright |
| 3 counter shortcuts on `Api` (api.py:1437-1477) | `HelperClient.increment/decrement/reset` | Remove outright |
| 35 flat methods on `ApiSyncFacade` (sync.py, generated) | `HelperClientSyncFacade` in `sync_helpers.py` (generated) | Regenerate |
| 35 flat protocol stubs on `ApiProtocol` (recording_api.py:244-294) | `helpers` attribute on protocol | Rewrite |
| 35 flat methods on `RecordingApi` impl (recording_api.py:752-915) | `RecordingHelperClient` class | Rewrite |
| 35 flat methods on `RecordingSyncFacade` (test_utils/sync_facade.py, generated) | `RecordingHelperClientSyncFacade` | Regenerate |
| `DOCUMENTED_EXCLUSIONS[Api]` entries for 35 methods (test_forgotten_await_completeness.py) | Updated exclusion list (no helper methods) | Update |
| `KNOWN_READ_METHODS` entries for 8 `list_*` methods (test_recording_api_write_parity.py) | Updated to reflect `HelperClient` shape | Update |

## Convention Examples

### Sync facade wiring (Resource child pattern)

**Source:** `src/hassette/api/api.py:281`

```python
self.sync = self.add_child(ApiSyncFacade, api=self)
```

`HelperClient` follows this same pattern: `self.helpers = self.add_child(HelperClient, api=self)`.

### Generic helper dispatch in RecordingApi

**Source:** `src/hassette/test_utils/recording_api.py:76-88`

```python
RECORD_TYPE_TO_DOMAIN: dict[type, tuple[str, bool]] = {
    InputBooleanRecord: ("input_boolean", False),
    InputNumberRecord: ("input_number", False),
    InputSelectRecord: ("input_select", True),  # deep_copy for mutable options list
    # ...
}
```

The `HelperClient` dispatch registries (`CREATE_DISPATCH`, `UPDATE_DISPATCH`, `DOMAIN_DISPATCH`) follow this same pattern — a type-keyed dict mapping to domain metadata.

### Facade generator entry point

**Source:** `codegen/src/hassette_codegen/sync_facade/generic.py:290-292`

```python
def generate_sync(api_path: Path) -> str:
    """Generate the ApiSyncFacade source from api.py."""
    return _generate_facade(api_path, "Api", header=HEADER, class_header=CLASS_HEADER, wrapped_attr="_api")
```

`generate_sync_helpers` follows this exact pattern, pointing at `helpers.py` and `HelperClient`.

## Alternatives Considered

**Option A: 8 per-domain facade classes** (`api.helpers.input_boolean.create()`). Rejected — 8 new classes is more code, more codegen complexity, and more verbose call sites than a single generic class with overloads. See research brief for full comparison.

**Option B: Single generic method with string domain + kwargs** (`api.helpers.create("input_boolean", name="foo")`). Rejected — loses type safety on inputs. The params models validate field sets and have domain-specific validators (`input_datetime`'s `has_date or has_time`).

**Option C: Generic with typed model dispatch but no overloads** (`api.helpers.create(CreateInputBooleanParams(...))`  returning `BaseModel`). Rejected — typed input via params model, but return type is generic `BaseModel` without overloads. Users would need to cast the result or lose IDE assistance on the returned record. The chosen approach (Option E) adds overloads to narrow return types, giving full type safety on both sides.

**Option D: File split without API change** (mixin or submodule, same 35 methods on `Api`). Rejected — does not achieve the stated goal of reducing public API surface. Only fixes the file-size violation.

## Test Strategy

### Existing Tests to Adapt

| File | What changes |
|---|---|
| `tests/integration/test_api_helpers.py` (~44 tests) | All call sites change from `api.create_input_boolean(params)` to `api.helpers.create(params)`, `api.list_input_booleans()` to `api.helpers.list("input_boolean")`, etc. |
| `tests/unit/test_recording_api_helpers.py` (~21 tests) | Same call site migration for RecordingApi |
| `tests/unit/test_recording_sync_facade.py` (~23 tests) | Call sites via sync facade change; regenerated facade may change method signatures |
| `tests/unit/test_api_helper_models.py` (~9 classes) | No changes — tests Pydantic models directly, not Api methods |
| `tests/unit/test_forgotten_await_completeness.py` | Remove 35 entries from `DOCUMENTED_EXCLUSIONS[Api]`; add `HelperClient` entry if needed |
| `tests/unit/test_recording_api_write_parity.py` | Update `KNOWN_READ_METHODS` and parity checks for new shape |

### New Test Coverage

- **Unit tests for `HelperClient`**: verify dispatch registries map correctly, overloads resolve expected types, unknown domain/params raise appropriate errors. (FR#2-FR#6)
- **Unit tests for `RecordingHelperClient`**: verify recording behavior (call capture, in-memory CRUD) matches `RecordingApi`'s current behavior. (FR#8)
- **Integration test confirming `api.helpers` wiring**: `HelperClient` is a `Resource` child of `Api`, initializes and marks ready. (FR#1)

### Tests to Remove

No tests are removed — all existing tests are adapted, not deleted. The behaviors being tested (CRUD operations, recording, sync facade parity) are preserved.

## Documentation Updates

| Artifact | Change |
|---|---|
| `docs/pages/core-concepts/api/managing-helpers.md` | Rewrite call sites, update method reference table, update import examples |
| `docs/pages/core-concepts/api/snippets/managing-helpers/crud_operations.py` | Update all call sites |
| `docs/pages/core-concepts/api/snippets/managing-helpers/create_helper.py` | Update call site |
| `docs/pages/core-concepts/api/snippets/managing-helpers/counter_shortcuts.py` | Update call site (`api.helpers.increment(...)`) |
| `docs/pages/core-concepts/api/snippets/managing-helpers/testing_harness.py` | Update to use new recording API shape |
| `docs/pages/recipes/vacation-mode-toggle.md` | Update `self.api.create_input_boolean` reference |
| `docs/pages/core-concepts/api/index.md` | Update any references to flat helper methods |
| CLAUDE.md Architecture section | Update `Api` description to mention `helpers` property |

## Impact

### Changed Files

**Shared / cross-cutting (higher risk):**
- modify `src/hassette/api/api.py` — remove 35 methods, add `helpers` property + `HelperClient` import + `add_child` wiring
- create `src/hassette/api/helpers.py` — `HelperClient(Resource)` with 7 methods, overloads, and dispatch registries
- modify `codegen/src/hassette_codegen/sync_facade/generic.py` — add `HELPERS_HEADER`, `HELPERS_CLASS_HEADER`, `generate_sync_helpers()`
- modify `codegen/src/hassette_codegen/sync_facade/cli.py` — add `helpers` generation target
- modify `codegen/src/hassette_codegen/sync_facade/recording.py` — add `generate_sync_recording_helpers()`
- create `src/hassette/api/sync_helpers.py` — generated `HelperClientSyncFacade` (one file per facade, matching `api/sync.py`, `bus/sync.py`, `scheduler/sync.py` convention)
- modify `src/hassette/api/sync.py` — regenerated (helper methods removed; `ApiSyncFacade` wires `self.helpers` to `HelperClientSyncFacade`)
- modify `src/hassette/test_utils/recording_api.py` — extract `RecordingHelperClient`, update protocol, remove 35 flat methods
- modify `src/hassette/test_utils/sync_facade.py` — regenerated

**Tests:**
- modify `tests/integration/test_api_helpers.py` — update call sites
- modify `tests/unit/test_recording_api_helpers.py` — update call sites
- modify `tests/unit/test_recording_sync_facade.py` — update call sites
- modify `tests/unit/test_forgotten_await_completeness.py` — update exclusion list
- modify `tests/unit/test_recording_api_write_parity.py` — update parity checks

**Documentation:**
- modify `docs/pages/core-concepts/api/managing-helpers.md`
- modify `docs/pages/core-concepts/api/snippets/managing-helpers/crud_operations.py`
- modify `docs/pages/core-concepts/api/snippets/managing-helpers/create_helper.py`
- modify `docs/pages/core-concepts/api/snippets/managing-helpers/counter_shortcuts.py`
- modify `docs/pages/core-concepts/api/snippets/managing-helpers/testing_harness.py`
- modify `docs/pages/recipes/vacation-mode-toggle.md`
- modify `CLAUDE.md`
- modify `src/hassette/exceptions.py` — docstring example uses old flat API
- modify `src/hassette/models/states/counter.py` — docstring cross-references old flat method names

<!-- Gap check 2026-07-16: 2 gaps included — exceptions.py:101 docstring → T05 Focus item 9, counter.py:26 docstring → T05 Focus item 10 -->

### Behavioral Invariants

- All helper CRUD operations must produce identical HA WebSocket commands as before — the wire protocol does not change
- `RecordingApi` test recording behavior (call capture, seeding, in-memory CRUD) must be functionally identical
- Counter shortcuts must continue to surface HA errors via `return_response=True`
- `input_datetime` validation (`has_date or has_time`) must continue to fire on `CreateInputDatetimeParams`
- `input_select` deep-copy behavior in `RecordingApi` must be preserved (mutable `options` list)

### Blast Radius

- **User apps**: Breaking change — any app using `self.api.create_input_boolean(...)` etc. must update to `self.api.helpers.create(...)`. No apps exist in the `examples/` directory that use these methods.
- **Sync facade users**: `AppSync` apps using the sync facade for helper CRUD must update call sites identically.
- **Test infrastructure**: `HassetteHarness` and `create_hassette_stub()` consumers that mock or record helper calls will need updates.

## Open Questions

None — all questions resolved during blind spot assessment.
