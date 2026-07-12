# Design: Standardize naming across entities, events, ResourceRole, and API

**Date:** 2026-07-12
**Status:** archived
**Scope-mode:** hold

## Problem

Four naming inconsistencies in the public API would become permanent technical debt after the v1.0 freeze. Entity type aliases use terse, collision-prone names (`Format`, `Status`, `Type`) that shadow builtins. Event factory classmethods use three different naming patterns for the same job. `ResourceRole` is the only `StrEnum` with Title-case values. `Api.get_state_value_typed` returns `Any` and cannot deliver the typing its name promises.

## Goals

- Eliminate collision-prone entity type aliases by domain-prefixing them via codegen.
- Standardize event factory classmethods on a descriptive `from_*` naming family.
- Normalize `ResourceRole` values to lowercase, matching every other `StrEnum` in `enums.py`.
- Remove `get_state_value_typed` and redirect users to `get_state().value` or `get_state_value()`.

## Functional Requirements

- **FR#1** Entity type aliases in `src/hassette/models/entities/` use domain-prefixed names: `CameraFormat`, `FanDirection`, `LightFlash`, `MediaPlayerEnqueue`, `MediaPlayerRepeat`, `RemoteCommandType`, `TodoStatus`, `WeatherType`.
- **FR#2** The codegen function `_make_alias_name` in `codegen/src/hassette_codegen/generators/entities.py` prepends the domain title to the PascalCased parameter name, so future codegen runs produce domain-prefixed aliases automatically.
- **FR#3** `HassetteServiceEvent.from_data()` is renamed to `from_service_status()`.
- **FR#4** `HassetteAppStateEvent.from_data()` is renamed to `from_app()`.
- **FR#5** `HassetteSimpleEvent.create_event()` is renamed to `from_topic()`.
- **FR#6** `HassetteFileWatcherEvent.create_event()` is renamed to `from_paths()`.
- **FR#7** `HassetteExecutionCompletedEvent.from_record()` retains its current name (already descriptive).
- **FR#8** `ResourceRole` enum values use lowercase strings via `auto()` instead of explicit Title-case strings.
- **FR#9** `Api.get_state_value_typed` and its sync/test-utils mirrors are removed.
- **FR#10** Documentation for `get_state_value_typed` is removed and replaced with guidance to use `get_state().value` (typed model) or `get_state_value()` (raw string).

## Edge Cases

- **Repeat/RepeatMode coexistence**: `MediaPlayerRepeat` (entity `Literal`) and `RepeatMode` (state `StrEnum`) define identical values but come from different HA source data via different codegen generators. They coexist as separate types — no cross-generator wiring needed.
- **Frontend test fixtures**: `diagnostics.test.tsx` already uses lowercase role values (`"core"`, `"storage"`) that don't match the current Title-case enum. Normalizing ResourceRole to lowercase aligns the enum with what the tests already expect, but `"storage"` is not a valid `ResourceRole` value — those fixtures need correction regardless.
- **Codegen test suite**: The codegen package has its own test suite (`codegen/tests/test_entity_generator.py`) that may assert on the old alias names.

## Acceptance Criteria

- **AC#1** (FR#1, FR#2) Running `hassette-codegen generate --domain camera,fan,light,media_player,remote,todo,weather` produces entity files with domain-prefixed aliases and no other changes. The codegen test suite passes.
- **AC#2** (FR#3–FR#7) All five event factory classmethods use their new names. `grep -rn '\.create_event(\|\.from_data(' src/hassette/events/ src/hassette/resources/ src/hassette/core/ src/hassette/test_utils/ tests/` returns no matches.
- **AC#3** (FR#8) `ResourceRole` values are lowercase. `grep -n '"Core"\|"Service"\|"App"\|"Base"\|"Resource"\|"Unknown"' src/hassette/types/enums.py` returns no matches. Frontend types are regenerated. Frontend test fixtures use valid lowercase values.
- **AC#4** (FR#9, FR#10) `grep -rn 'get_state_value_typed' src/ tests/ docs/` returns no matches. The docs "Which method to use" table no longer lists it. The snippet file is deleted.
- **AC#5** `uv run nox -s dev` passes. `prek -a` (ruff + pyright + all pre-commit hooks) is clean.
- **AC#6** PR uses `refactor!:` prefix with `BREAKING CHANGE:` footer covering all four changes.

## Key Constraints

- Entity alias renames must go through codegen, not manual edits — manual edits would be overwritten on the next codegen run.
- `from_record` on `HassetteExecutionCompletedEvent` is explicitly excluded from renaming (already descriptive, 11 test call sites).

## Dependencies and Assumptions

- Local HA core checkout at `~/source/core` for codegen (already available per memory).
- Codegen venv setup in the worktree (`cd codegen && uv sync`).

## Architecture

### 1. Entity alias codegen fix

Modify `_make_alias_name` in `codegen/src/hassette_codegen/generators/entities.py`:

```python
# Before
def _make_alias_name(param_name: str) -> str:
    return param_name.replace("_", " ").title().replace(" ", "")

# After
def _make_alias_name(param_name: str, domain_title: str) -> str:
    base = param_name.replace("_", " ").title().replace(" ", "")
    return f"{domain_title}{base}"
```

Move `domain_title = domain_to_title(domain.name)` before the service loop (currently on line 119, needed on line 83). Thread `domain_title` to the `_make_alias_name` call on line 83. Then run codegen for the 7 affected domains: `hassette-codegen generate --ha-core-path ~/source/core --domain camera,fan,light,media_player,remote,todo,weather`.

### 2. Event factory renames

Direct method renames in `src/hassette/events/hassette.py`:

| Class | Old method | New method |
|---|---|---|
| `HassetteServiceEvent` | `from_data` | `from_service_status` |
| `HassetteAppStateEvent` | `from_data` | `from_app` |
| `HassetteSimpleEvent` | `create_event` | `from_topic` |
| `HassetteFileWatcherEvent` | `create_event` | `from_paths` |

Update all call sites (16 in src/, 11 in tests/).

### 3. ResourceRole lowercase

Change `ResourceRole` in `src/hassette/types/enums.py` from explicit Title-case strings to `auto()`:

```python
# Before
class ResourceRole(StrEnum):
    CORE = "Core"
    BASE = "Base"
    SERVICE = "Service"
    RESOURCE = "Resource"
    APP = "App"
    UNKNOWN = "Unknown"

# After
class ResourceRole(StrEnum):
    CORE = auto()
    BASE = auto()
    SERVICE = auto()
    RESOURCE = auto()
    APP = auto()
    UNKNOWN = auto()
```

No downstream code changes needed in `runtime_query_service.py` or `web/models.py` — they already use `.value` which will now return lowercase. Regenerate OpenAPI schema and frontend types. Fix frontend test fixtures that use invalid role values.

### 4. Remove get_state_value_typed

Delete the method from `src/hassette/api/api.py`, its sync mirror from `src/hassette/api/sync.py`, and its stubs from `src/hassette/test_utils/recording_api.py` and `src/hassette/test_utils/sync_facade.py`. Update tests and docs.

## Implementation Preferences

No specific implementation preferences — follow codebase conventions.

## Replacement Targets

| Target | Replaced by | Action |
|---|---|---|
| `_make_alias_name(param_name)` signature | `_make_alias_name(param_name, domain_title)` | Modify in place |
| `Format`, `Direction`, `Flash`, `Enqueue`, `Repeat`, `CommandType`, `Status`, `Type` aliases | Domain-prefixed names via codegen | Regenerate (old names disappear) |
| `HassetteServiceEvent.from_data()` | `from_service_status()` | Rename |
| `HassetteAppStateEvent.from_data()` | `from_app()` | Rename |
| `HassetteSimpleEvent.create_event()` | `from_topic()` | Rename |
| `HassetteFileWatcherEvent.create_event()` | `from_paths()` | Rename |
| `ResourceRole` explicit Title-case values | `auto()` for lowercase | Modify in place |
| `Api.get_state_value_typed` + mirrors | `get_state().value` or `get_state_value()` | Remove entirely |

## Convention Examples

### StrEnum with auto() for lowercase values

**Source:** `src/hassette/types/enums.py` (RestartType, ExecutionMode, etc.)

```python
class RestartType(StrEnum):
    PERMANENT = auto()
    TRANSIENT = auto()
    TEMPORARY = auto()
```

### Domain-prefixed naming in states module

**Source:** `src/hassette/models/states/media_player.py`

```python
class MediaPlayerStateValue(StrEnum):
    BUFFERING = "buffering"
    IDLE = "idle"
    OFF = "off"
    ON = "on"
    PAUSED = "paused"
    PLAYING = "playing"
    STANDBY = "standby"

class RepeatMode(StrEnum):
    ALL = "all"
    OFF = "off"
    ONE = "one"
```

Note: the states module uses domain prefixes for most types (`MediaPlayerStateValue`, `MediaPlayerEntityFeature`) but some like `RepeatMode` and `ColorMode` use shorter names. The entity module currently has no domain prefixes at all — the codegen fix introduces them.

### Codegen alias generation

**Source:** `codegen/src/hassette_codegen/generators/entities.py:130`

```python
def _make_alias_name(param_name: str) -> str:
    """Convert a param name to a PascalCase type alias name."""
    return param_name.replace("_", " ").title().replace(" ", "")
```

DO: Prepend domain title to distinguish aliases across domains.
DON'T: Leave bare PascalCased parameter names that collide with builtins (`Format`, `Status`, `Type`).

## Alternatives Considered

**Manual entity renames without codegen change**: Rejected — manual edits to generated files would be overwritten on the next codegen run. The codegen fix is a one-line change and makes all future regenerations correct.

**Keep `from_data` names unchanged**: Rejected — with two classes sharing the same `from_data` name and taking different parameter shapes, the name provides no signal about what data each method expects. Descriptive `from_*` names make the call sites self-documenting.

**Deprecation period for `get_state_value_typed`**: Rejected — this is a pre-v1.0 cleanup. Adding deprecation warnings for a method that was never in a stable release adds complexity without value. Clean removal before the freeze is appropriate.

## Test Strategy

### Existing Tests to Adapt

**Event factory renames (5 test files):**
- `tests/unit/events/test_hassette_payload.py` — uses `HassetteSimpleEvent.create_event()` and `HassetteFileWatcherEvent.create_event()`
- `tests/unit/events/test_service_status_payload.py` — uses `HassetteServiceEvent.from_data()`
- `tests/unit/core/test_runtime_query_service.py` — uses `HassetteServiceEvent.from_data()` and `HassetteExecutionCompletedEvent.from_record()`
- `tests/unit/bus/test_bus_registration_edge_cases.py` — uses `HassetteAppStateEvent.from_data()`
- `tests/unit/test_app_key.py` — uses `HassetteAppStateEvent.from_data()`

**ResourceRole (1 test file):**
- `frontend/src/pages/diagnostics.test.tsx` — fixture values need to use valid lowercase `ResourceRole` values

**get_state_value_typed removal (4 test files):**
- `tests/unit/test_recording_sync_facade.py` — remove test of `get_state_value_typed` NotImplementedError
- `tests/unit/test_forgotten_await_completeness.py` — remove from completeness list
- `tests/unit/test_recording_api_write_parity.py` — remove from parity list
- `tests/unit/test_recording_api.py` — update docstring in `test_getattr_tailored_message_for_state_conversion` to remove `get_state_value_typed` mention (the test itself exercises `get_state_value`, which is not being removed)

**Codegen tests (1 file):**
- `codegen/tests/test_entity_generator.py` — may assert old alias names; update assertions

### New Test Coverage

No new test coverage needed — this is a naming refactor. Existing tests adapted for the new names cover the same behaviors.

### Tests to Remove

- Test of `get_state_value_typed` NotImplementedError in `tests/unit/test_recording_sync_facade.py`
- References to `get_state_value_typed` in completeness/parity list tests

## Documentation Updates

- **`docs/pages/core-concepts/api/methods.md`**: Remove `get_state_value_typed` from the "Which method to use" table (line 14), remove cross-reference from `get_state()` docs (line 43), remove the full method documentation section (lines 78–89). Add a note that `get_state().value` provides the typed value.
- **`docs/pages/testing/factories.md`**: Remove line 174 mention of `get_state_value_typed`.
- **`docs/pages/core-concepts/api/snippets/api_get_state_value_typed.py`**: Delete this file.
- **OpenAPI schema + frontend types**: Regenerate via `uv run python scripts/export_schemas.py --types` after ResourceRole change.

## Impact

### Changed Files

**Codegen (modify):**
- `codegen/src/hassette_codegen/generators/entities.py` — modify `_make_alias_name` signature and move `domain_title` computation earlier

**Entity models (modify via codegen regeneration):**
- `src/hassette/models/entities/camera.py` — `Format` → `CameraFormat`
- `src/hassette/models/entities/fan.py` — `Direction` → `FanDirection`
- `src/hassette/models/entities/light.py` — `Flash` → `LightFlash`
- `src/hassette/models/entities/media_player.py` — `Enqueue` → `MediaPlayerEnqueue`, `Repeat` → `MediaPlayerRepeat`
- `src/hassette/models/entities/remote.py` — `CommandType` → `RemoteCommandType`
- `src/hassette/models/entities/todo.py` — `Status` → `TodoStatus`
- `src/hassette/models/entities/weather.py` — `Type` → `WeatherType`
- `src/hassette/models/entities/__init__.py` — update imports and `__all__`

**Event factories (modify):**
- `src/hassette/events/hassette.py` — rename 4 classmethods

**Event factory call sites (modify):**
- `src/hassette/resources/mixins.py` — 1 call
- `src/hassette/core/file_watcher.py` — 1 call
- `src/hassette/core/app_lifecycle_service.py` — 5 calls
- `src/hassette/core/websocket_service.py` — 2 calls
- `src/hassette/test_utils/helpers.py` — 3 calls
- `src/hassette/test_utils/simulation.py` — 4 calls

**ResourceRole (modify):**
- `src/hassette/types/enums.py` — change values to `auto()`

**API removal (modify/delete):**
- `src/hassette/api/api.py` — delete `get_state_value_typed` method
- `src/hassette/api/sync.py` — delete sync mirror
- `src/hassette/test_utils/recording_api.py` — delete protocol stub and references
- `src/hassette/test_utils/sync_facade.py` — delete NotImplementedError stub

**Frontend (modify via regeneration):**
- `frontend/src/api/generated-types.ts` — regenerated (ResourceRole values)

**Tests (modify):**
- `tests/unit/events/test_hassette_payload.py`
- `tests/unit/events/test_service_status_payload.py`
- `tests/unit/core/test_runtime_query_service.py`
- `tests/unit/bus/test_bus_registration_edge_cases.py`
- `tests/unit/test_app_key.py`
- `tests/unit/test_recording_sync_facade.py`
- `tests/unit/test_forgotten_await_completeness.py`
- `tests/unit/test_recording_api_write_parity.py`
- `tests/unit/test_recording_api.py`
- `frontend/src/pages/diagnostics.test.tsx`
- `codegen/tests/test_entity_generator.py`

**Docs (modify/delete):**
- `docs/pages/core-concepts/api/methods.md` — modify
- `docs/pages/testing/factories.md` — modify
- `docs/pages/core-concepts/api/snippets/api_get_state_value_typed.py` — delete

### Behavioral Invariants

- All entity service methods continue to accept the same parameter values — only the type alias names change, not the underlying `Literal` values.
- Event factory methods produce identical `Event` objects — only the classmethod names change.
- `ResourceRole` member names (`CORE`, `SERVICE`, etc.) are unchanged — only `.value` strings change from Title-case to lowercase.
- All existing Bus subscriptions, Scheduler jobs, and API calls continue working identically.

### Blast Radius

- **External user apps**: Any app importing entity type aliases (`Format`, `Direction`, etc.) by name will break. Any app calling `get_state_value_typed()` will break. This is intentional pre-v1.0 breakage.
- **API consumers**: Any consumer comparing `role` string values (e.g., `== "Core"`) will break after ResourceRole normalizes to lowercase.
- **Frontend**: Generated types will reflect lowercase role values. Diagnostics page role display is mapping-only today (not rendered as visible text), so no visible UI change.
- **Logs and fatal-reason text**: `service_watcher.py` interpolates `role` directly into fatal-reason strings and log messages (e.g. `f"{role} '{name}' restart budget exhausted (PERMANENT)"`). These will render with lowercase role text (`"service 'X' crashed"` instead of `"Service 'X' crashed"`). This is not a separate concern — it is the same `.value` casing change described above, and it matches the file's existing convention: `ResourceStatus`, already a lowercase `auto()` enum, flows into the same log statements (e.g. `"%s '%s' transitioned to status '%s' from '%s'"`) with no capitalization compensation. No code change is needed in `service_watcher.py`.

## Open Questions

None — all decisions resolved during discovery.
