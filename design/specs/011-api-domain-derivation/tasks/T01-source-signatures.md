---
task_id: "T01"
title: "Update Api convenience method signatures"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#6", "AC#1", "AC#2", "AC#3", "AC#4", "AC#5", "AC#6", "AC#7", "AC#8", "AC#10"]
---

## Summary

Change `turn_on`, `turn_off`, and `toggle` (renamed from `toggle_service`) across all four parallel implementations (Api, ApiSyncFacade, RecordingApi, RecordingApiSyncFacade). The `domain` parameter default changes from `"homeassistant"` to `None` with automatic derivation from entity_id. `turn_off` and `toggle` gain `**data: Any` for parity with `turn_on`. The module docstring in `api.py` also references `toggle_service` and must be updated. Note: `BaseEntity`/`BaseEntitySyncFacade` methods were already removed by a cherry-picked commit (#1320) — no entity model changes needed.

## Target Files

- modify: `src/hassette/api/api.py`
- modify: `src/hassette/test_utils/recording_api.py`
- regenerate: `src/hassette/api/sync.py` (codegen-generated from api.py)
- regenerate: `src/hassette/test_utils/sync_facade.py` (codegen-generated from recording_api.py)
- read: `src/hassette/models/entities/base.py` (verify BaseEntity methods removed by #1320)
- read: `src/hassette/events/hass/hass.py` (domain derivation pattern reference)

## Prompt

Update `api.py` and `recording_api.py` to implement domain derivation, rename `toggle_service` → `toggle`, and add `**data` to `turn_off`/`toggle`. Then regenerate the codegen-generated sync facades.

### 1. `src/hassette/api/api.py`

Change the three convenience methods (currently at lines 555-609):

**`turn_on`** (line 555): Change `domain: str = "homeassistant"` to `domain: str | None = None`. Add domain derivation logic:
```python
def turn_on(self, entity_id: str | StrEnum, domain: str | None = None, **data: Any) -> "Coroutine[Any, Any, None]":
    entity_id = str(entity_id)
    if domain is None:
        domain = entity_id.split(".", 1)[0]
    return self.call_service(domain=domain, service="turn_on", target={"entity_id": entity_id}, **data)
```

**`turn_off`** (line 575): Same `domain` change. Add `**data: Any`. Forward `**data` to `call_service`.

**`toggle_service`** (line 593): Rename to `toggle`. Same `domain` change. Add `**data: Any`. Forward `**data` to `call_service`.

Update docstrings on all three methods — remove the deprecation note about `homeassistant.turn_on` since the default is now correct. Describe the new behavior: "Defaults to the entity's domain (derived from entity_id). Pass explicitly to override."

Update the module docstring (line 8) that references `toggle_service` to say `toggle`.

Update the class-level example (line 54) that shows `toggle_service` to say `toggle`.

Keep the Shape B delegate comment on each method.

### 2. `src/hassette/api/sync.py` (codegen-generated — do NOT hand-edit)

This file is auto-generated from `api.py` by `codegen/src/hassette_codegen/sync_facade/`. Do not edit it directly. It will be regenerated in step 6 below.

### 3. `src/hassette/test_utils/recording_api.py`

Update the protocol stub (around line 158-161):
```python
async def turn_on(self, entity_id: str | StrEnum, domain: str | None = ..., **data) -> None: ...
async def turn_off(self, entity_id: str | StrEnum, domain: str | None = ..., **data) -> None: ...
async def toggle(self, entity_id: str | StrEnum, domain: str | None = ..., **data) -> None: ...
```

Update `RecordingApi.turn_on` (line 415): Change `domain: str = "homeassistant"` to `domain: str | None = None`. Add domain derivation before recording: `if domain is None: domain = entity_id.split(".", 1)[0]`. This ensures the recorded kwargs reflect the derived domain.

Update `RecordingApi.turn_off` (line 426): Same domain change. Add `**data: Any`. Capture `**data` in kwargs: `kwargs={"entity_id": entity_id, "domain": domain, **data}`. Add domain derivation.

Rename `RecordingApi.toggle_service` (line 437) to `toggle`. Same domain change. Add `**data: Any`. Capture in kwargs. Update recorded method name from `"toggle_service"` to `"toggle"`. Add domain derivation.

### 4. `src/hassette/test_utils/sync_facade.py` (codegen-generated — do NOT hand-edit)

This file is auto-generated from `recording_api.py` by `codegen/src/hassette_codegen/sync_facade/`. Do not edit it directly. It will be regenerated in step 6 below.

### 5. `src/hassette/models/entities/base.py` (read-only verification)

Verify that `BaseEntity` and `BaseEntitySyncFacade` no longer have `turn_on`, `turn_off`, or `toggle` methods. These were removed by the cherry-picked #1320 commit. No changes needed in this task.

### 6. Regenerate sync facades

After editing `api.py` and `recording_api.py`, regenerate both sync facades:

```bash
uv run python codegen/src/hassette_codegen/sync_facade/ --target all
```

This regenerates `src/hassette/api/sync.py` and `src/hassette/test_utils/sync_facade.py` from their source files. Verify the regenerated files contain the new `toggle` method (not `toggle_service`), `domain: str | None = None` defaults, and `**data: Any` on `turn_off`/`toggle`.

### Verification

After all changes and regeneration, run `prek -a` to verify lint + type check passes. Run `uv run pytest tests/pyright_probes/forgotten_await_probe.py -v` to verify the Pyright probe still works with the new `domain: str | None` type.

## Focus

- Only edit `api.py` and `recording_api.py` directly. `sync.py` and `sync_facade.py` are codegen-generated — regenerate them after editing the source files. Do NOT hand-edit them.
- Domain derivation in `RecordingApi` should happen before recording so the recorded kwargs show the derived domain, not `None`. This matches how the real Api resolves the domain before calling `call_service`.
- `api.py` module docstring (line 8) and class-level example (line 54) both reference `toggle_service` — update both.
- The `recording_api.py` comment at line 413 says "Signatures must exactly match hassette.api.Api" — this continues to apply after the change.
- Generated entity models (fan, humidifier, switch, light, etc.) call `api.call_service(domain=self.domain, ...)` directly — they are NOT affected and should NOT be modified.
- `BaseEntity`/`BaseEntitySyncFacade` `turn_on`/`turn_off`/`toggle` methods were already removed by the cherry-picked #1320 commit. Do not re-add them.

## Verify

- [ ] FR#1: `Api.turn_on("light.kitchen")` with no `domain` arg calls `call_service` with `domain="light"`
- [ ] FR#2: `Api.turn_on("light.kitchen", domain="homeassistant")` calls `call_service` with `domain="homeassistant"`
- [ ] FR#3: `Api.toggle` method exists; `Api.toggle_service` does not exist (verified via `hasattr`)
- [ ] FR#4: `Api.turn_off("switch.fan", transition=2)` forwards `transition=2` to `call_service`
- [ ] FR#4: `Api.toggle("light.kitchen", transition=1)` forwards `transition=1` to `call_service`
- [ ] FR#5: `RecordingApi.toggle("light.x")` records method name `"toggle"` and derived domain `"light"` in kwargs
- [ ] FR#5: `RecordingApi.turn_off("light.x", brightness=0)` captures `brightness=0` in kwargs
- [ ] FR#6: `BaseEntity` has no `turn_on`, `turn_off`, or `toggle` methods (verified by reading `base.py`)
- [ ] AC#1: `Api.turn_on("light.kitchen")` dispatches to domain `"light"`
- [ ] AC#2: `Api.turn_on("light.kitchen", domain="homeassistant")` dispatches to domain `"homeassistant"`
- [ ] AC#3: `Api.toggle` exists; `Api.toggle_service` does not
- [ ] AC#4: `Api.turn_off("switch.fan", transition=2)` forwards `transition=2`
- [ ] AC#5: `Api.toggle("light.kitchen", transition=1)` forwards `transition=1`
- [ ] AC#6: `RecordingApi.toggle("light.x")` records under `"toggle"`
- [ ] AC#7: `RecordingApi.turn_off("light.x", brightness=0)` captures `brightness=0`
- [ ] AC#8: `BaseEntity` has no `turn_on`, `turn_off`, or `toggle` methods
- [ ] AC#10: `prek -a` passes cleanly
