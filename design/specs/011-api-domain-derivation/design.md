# Design: Derive service domain from entity_id in Api convenience methods

**Date:** 2026-07-14
**Status:** archived
**Scope-mode:** hold
**Research:** /tmp/claude-mine-define-research-yktaKQ/brief.md

## Problem

Home Assistant deprecated the generic `homeassistant.turn_on`, `homeassistant.turn_off`, and `homeassistant.toggle` services starting in 2024.x. Hassette's `Api.turn_on`, `turn_off`, and `toggle_service` default to `domain="homeassistant"`, so every caller that omits `domain=` sends a deprecated service call. App authors must pass `domain="light"` or `domain="switch"` on every call to avoid the deprecation — boilerplate that the framework should handle, since the entity_id already encodes the domain.

Additionally, `toggle_service` is named inconsistently with `turn_on`/`turn_off` and with the entity-level method (`BaseEntity.toggle`). And `turn_off`/`toggle_service` lack the `**data` parameter that `turn_on` already supports, preventing app authors from passing service data (like `transition`) on those calls.

## Goals

- `Api.turn_on("light.kitchen")` dispatches to `light.turn_on` without requiring `domain="light"`
- Explicit `domain=` override still works: `Api.turn_on("light.kitchen", domain="homeassistant")` routes to `homeassistant.turn_on`
- `toggle_service` renamed to `toggle` across all layers (Api, sync facade, recording API, entity model)
- `turn_off` and `toggle` accept `**data` kwargs for parity with `turn_on`
- All four parallel implementations (Api, ApiSyncFacade, RecordingApi, RecordingApiSyncFacade) have identical signatures
- `BaseEntity`/`BaseEntitySyncFacade` generic methods removed (cherry-picked from #1320) — eliminates serviceless-domain regression

## Non-Goals

- No backward compatibility alias for `toggle_service` (pre-1.0)
- No changes to `call_service` itself
- No changes to generated entity models (light, switch, fan, etc.) — they already call `api.call_service(domain=self.domain, ...)` directly

## User Scenarios

### App author: automation developer

- **Goal:** call turn_on/turn_off/toggle without boilerplate domain= parameter
- **Context:** writing a Hassette app that controls lights, switches, or other entities

#### Turn on a light with service data

1. **Calls `await self.api.turn_on("light.kitchen", brightness=255)`**
   - Sees: no `domain=` parameter needed
   - Then: Hassette derives `domain="light"` from the entity_id and dispatches `light.turn_on` with `brightness=255`

#### Toggle via entity model

1. **Calls `await light.toggle()`**
   - Sees: same method name as before
   - Then: internally calls `api.toggle("light.kitchen")` (renamed from `api.toggle_service`), domain derived automatically

#### Override domain explicitly

1. **Calls `await self.api.turn_on("light.kitchen", domain="homeassistant")`**
   - Sees: explicit domain takes precedence
   - Then: dispatches to `homeassistant.turn_on` (deprecated, but the caller chose it)

## Functional Requirements

- **FR#1** When `domain` is `None` (the default), `turn_on`, `turn_off`, and `toggle` derive the domain from `entity_id` using `entity_id.split(".", 1)[0]`
- **FR#2** When `domain` is explicitly passed as a string, `turn_on`, `turn_off`, and `toggle` use that string as the domain
- **FR#3** `toggle_service` is renamed to `toggle` on `Api`, `ApiSyncFacade`, `RecordingApi`, `RecordingApiSyncFacade`, `BaseEntity`, and `BaseEntitySyncFacade`
- **FR#4** `turn_off` and `toggle` accept `**data: Any` keyword arguments and forward them to `call_service`, matching `turn_on`'s existing behavior
- **FR#5** `RecordingApi.turn_off` and `RecordingApi.toggle` capture `**data` in the recorded `ApiCall.kwargs`, matching `RecordingApi.turn_on`'s existing behavior
- **FR#6** `BaseEntity` and `BaseEntitySyncFacade` no longer expose generic `turn_on`/`turn_off`/`toggle` methods — only generated domain-specific entities (light, switch, fan, etc.) provide these via their own overrides

## Edge Cases

- **Malformed entity_id (no dot):** `entity_id.split(".", 1)[0]` returns the whole string. This matches `call_service`'s existing behavior — no new failure mode introduced.
- **StrEnum entity_id:** All three methods already call `str(entity_id)` before use. The split operates on the string result.
- **Positional domain argument:** `turn_on("light.x", "light")` continues to work — `domain` remains the second positional parameter with a changed default.

## Acceptance Criteria

- **AC#1** `Api.turn_on("light.kitchen")` dispatches to domain `"light"` (FR#1)
- **AC#2** `Api.turn_on("light.kitchen", domain="homeassistant")` dispatches to domain `"homeassistant"` (FR#2)
- **AC#3** `Api.toggle` exists; `Api.toggle_service` does not (FR#3)
- **AC#4** `Api.turn_off("switch.fan", transition=2)` forwards `transition=2` as service data (FR#4)
- **AC#5** `Api.toggle("light.kitchen", transition=1)` forwards `transition=1` as service data (FR#4)
- **AC#6** `RecordingApi.toggle("light.x")` records under method name `"toggle"`, not `"toggle_service"` (FR#3, FR#5)
- **AC#7** `RecordingApi.turn_off("light.x", brightness=0)` captures `brightness=0` in recorded kwargs (FR#5)
- **AC#8** `BaseEntity` has no `turn_on`, `turn_off`, or `toggle` methods (FR#6)
- **AC#9** All existing tests pass after the signature changes (no regressions)
- **AC#10** `prek -a` (lint + type check) passes cleanly
- **AC#11** Doc snippets type-check via Pyright (CI-tested)

## Key Constraints

- The `domain` parameter type changes from `str` to `str | None`. These methods are not `@overload`-decorated (only `call_service` is), but `forgotten_await_probe.py` should be verified to ensure `reportUnusedCoroutine` still fires correctly for the Shape B delegate pattern after the type change.
- `Api` and `RecordingApi` are the source-of-truth implementations. `ApiSyncFacade` (`sync.py`) and `RecordingApiSyncFacade` (`sync_facade.py`) are codegen-generated — regenerate them via `uv run python codegen/src/hassette_codegen/sync_facade/ --target all` after editing the source files. CI enforces freshness via `--check` mode.

## Dependencies and Assumptions

- Assumes HA's entity_id format (`<domain>.<object_id>`) is stable. This is a foundational HA convention.
- No external dependencies or new libraries.

## Architecture

### Domain derivation

Change the `domain` parameter default from `"homeassistant"` to `None` on all three methods across all four implementations. When `domain is None`, derive it:

```python
def turn_on(self, entity_id: str | StrEnum, domain: str | None = None, **data: Any) -> Coroutine[Any, Any, None]:
    entity_id = str(entity_id)
    if domain is None:
        domain = entity_id.split(".", 1)[0]
    return self.call_service(domain=domain, service="turn_on", target={"entity_id": entity_id}, **data)
```

This pattern matches the existing `entity_id.split(".", 1)[0]` derivation used in `src/hassette/events/hass/hass.py:148` and `src/hassette/conversion/state_registry.py:93`.

### Rename toggle_service → toggle

Rename in `Api` (`api.py`) and `RecordingApi` (`recording_api.py`). Update the method-name string in `RecordingApi` from `"toggle_service"` to `"toggle"`. Then regenerate the sync facades (`sync.py`, `sync_facade.py`) via `uv run python codegen/src/hassette_codegen/sync_facade/ --target all` — these are codegen-generated and must not be hand-edited.

### Add **data to turn_off and toggle

Add `**data: Any` to `turn_off` and `toggle` signatures on `Api` and `RecordingApi`. Forward `**data` to `call_service` (Api) or capture in `ApiCall.kwargs` (RecordingApi). The sync facades pick up the change automatically via codegen regeneration.

### BaseEntity method removal (prerequisite — cherry-picked from #1320)

`BaseEntity` and `BaseEntitySyncFacade` no longer expose generic `turn_on`/`turn_off`/`toggle` methods. These were only hit by serviceless domains (lock, button, number, etc.) that don't have corresponding HA services — removing them prevents dispatching to nonexistent services. Generated domain-specific entities (light, switch, fan, etc.) are unaffected — they provide their own typed overrides via `call_service(domain=self.domain, ...)`.

### Recording API protocol stub

Update the protocol stub in `RecordingApi` (lines 158-161) to match the new signatures:

```python
async def turn_on(self, entity_id: str | StrEnum, domain: str | None = ..., **data) -> None: ...
async def turn_off(self, entity_id: str | StrEnum, domain: str | None = ..., **data) -> None: ...
async def toggle(self, entity_id: str | StrEnum, domain: str | None = ..., **data) -> None: ...
```

## Implementation Preferences

No specific implementation preferences — follow codebase conventions.

## Replacement Targets

| Target | Replaced by | Action |
|---|---|---|
| `domain: str = "homeassistant"` default on all three methods across four implementations | `domain: str \| None = None` with `entity_id.split(".", 1)[0]` derivation | Replace in-place |
| `toggle_service` method name across four implementations + entity model | `toggle` | Rename, remove old name |
| `turn_off` and `toggle` signatures without `**data` | Signatures with `**data: Any` | Replace in-place |

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

## Alternatives Considered

### Keep `domain="homeassistant"` default, add deprecation warning

Add a runtime deprecation warning when `domain` is the default `"homeassistant"`, nudging callers to pass an explicit domain. Rejected because: the default is already broken (HA deprecated the service), adding a warning only delays the inevitable fix, and the auto-derivation approach is strictly better — no caller action needed, no deprecation period.

### Remove `domain` parameter entirely

Always derive from entity_id, no override. Rejected because: there are edge cases where an app author might want to route through a different domain (e.g., `homeassistant.turn_on` for cross-domain bulk operations), and removing the parameter would be a more aggressive breaking change with no escape hatch.

## Test Strategy

### Existing Tests to Adapt

- `tests/unit/test_recording_api.py` — update `"toggle_service"` method-name assertions to `"toggle"`, update `"homeassistant"` domain assertions to derived domains
- `tests/unit/test_recording_sync_facade.py` — same method-name and domain assertion updates
- `tests/unit/test_api_coroutine_conversion.py` — update `toggle_service` references to `toggle`
- `tests/unit/test_sync_entity_facade.py` — update `toggle_service` call expectations, update domain assertions
- `tests/unit/test_entity_coroutine_conversion.py` — update `toggle_service` references
- `tests/unit/test_forgotten_await_completeness.py` — update `toggle_service` in method name lists
- `tests/pyright_probes/forgotten_await_probe.py` — verify `domain: str | None` doesn't break overload resolution
- `tests/integration/test_sync_facades.py` — update any `toggle_service` references
- Lock-domain-specific tests (if any assert `"homeassistant"` domain routing) — update to reflect derived domain behavior

### New Test Coverage

- Test domain derivation: `turn_on("light.kitchen")` dispatches to domain `"light"` (FR#1, unit)
- Test explicit domain override: `turn_on("light.kitchen", domain="homeassistant")` dispatches to domain `"homeassistant"` (FR#2, unit)
- Test `**data` forwarding on `turn_off` and `toggle` (FR#4, unit)
- Test `RecordingApi.toggle` records under `"toggle"` method name (FR#3, FR#5, unit)
- Test `RecordingApi.turn_off` captures `**data` in kwargs (FR#5, unit)

### Tests to Remove

No tests to remove — existing tests are adapted, not deleted.

## Documentation Updates

- `docs/pages/core-concepts/api/methods.md` — update signatures, parameter tables, deprecation warning admonitions (remove them — the default is now correct), rename `toggle_service` section to `toggle`
- `docs/pages/core-concepts/api/snippets/api_helpers.py` — update code examples to use new signatures (remove `domain=` args, rename `toggle_service` to `toggle`)
- `docs/pages/testing/harness.md` — update method-name references (`toggle_service` → `toggle`)
- `docs/pages/testing/snippets/testing_assert_turn_on_off.py` — remove `domain="light"` from examples (auto-derived now)
- `docs/pages/getting-started/snippets/first_automation_step3.py` — remove `domain="light"` from `turn_on` call
- `docs/pages/getting-started/snippets/first_automation_step4.py` — same
- `docs/pages/getting-started/first-automation.md` — update prose referencing `domain="light"` parameter
- `docs/pages/troubleshooting.md` — update `toggle_service()` to `toggle()` in forgotten-await method list
- `docs/pages/migration/snippets/` — update any snippet files referencing `domain=` on these methods
- `examples/climate_controller.py` — remove `domain=` if present (behavior improves via auto-derivation)

## Impact

### Changed Files

- **modify** `src/hassette/api/api.py` — change `turn_on`, `turn_off` signatures; rename `toggle_service` → `toggle`; add domain derivation logic and `**data` to `turn_off`/`toggle`
- **regenerate** `src/hassette/api/sync.py` — codegen-generated from `api.py`; regenerate via `--target all`
- **modify** `src/hassette/test_utils/recording_api.py` — mirror signatures; update protocol stub; update method-name string
- **regenerate** `src/hassette/test_utils/sync_facade.py` — codegen-generated from `recording_api.py`; regenerate via `--target all`
- **read** `src/hassette/models/entities/base.py` — verify BaseEntity methods removed (cherry-picked from #1320)
- **modify** `tests/unit/test_recording_api.py` — update assertions
- **modify** `tests/unit/test_recording_sync_facade.py` — update assertions
- **modify** `tests/unit/test_api_coroutine_conversion.py` — update toggle_service references
- **modify** `tests/unit/test_sync_entity_facade.py` — update assertions
- **modify** `tests/unit/test_entity_coroutine_conversion.py` — update references
- **modify** `tests/unit/test_forgotten_await_completeness.py` — update method name list
- **modify** `tests/pyright_probes/forgotten_await_probe.py` — verify/adjust probe
- **modify** `tests/integration/test_sync_facades.py` — update references
- **modify** `docs/pages/core-concepts/api/methods.md` — update signatures, tables, admonitions
- **modify** `docs/pages/core-concepts/api/snippets/api_helpers.py` — update examples
- **modify** `docs/pages/testing/harness.md` — update method name references
- **modify** `docs/pages/testing/snippets/testing_assert_turn_on_off.py` — update examples
- **modify** `docs/pages/getting-started/snippets/first_automation_step3.py` — remove domain= arg
- **modify** `docs/pages/getting-started/snippets/first_automation_step4.py` — remove domain= arg
- **modify** `docs/pages/getting-started/first-automation.md` — update prose
- **modify** `docs/pages/troubleshooting.md` — rename toggle_service → toggle

### Behavioral Invariants

- `call_service` behavior is unchanged — these methods are thin wrappers
- Generated entity models (light, switch, fan, etc.) are unchanged — they bypass these methods
- `RecordingApi.assert_called("turn_on", ...)` continues to work for `turn_on` and `turn_off`
- Explicit `domain=` override preserves the ability to route to any domain

### Blast Radius

- **App authors:** any app calling `api.toggle_service()` must rename to `api.toggle()`. Any app relying on the `"homeassistant"` default domain gets different routing (the intended fix).
- **Test authors:** tests asserting `domain="homeassistant"` on these methods need updating. Tests asserting `method="toggle_service"` in recording API output need updating.
- **Doc readers:** API reference and examples will show the new signatures.

## Open Questions

None — all questions resolved during discovery.
