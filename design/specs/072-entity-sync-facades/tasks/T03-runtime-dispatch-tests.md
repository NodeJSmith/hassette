---
task_id: "T03"
title: "Add runtime dispatch tests for domain sync facades"
status: "planned"
depends_on: ["T02"]
implements: ["AC#2", "AC#3", "AC#4", "AC#5"]
---

## Summary

Add unit tests that exercise the generated domain sync facades at runtime:
`.sync` returns the domain-specific facade type, and facade methods dispatch the
correct synchronous `api.sync.call_service` for no-param, required-param, and
optional-param services. Confirm the inherited base actions still work. These
tests require the regenerated facade classes from T02.

## Prompt

Depends on T02 (the `{Domain}EntitySyncFacade` classes must exist as generated
code).

Add a new test file `tests/unit/test_sync_entity_facade.py`. Follow the dispatch
and mocking pattern already used in
`tests/unit/test_entity_coroutine_conversion.py:307-322`, which patches
`api.sync` with a mock and calls `entity.sync.turn_on(...)`. Construct domain
entities the same way that file does (it builds entities and patches `api.sync`).

Cover these cases:

1. **`.sync` returns the domain facade type (AC#2):** for `CoverEntity`,
   `ClimateEntity`, and `LightEntity`, assert
   `isinstance(entity.sync, {Domain}EntitySyncFacade)` and that it is NOT merely
   the base type (`type(entity.sync) is {Domain}EntitySyncFacade`).

2. **No-param dispatch (AC#3):** patch `api.sync`, call
   `cover.sync.open_cover()`, assert `api.sync.call_service` was called once with
   `domain=<cover domain>`, `service="open_cover"`,
   `target={"entity_id": <id>}`, and no extra kwargs.

3. **Required-param dispatch (AC#4):** call
   `climate.sync.set_temperature(temperature=21.0)`, assert `call_service` was
   called with `service="set_temperature"` and `temperature=21.0` passed through.

4. **Optional-param / inherited base actions (AC#5):** call
   `light.sync.turn_on(brightness=128)` and `light.sync.turn_off()`, assert they
   route through `api.sync.turn_on(...)` / `api.sync.turn_off(...)` (the inherited
   `BaseEntitySyncFacade` methods) — confirming inheritance is intact.

Also confirm the existing regression test still passes:
`tests/unit/test_entity_coroutine_conversion.py::test_entity_sync_turn_on_registers`
(it calls `entity.sync.turn_on(brightness=100)` through the inherited route; after
this change `LightEntity.sync` is `LightEntitySyncFacade`, which inherits
`turn_on`, so it must stay green).

Run: `uv run pytest tests/unit/test_sync_entity_facade.py
tests/unit/test_entity_coroutine_conversion.py tests/unit/test_recording_sync_facade.py -v`

## Focus

- Reference pattern: `tests/unit/test_entity_coroutine_conversion.py` —
  `test_entity_sync_turn_on_registers` (line ~307) patches `api.sync` to a mock
  (`api.sync = mock_sync`) and asserts on the call. Reuse this approach; do not
  spin up a real event loop.
- Entity construction helpers may also live in
  `src/hassette/test_utils/recording_api.py` and
  `src/hassette/test_utils/sync_facade.py` — check there for fixtures that build
  entities with a recording/mock api before hand-rolling your own.
- Mock at the boundary: patch `api.sync` (or its `call_service`), use real entity
  and facade instances. Do not mock the facade itself.
- The facade delegates `service=` from the literal in the generated method, and
  `domain`/`entity_id` from `self.entity` — assert all three.
- `set_temperature` lives on `ClimateEntity`; confirm the exact generated
  `method_name` and param name by reading the regenerated
  `src/hassette/models/entities/climate.py` before asserting (HA may name the
  param `temperature`).

## Verify

- [ ] AC#2: `CoverEntity(...).sync`, `ClimateEntity(...).sync`, and
      `LightEntity(...).sync` are instances of their respective
      `{Domain}EntitySyncFacade`, not `BaseEntitySyncFacade`.
- [ ] AC#3: `CoverEntity(...).sync.open_cover()` calls `api.sync.call_service`
      once with `service="open_cover"` and the correct domain/target.
- [ ] AC#4: `ClimateEntity(...).sync.set_temperature(temperature=21.0)` calls
      `api.sync.call_service` with `service="set_temperature"` and the temperature
      passed through.
- [ ] AC#5: `LightEntity(...).sync.turn_on(brightness=128)` and `.turn_off()`
      route through the inherited base facade methods and still work;
      `test_entity_sync_turn_on_registers` remains green.
