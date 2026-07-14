---
task_id: "T01"
title: "Update Api convenience method signatures and entity model"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#6", "FR#7", "AC#1", "AC#2", "AC#3", "AC#4", "AC#5", "AC#6", "AC#7", "AC#8", "AC#10"]
---

## Summary

Change `turn_on`, `turn_off`, and `toggle` (renamed from `toggle_service`) across all four parallel implementations (Api, ApiSyncFacade, RecordingApi, RecordingApiSyncFacade) and both entity model layers (BaseEntity, BaseEntitySyncFacade). The `domain` parameter default changes from `"homeassistant"` to `None` with automatic derivation from entity_id. `turn_off` and `toggle` gain `**data: Any` for parity with `turn_on`. The module docstring in `api.py` also references `toggle_service` and must be updated.

## Target Files

- modify: `src/hassette/api/api.py`
- modify: `src/hassette/api/sync.py`
- modify: `src/hassette/test_utils/recording_api.py`
- modify: `src/hassette/test_utils/sync_facade.py`
- modify: `src/hassette/models/entities/base.py`
- read: `src/hassette/events/hass/hass.py` (domain derivation pattern reference)

## Prompt

Update six files to implement domain derivation, rename `toggle_service` → `toggle`, and add `**data` to `turn_off`/`toggle`.

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

### 2. `src/hassette/api/sync.py`

Mirror the Api changes on `ApiSyncFacade` (currently at lines 226-260):

- `turn_on`: Change domain default to `None`, update docstring.
- `turn_off`: Change domain default to `None`, add `**data: Any`, forward `**data`.
- `toggle_service` → `toggle`: Rename, change domain default, add `**data: Any`.

The sync facade delegates to `self._api.<method>(entity_id, domain, **data)`. Pass `domain` through as-is (the Api layer handles derivation).

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

### 4. `src/hassette/test_utils/sync_facade.py`

Mirror recording API changes on `RecordingApiSyncFacade` (around lines 180-198):

- `turn_on`: Change domain default, add domain derivation before recording.
- `turn_off`: Change domain default, add `**data: Any`, capture in kwargs, add domain derivation.
- `toggle_service` → `toggle`: Rename, change domain default, add `**data`, update method name string to `"toggle"`, add domain derivation.

### 5. `src/hassette/models/entities/base.py`

**`BaseEntity`** (lines 84-104):
- `turn_off()`: Add `**data: Any` parameter. Forward: `return self.api.turn_off(self.entity_id, **data)`.
- `turn_on()`: Already has `**data`. No change needed.
- `toggle()`: Already named `toggle`. Change internal call from `self.api.toggle_service(self.entity_id)` to `self.api.toggle(self.entity_id)`. Add `**data: Any` parameter and forward it.

**`BaseEntitySyncFacade`** (lines 107-129):
- `turn_off()`: Add `**data: Any`. Forward: `self.entity.api.sync.turn_off(self.entity.entity_id, **data)`.
- `turn_on()`: Already has `**data`. No change needed.
- `toggle()`: Change internal call from `self.entity.api.sync.toggle_service(...)` to `self.entity.api.sync.toggle(...)`. Add `**data: Any` and forward it.

Update docstrings on modified methods to mention `**data` forwarding.

### Verification

After all changes, run `prek -a` to verify lint + type check passes. Run `uv run pytest tests/pyright_probes/forgotten_await_probe.py -v` to verify the Pyright probe still works with the new `domain: str | None` type.

## Focus

- The four implementations (Api, ApiSyncFacade, RecordingApi, RecordingApiSyncFacade) must end up with identical signatures. There is no shared protocol — manual synchronization is required.
- Domain derivation in RecordingApi/RecordingApiSyncFacade should happen before recording so the recorded kwargs show the derived domain, not `None`. This matches how the real Api resolves the domain before calling `call_service`.
- `api.py` module docstring (line 8) and class-level example (line 54) both reference `toggle_service` — update both.
- The `recording_api.py` comment at line 413 says "Signatures must exactly match hassette.api.Api" — this continues to apply after the change.
- Generated entity models (fan, humidifier, switch, light, etc.) call `api.call_service(domain=self.domain, ...)` directly — they are NOT affected and should NOT be modified.

## Verify

- [ ] FR#1: `Api.turn_on("light.kitchen")` with no `domain` arg calls `call_service` with `domain="light"`
- [ ] FR#2: `Api.turn_on("light.kitchen", domain="homeassistant")` calls `call_service` with `domain="homeassistant"`
- [ ] FR#3: `Api.toggle` method exists; `Api.toggle_service` does not exist (verified via `hasattr`)
- [ ] FR#4: `Api.turn_off("switch.fan", transition=2)` forwards `transition=2` to `call_service`
- [ ] FR#4: `Api.toggle("light.kitchen", transition=1)` forwards `transition=1` to `call_service`
- [ ] FR#5: `RecordingApi.toggle("light.x")` records method name `"toggle"` and derived domain `"light"` in kwargs
- [ ] FR#5: `RecordingApi.turn_off("light.x", brightness=0)` captures `brightness=0` in kwargs
- [ ] FR#6: `BaseEntity.turn_off(transition=2)` forwards `transition=2` to `api.turn_off`
- [ ] FR#7: `BaseEntitySyncFacade.toggle(transition=1)` forwards `transition=1` to `api.sync.toggle`
- [ ] AC#1: `Api.turn_on("light.kitchen")` dispatches to domain `"light"`
- [ ] AC#2: `Api.turn_on("light.kitchen", domain="homeassistant")` dispatches to domain `"homeassistant"`
- [ ] AC#3: `Api.toggle` exists; `Api.toggle_service` does not
- [ ] AC#4: `Api.turn_off("switch.fan", transition=2)` forwards `transition=2`
- [ ] AC#5: `Api.toggle("light.kitchen", transition=1)` forwards `transition=1`
- [ ] AC#6: `RecordingApi.toggle("light.x")` records under `"toggle"`
- [ ] AC#7: `RecordingApi.turn_off("light.x", brightness=0)` captures `brightness=0`
- [ ] AC#8: `BaseEntity.turn_off(transition=2)` forwards `transition=2`
- [ ] AC#10: `prek -a` passes cleanly
