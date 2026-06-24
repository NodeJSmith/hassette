# ADR-0003: Dumb State Models, Codec-Owned Conversion, and Clean Global Registries

## Status

Accepted

## Context

The `conversion ↔ models` runtime import cycle (#892, the last open cycle under #1079) has resisted the mechanical fixes that cleared the other three cycles in #1120. Every prior attempt relocated the symptom instead of the cause. This ADR records the decision to fix the cause: the conversion *behavior* that lives inside the state models.

### The cycle is one back-edge

Despite the remaining `# lazy-import:` markers in `conversion/` (`annotation_converter.py:38,40`, `state_registry.py:89`; `validation.py:77` is a load-order note, not a cycle), exactly one runtime edge points the wrong way:

```
src/hassette/models/states/base.py:10
    from hassette.conversion import TYPE_REGISTRY, register_state_converter
```

The three `conversion → models` lazy imports (`annotation_converter.py:40`, `state_registry.py:90`, and the `issubclass(tp, BaseState)` use at `annotation_converter.py:72`) are the *legitimate* direction — the conversion engine depends on the data models. They are only lazy because the back-edge above would otherwise close the loop at package-init time. Remove `base.py:10` and all three become ordinary top-level imports.

`base.py` reaches up to `conversion` for exactly two things:

- `register_state_converter(cls, ...)` in `__init_subclass__` (line 137) — every `BaseState` subclass pushes itself into the global state registry at class-definition time.
- `TYPE_REGISTRY.convert(state, cls.value_type)` in the `_validate_domain_and_state` model-validator (line 175) — scalar value coercion (`"on"` → `True`, etc.).

### Why this is a design problem, not an import problem

A Pydantic `@model_validator` is a classmethod. There is nothing to inject a registry into, so a self-validating model *must* reach for an ambient module global to convert its value. Self-validating models and "no shared mutable conversion state" are therefore mutually exclusive. The cycle is a downstream symptom of that choice. The other symptoms of the same root:

- **Process-global registries via `ClassVar`.** `TypeRegistry.conversion_map` and `StateRegistry._registry` are class variables (`type_registry.py:145`, `state_registry.py:46`). The `TYPE_REGISTRY = TypeRegistry()` singleton in `conversion/__init__.py:7-9` is a cosmetic handle; the state lives on the class. Two `Hassette` instances in one process share it — which is why `test_utils/harness.py` needs `snapshot`/`restore`.
- **Implicit load-order contract.** Importing `hassette.conversion` runs the `register_simple_type_converter(...)` calls at the bottom of `type_registry.py`. `base.py` importing `conversion` is what guarantees scalar converters exist before any state validates. `conversion/validation.py:91` literally warns "STATE_REGISTRY is empty — models package may not be imported." A missing `str → bool` converter is a correctness bug (`bool("off")` is `True`), not a missing optimization.
- **Convert-time self-mutation.** `TypeRegistry.convert` auto-registers a constructor converter into the global map on a cache miss (`type_registry.py:200-215`), making registry contents order-dependent and emitting "Overwriting existing conversion" warnings.

ADR-0002 already named "Registry Holder — stores state/type registries as class attributes" as one of the `Hassette` god-object responsibilities. This ADR resolves that thread for the registries specifically.

### What is already in place

The injectable seam exists; it is just wired to the globals.

- `core.py` exposes `hassette.state_registry` and `hassette.type_registry` properties (lines 439, 446), populated at startup from the globals (`self._state_registry = STATE_REGISTRY`, lines 220-221).
- Production already converts through those instances: `api.py:392/686` and `state_manager.py:356` call `self.hassette.state_registry.try_convert_state(...)`.
- `api.py:747` already does `self.hassette.type_registry.convert(state, model.value_type)` — the exact value-coercion pattern this ADR moves into the codec. The model validator is duplicating, the wrong way, what the API already does the right way.

### Blast radius (verified)

- **Models:** the conversion coupling is two lines in `base.py`. Every per-domain model (~40 files) only carries `field_validator`s for datetime *attribute* parsing (e.g. `sensor.py:96`, `media_player.py:147`), which depend on `utils`/`whenever` (downward, no cycle) and stay put. "Dumb models" is a `base.py`-only change; it does not ripple through the domain files.
- **Production raw-dict → State** is concentrated in `state_manager.py:87`, a few `api.py` sites, and the codec (`conversion/state_registry.py`). Not sprinkled.
- **Tests:** ~6-8 files construct states with `XState.model_validate(raw_dict)` directly (`tests/unit/conftest.py:97`, `test_sync_entity_facade.py`, `test_entity_coroutine_conversion.py`, `test_models.py:154`, `test_sync_facades.py`, `test_api_helper_models.py`). They route to a `test_utils` codec helper; the dict-builder half already exists (`helpers.py:make_light_state_dict` etc.). `test_state_manager.py` spies on `LightState.model_validate` and re-points at the codec.

### Public extension API (the constraint on "per-instance")

The registration surface is documented public API, not internal plumbing:

- `register_simple_type_converter` and `register_type_converter_fn` are re-exported from `hassette` (`__init__.py:12-13`) and used across ~10 docs pages (`core-concepts/states/conversion.md`, `custom-states.md`, the `type-registry/` snippets).
- Custom state classes auto-register by **module-level definition** — `custom-states.md` and `tests/unit/test_state_registry.py:64-89` document that defining a `BaseState` subclass at module level works with no explicit call.

"Per-instance registries" therefore cannot mean "retire the globals." It means separating the global *definition catalog* (the extension surface + the standard converters + `BaseState.__subclasses__()`) from the per-instance *live conversion state* (the resolved domain→class map and the convert-on-miss cache).

## Decision

Make state models dumb data, move conversion ownership into a codec, and build per-instance live registries from a global definition catalog.

### 1. Dumb state models

`BaseState` carries shape and a `value_type` declaration. It does not import `conversion`, does not self-register, and does not coerce its own value.

- Remove `register_state_converter` from `__init_subclass__`.
- Remove the `TYPE_REGISTRY.convert(...)` line from `_validate_domain_and_state`. Domain extraction and the `unknown`/`unavailable` handling stay (pure shape logic). Datetime field validators stay.
- `base.py` then imports nothing from `conversion`; `models/states` becomes a leaf over `types`, `const`, `utils`, `whenever`.

The codec coerces the raw value against `state_class.value_type` *before* constructing the model, so Pydantic validates an already-typed value. `__init_subclass__` stays as the registration mechanism but writes a `models`-layer state-class catalog (a sibling leaf), not `conversion` — keeping eager, order-independent, all-depth registration while removing the back-edge.

### 2. The codec owns dict → State and known-model coercion

The conversion engine (today's `conversion` package) is the single place that turns raw Home Assistant JSON into a typed state: resolve domain → look up the state class → coerce the value via the type registry → construct. It also exposes a known-model coercion path (target class + raw dict) for `state_manager`. The lazy `conversion → models` imports become top-level (the legitimate direction). Coercion failures are wrapped so the existing `UnableToConvertStateError(entity_id, model)` contract holds.

### 3. Clean global registries (revised — per-instance rejected)

> **Revision (2026-06-23):** the original proposal here was per-instance live registries built from a global catalog. Verification during the challenge killed that: production is single-instance (`context.set_global_hassette` raises on a second instance, `context.py:41-43`), and per-instance does not isolate tests because the pollution is at the process-global `__init_subclass__`/catalog level. The decision is now clean global registries (was "Alternative B1").

- `TYPE_REGISTRY`/`STATE_REGISTRY` stay process-global singletons; the `hassette.*_registry` accessors keep returning them. No per-instance build, no active-context routing.
- The shared domain→class map moves from `StateRegistry._registry` (`ClassVar` in `conversion`) into the `models`-layer catalog leaf so `models` never imports `conversion`; the codec's `StateRegistry` reads it.
- **Stop the convert-on-miss self-write** (`type_registry.py:205`): `TypeRegistry` becomes read-only after its standard converters load, removing the type-side `snapshot`/`restore` entirely.
- The state-side reset fixture stays (simplified to the state catalog) — it is irreducible while `__init_subclass__` auto-registration remains a documented feature.

### 4. Enforcement

- Flip the three `conversion`-side lazy imports to top-level and delete the `# lazy-import:` annotations (keep `validation.py:77`, a load-order note, not a cycle). Clearing `annotation_converter.py:39` requires relocating the `TYPE_REGISTRY`/`TYPE_MATCHER` singleton definitions out of `conversion/__init__.py` into their submodules (re-exported).
- Add a `models-no-conversion` rule to `tools/check_module_boundaries.py` so the back-edge cannot re-accrete.

## Consequences

### Positive

- The `conversion ↔ models` cycle is gone, and the dependency graph is one-directional. This unblocks the #633 graph cycle detector.
- `models/states` becomes a true leaf relative to `conversion`. Conversion lives in one place and is testable.
- The convert-time self-mutation is removed and the type-side `snapshot`/`restore` with it; the import-order warning is addressed by the model no longer needing `conversion` at all.
- Resolves the registry portion of the ADR-0002 god-object thread without adding per-instance machinery.

### Negative / costs

- Breaking internal change. `LightState.model_validate(raw_ha_dict)` no longer coerces a raw HA dict standalone; raw-dict construction goes through the codec. Pre-1.0, internal breakage is acceptable.
- `__init_subclass__` stays, so the **state-side reset fixture stays** (simplified to the state catalog). This is the deliberate trade: keeping the documented "module-level custom state just works" DX means custom classes register globally, so tests still reset between runs. Only dropping that DX would remove the fixture, which is not worth it.
- Test migration: route direct `XState.model_validate(raw_dict)` calls through a `test_utils` codec helper; re-point the `model_validate` spy in `test_state_manager.py`; rewrite `TestConstructorFallbackCache`'s memoization assertions. Mechanical, spread across ~8 files.

### Honest limit

The state-class catalog is process-global (via `__init_subclass__`). This design does not isolate it per-run — the reset fixture remains the isolation mechanism. That is accepted: per-instance registries were verified not to remove it either (production is single-instance; the catalog stays global regardless), so the extra machinery bought nothing.

## Phased plan (verifiable checkpoints)

1. **Break the cycle + dumb models.** Extract the state-class catalog leaf; repoint `__init_subclass__`; move value coercion + the known-model path into the codec with error wrapping; flip the lazy imports to top-level (incl. the singleton relocation that clears `annotation_converter:39`). Checkpoint: cycle gone, `check_module_boundaries`/`check_lazy_imports` clean, full suite green.
2. **Registry hygiene.** Stop the convert-on-miss self-write; remove `TypeRegistry.snapshot`/`restore`; simplify the `conftest.py` reset fixture to the state catalog; rewrite `TestConstructorFallbackCache`. Checkpoint: suite green, no type-registry mutation on the hot path.
3. **Lock it.** Add the `models-no-conversion` boundary rule; update the affected docs pages. Checkpoint: boundary rule self-proves the break.

## Alternatives considered

- **B2 — Per-instance live registries (originally proposed here).** Build each `Hassette` a registry from a process-global catalog. **Rejected after verification:** production is single-instance (`context.py:41-43` forbids a second), and per-instance does not isolate tests (pollution is at the `__init_subclass__`/catalog level, which stays global). It adds active-context routing, `ClassVar`→instance migration, and DI-path threading to solve nothing. Full analysis in `design/specs/084-dumb-state-models-codec-conversion/challenge-results.md`.
- **A — Smart models, registries demoted to a leaf.** Keep the model validator coercing via a leaf registry. Smaller, keeps standalone `model_validate`, but keeps the model owning conversion and the convert-on-miss self-write. The chosen design is barely larger and removes both.
- **Drop `__init_subclass__` for explicit registration.** Would remove the state reset fixture entirely, but breaks the documented "module-level custom state just works" DX. Rejected — the fixture is the smaller cost.
- **C — Status quo with the lazy imports.** Rejected: leaves a static cycle that blocks #633.

## References

- Issue #1079 (break import cycles), #892 (`conversion ↔ models`), #633 (boundary enforcement this unblocks)
- PR #1120 (broke the other three cycles via protocol/factory inversion)
- ADR-0002 (Hassette god-object extraction; names the registry-holder responsibility)
- Research brief: `design/research/2026-06-22-break-import-cycles/research.md`
