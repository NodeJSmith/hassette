# Context: Api Domain Derivation

## Problem & Motivation

Home Assistant deprecated the generic `homeassistant.turn_on`, `homeassistant.turn_off`, and `homeassistant.toggle` services starting in 2024.x. Hassette's `Api` convenience methods (`turn_on`, `turn_off`, `toggle_service`) hardcode `domain="homeassistant"` as the default, so every caller that omits `domain=` sends a deprecated service call. App authors must pass `domain="light"` or `domain="switch"` on every call — boilerplate the framework should handle, since the entity_id already encodes the domain. Additionally, `toggle_service` is named inconsistently with `turn_on`/`turn_off` and with the entity-level method (`BaseEntity.toggle`), and `turn_off`/`toggle_service` lack the `**data` parameter that `turn_on` already supports.

## Visual Artifacts

None.

## Key Decisions

1. Change `domain` parameter default from `"homeassistant"` to `None`. When `None`, derive domain via `entity_id.split(".", 1)[0]`. When explicitly passed, use that value. This matches the existing derivation pattern in `src/hassette/events/hass/hass.py:148` and `src/hassette/conversion/state_registry.py:93`.
2. Rename `toggle_service` → `toggle` across all layers (Api, ApiSyncFacade, RecordingApi, RecordingApiSyncFacade, BaseEntity, BaseEntitySyncFacade). Pre-1.0, so no backward compat alias.
3. Add `**data: Any` to `turn_off` and `toggle` on all four implementations plus `BaseEntity` and `BaseEntitySyncFacade`, matching `turn_on`'s existing pattern.
4. Generated entity models (light, switch, fan, etc.) are unaffected — they call `api.call_service(domain=self.domain, ...)` directly and bypass these convenience methods.
5. `BaseEntity`/`BaseEntitySyncFacade` generic `turn_on`/`turn_off`/`toggle` methods are removed (cherry-picked from #1320). Serviceless domains (lock, button, number, etc.) no longer inherit fallback methods that would dispatch to nonexistent HA services.

## Constraints & Anti-Patterns

- No backward compatibility alias for `toggle_service` — this is pre-1.0.
- No changes to `call_service` itself.
- No changes to generated entity models — they already use the correct domain.
- Serviceless-domain gap resolved by removing BaseEntity methods (cherry-picked from #1320).
- `Api` and `RecordingApi` are the source-of-truth implementations. `ApiSyncFacade` (`sync.py`) and `RecordingApiSyncFacade` (`sync_facade.py`) are codegen-generated — regenerate via `uv run python codegen/src/hassette_codegen/sync_facade/ --target all` after editing source files. Do NOT hand-edit the generated files.
- These methods are not `@overload`-decorated (only `call_service` is), but `tests/pyright_probes/forgotten_await_probe.py` should be verified to ensure `reportUnusedCoroutine` still fires after the type change.

## Design Doc References

- `## Architecture` — domain derivation logic, rename mechanics, `**data` forwarding pattern
- `## Replacement Targets` — what's being replaced (default value, method name, signatures)
- `## Test Strategy` — existing tests to adapt, new coverage needed
- `## Documentation Updates` — specific docs pages and snippets to update
- `## Impact → Changed Files` — complete file list with change verbs

## Convention Examples

### Domain derivation pattern

**Source:** `src/hassette/events/hass/hass.py:148`

```python
return self.entity_id.split(".", 1)[0]
```

### Shape B delegate pattern

**Source:** `src/hassette/api/api.py:570-573`

```python
def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data: Any) -> "Coroutine[Any, Any, None]":
    # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
    entity_id = str(entity_id)
    return self.call_service(domain=domain, service="turn_on", target={"entity_id": entity_id}, **data)
```

### Recording API capture with **data

**Source:** `src/hassette/test_utils/recording_api.py:415-424`

```python
async def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data: Any) -> None:
    entity_id = str(entity_id)
    self.calls.append(
        ApiCall(
            method="turn_on",
            args=(entity_id,),
            kwargs={"entity_id": entity_id, "domain": domain, **data},
        )
    )
```

### Sync facade delegation

**Source:** `src/hassette/api/sync.py:226-236`

```python
def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data: Any) -> None:
    return self.task_bucket.run_sync(self._api.turn_on(entity_id, domain, **data))
```
