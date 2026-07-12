---
task_id: "T01"
title: "Add domain prefix to entity type aliases via codegen"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "AC#1"]
---

## Summary
Fix the codegen pipeline to produce domain-prefixed entity type aliases instead of terse bare names. Modify `_make_alias_name` to accept a `domain_title` parameter and prepend it to the PascalCased parameter name. Then regenerate the 7 affected entity domains. This eliminates collision-prone names like `Format`, `Status`, and `Type` in favor of `CameraFormat`, `TodoStatus`, and `WeatherType`.

## Target Files
- modify: `codegen/src/hassette_codegen/generators/entities.py`
- modify: `codegen/tests/test_entity_generator.py`
- modify: `src/hassette/models/entities/camera.py` (via codegen regeneration)
- modify: `src/hassette/models/entities/fan.py` (via codegen regeneration)
- modify: `src/hassette/models/entities/light.py` (via codegen regeneration)
- modify: `src/hassette/models/entities/media_player.py` (via codegen regeneration)
- modify: `src/hassette/models/entities/remote.py` (via codegen regeneration)
- modify: `src/hassette/models/entities/todo.py` (via codegen regeneration)
- modify: `src/hassette/models/entities/weather.py` (via codegen regeneration)
- modify: `src/hassette/models/entities/__init__.py` (via codegen regeneration)
- read: `design/specs/008-standardize-naming-v1/design.md`
- read: `design/specs/008-standardize-naming-v1/tasks/context.md`

## Prompt
Modify the entity codegen to produce domain-prefixed type aliases.

**Step 1: Fix `_make_alias_name` in `codegen/src/hassette_codegen/generators/entities.py`**

Change the function signature to accept `domain_title`:

```python
def _make_alias_name(param_name: str, domain_title: str) -> str:
    base = param_name.replace("_", " ").title().replace(" ", "")
    return f"{domain_title}{base}"
```

Move `domain_title = domain_to_title(domain.name)` from line 119 to before the service loop (before `services_for_template` initialization around line 56). Remove the now-duplicate assignment on line 119. Thread `domain_title` to the `_make_alias_name` call on line 83.

**Step 2: Update codegen tests**

Read `codegen/tests/test_entity_generator.py` and update any assertions that check for old alias names (e.g., `Status`) to expect the new domain-prefixed names (e.g., `TodoStatus`).

**Step 3: Regenerate entity files**

Set up the codegen venv and run:
```bash
cd codegen && uv sync
uv run hassette-codegen generate --ha-core-path ~/source/core --domain camera,fan,light,media_player,remote,todo,weather
```

Verify that the generated files contain exactly these renamed aliases:
- `Format` → `CameraFormat`
- `Direction` → `FanDirection`
- `Flash` → `LightFlash`
- `Enqueue` → `MediaPlayerEnqueue`
- `Repeat` → `MediaPlayerRepeat`
- `CommandType` → `RemoteCommandType`
- `Status` → `TodoStatus`
- `Type` → `WeatherType`

**Step 4: Run codegen tests**
```bash
cd codegen && uv run pytest
```

## Focus
- The `domain_title` variable is currently computed on line 119 (after the service loop) but needs to be available inside the loop on line 83. Move it earlier — don't create a second computation.
- The codegen test suite in `codegen/tests/` has its own venv and test runner. Run `cd codegen && uv sync` first, then `uv run pytest`.
- The entity files under `src/hassette/models/entities/` are generated — don't manually edit them. Only the codegen source and test files are hand-edited.
- `__init__.py` imports and `__all__` entries are also codegen-managed and will update automatically.

## Verify
- [ ] FR#1: Generated entity files contain `CameraFormat`, `FanDirection`, `LightFlash`, `MediaPlayerEnqueue`, `MediaPlayerRepeat`, `RemoteCommandType`, `TodoStatus`, `WeatherType` — no bare `Format`, `Direction`, `Flash`, `Enqueue`, `Repeat`, `CommandType`, `Status`, or `Type` aliases remain
- [ ] FR#2: `_make_alias_name` accepts `(param_name, domain_title)` and prepends the domain title
- [ ] AC#1: Running `hassette-codegen generate --domain camera,fan,light,media_player,remote,todo,weather` produces entity files with domain-prefixed aliases and no other changes; codegen test suite passes
