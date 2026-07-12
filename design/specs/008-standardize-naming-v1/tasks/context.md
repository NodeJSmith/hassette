# Context: Standardize Naming Before v1.0 Freeze

## Problem & Motivation
Four naming inconsistencies in the public API would become permanent technical debt after the v1.0 freeze. Entity type aliases use terse, collision-prone names (`Format`, `Status`, `Type`) that shadow builtins and don't follow the domain-prefix convention used in the states module. Event factory classmethods use three different naming patterns (`from_data`, `create_event`, `from_record`) for the same job. `ResourceRole` is the only `StrEnum` with Title-case explicit values instead of lowercase `auto()`. `Api.get_state_value_typed` returns `Any` and cannot deliver the typing its name promises. All four are breaking changes that must land before the v1.0 API freeze locks the public surface.

## Visual Artifacts
None.

## Key Decisions
1. Entity alias renames go through codegen (modify `_make_alias_name` to prepend domain title), not manual edits — manual edits would be overwritten on the next codegen run.
2. `MediaPlayerRepeat` (entity `Literal`) and `RepeatMode` (state `StrEnum`) coexist as separate types from different codegen generators. No cross-generator wiring.
3. Event factory renames: `from_data` → `from_service_status`/`from_app`, `create_event` → `from_topic`/`from_paths`. `from_record` stays (already descriptive, 11 test call sites).
4. `ResourceRole` switches to `auto()` for lowercase values, matching every other `StrEnum` in `enums.py`.
5. `get_state_value_typed` is removed outright (no deprecation period — pre-v1.0 cleanup). Users get `get_state().value` or `get_state_value()`.

## Constraints & Anti-Patterns
- Entity alias renames MUST go through codegen. Manual edits to generated files will be overwritten.
- `from_record` on `HassetteExecutionCompletedEvent` is explicitly excluded from renaming.
- `ResourceRole` has no database persistence — this is API/frontend only, not a migration concern.
- Hassette is a framework — zero in-repo callers beyond the framework's own modules and tests does not mean zero real-world usage. All renames are breaking.

## Design Doc References
- `## Architecture` — the four implementation approaches (codegen fix, method renames, auto() switch, method removal)
- `## Replacement Targets` — what's being replaced and by what
- `## Test Strategy` — which tests to adapt, which to remove
- `## Impact → Changed Files` — complete file inventory with change verbs
- `## Edge Cases` — Repeat/RepeatMode coexistence, frontend test fixtures, codegen tests

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
