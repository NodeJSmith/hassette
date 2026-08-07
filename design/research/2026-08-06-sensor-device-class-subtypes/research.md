# Research Brief: Device-Class-Specific Sensor State Subtypes (#717)

---
proposal: "Emit per-device-class SensorState subtypes from codegen (TemperatureSensorState, EnumSensorState, ...) so sensor values are typed instead of always `str`."
date: 2026-08-06
status: Draft (revision 3)
flexibility: Exploring
motivation: "Type-checker friction, runtime correctness, codegen fidelity, and discoverability — all four, none dominant."
constraints: "Pre-1.0; breaking changes acceptable but must be enumerated. Public API surface deliberately minimal. Docs ship with the feature."
non-goals: "None stated by caller; scope deliberately left to research."
depth: deep
revision: 3
---

**Initiated by**: GitHub issue #717 — "Add device-class-specific sensor state subtypes", plus a requirements interview stating the shape is *not* decided and competing designs are wanted.

## Corrections in Revision 3

The user reviewed revision 2 and made three corrections. Two delete work; one reshapes Option E and
sent me to a live Home Assistant instance for evidence I should have gathered in revision 1.

| # | Revision 2 said | Revision 3 says | Consequence |
|---|---|---|---|
| 1 | The catalog clobber is "a live bug — silent data loss" and Option G should fix it. | **Wrong. The clobber is the intended override mechanism** — it is how a user supplies a different definition for a domain. Not a bug, needs no guard. | **Option G cut** and rewritten as a rejected option. The overwrite guard and the validator rewrite go with it. Critics' Finding 3 is half-rejected. |
| 2 | Granularity: carry the device class as an argument (`sensor.of(SensorDeviceClass.TEMPERATURE)`) with 61 stub overloads. | **Rejected.** The user cares about *types*, not about accessing temperature vs humidity. Filtering to a device class is a **data query** and does not belong in a typing feature. | Option E becomes four plain accessors. 61 overloads gone; per-release stub regeneration gone. |
| 3 | Option E's benefit is "unevidenced by observed usage" because every `float(str(...))` site is a DI handler in `examples/`/`docs/`. | **Invalid reasoning.** Hassette is a framework; its callers are user apps outside this repo. Absence of a pattern in `examples/` is evidence about the examples, nothing more. | Caveat removed from Option E and the Recommendation. Audited the whole brief for the same reasoning shape — **three more instances found and corrected** (Q4 twice, Recommendation once). |

**Structural consequence of correction 1, worth stating plainly: with Option G cut, nothing in the
recommendation touches the catalog, the registration path, or `validate_registries` at all.** The
whole feature reduces to four generated classes, four stub entries, four properties, and a predicate
on `DomainStates`. Every finding the three critics raised — Findings 1 through 6 — was about catalog
dispatch, and all six are now out of scope rather than argued with.

**Correction 1's deeper point, which I am adopting as a design rule:** registering ~61 catalog entries
to express 4 types is the wrong shape. The 61→4 relationship is *data*, not keys. If runtime dispatch
(C3) is ever revisited, it should be priced as a **two-step lookup** — device class → value shape →
class, keeping one catalog entry per domain — never as 61 `StateKey`s.

**New evidence gathered for revision 3.** Correction 2 asked me to re-examine the no-device-class
case rather than defer it. I surveyed the user's live HA instance (864 entities, 270 sensors). The
result overturns revision 2's answer — see **"The no-device-class question"** in Option E. Short
version: **46% of real sensors have no device class**, and revision 2's rule would have silently
excluded 37 genuinely numeric sensors, about a quarter of the numeric population.

## Corrections in Revision 2

Revision 1 went through a three-critic adversarial challenge and then a user review. The user found
four things neither revision 1 nor the critics considered. All four are load-bearing, and two of them
invalidate conclusions revision 1 stated confidently. **The recommendation has changed.**

| # | Revision 1 said | Revision 2 says | Consequence |
|---|---|---|---|
| 1 | The accessor path (`self.states.sensor[...]`) "can never narrow statically" because `state_manager.pyi` is a fixed domain→class table. | **Wrong.** Hand-written is exactly *why* it can. Nothing requires a stub accessor to correspond to a real HA domain. Verified with pyright: an invented `self.states.numeric_sensor` accessor narrows correctly. | New **Option E**. Q4 verdict corrected. The critics' Finding 1 rested on this premise too. |
| 2 | `D.StateNew[X]` "bypasses the catalog entirely" — treated as inert. | True but incomplete. `convert_state_dict_to_model` holds the raw dict and *could* consult `resolve()`. Also, the `suppress(UnableToConvertValueError)` at `state_registry.py:257` does **not** make mismatches silent — Pydantic raises immediately after. The *opposite* direction (annotating a looser class) is the silent one. | New **Option F**. Q4 corrected in both directions. |
| 3 | "Generated subclasses must not re-declare `domain`" — a workaround for the clobber trap, which then broke `get_domain()` (critics' Finding 4). | **Solving the wrong problem.** The clobber exists *only* because `device_class` is not part of the derived key. Verified: composite-key derivation lets subclasses safely re-declare `domain`, and `get_domain()` then works. | New **Option G**. Q5 resolution rewritten. Dissolves critics' Findings 2 and 4. |
| 4 | Four access paths examined. | **~20 call sites across 17 named surfaces exist.** Revision 1 missed every sync-facade mirror, `D.StateOld` / `MaybeState*` / `TypedStateChangeEvent` / `EventData`, `Api.get_entity`, and the entire test-utils surface. | Q4's inventory replaced. Every option's blast radius re-assessed against the full set. |

A fifth correction is mine, not the user's: revision 1's recommendation assumed runtime dispatch was
straightforwardly good. It has a cost revision 1 and all three critics missed — see
**"The `cast()` problem"** in the revised Recommendation. It is the reason runtime dispatch is now
deferred rather than recommended.

Everything else in revision 1 — Q1, Q2, Q3, Q6, the three footguns, the HA-core counts, the
blast-radius numbers — was re-checked and stands. Corrected passages are marked
**`[CORRECTED v2]`** inline rather than silently rewritten.

## Context

### What prompted this

`sensor.outdoor_temperature` reports `"23.5"`. Hassette hands the app author a `SensorState` whose
`value` is `str | None`. Every numeric sensor automation therefore starts with a conversion dance.
This is not hypothetical — it is the shape of the code in this repo's own examples and docs:

```python
# examples/climate_controller.py:88-91
temp = float(new_state.value) if new_state.value is not None else None
```
```python
# docs/pages/recipes/snippets/debounce_sensor.py:26  — note the double conversion
new_temp = float(str(new_state.value))
```
```python
# examples/demo_stimulator.py:143
readings[key] = round(float(value), 2)  # pyright: ignore[reportArgumentType]
```

The `pyright: ignore` is the tell. The author knows the value is numeric; the type system does not.

### Current state

**Value typing is per-domain, one class per domain, chosen by a codegen heuristic.**
`codegen/src/hassette_codegen/extractors/base_class.py:8-35` inspects HA's `SensorEntity.state`
return annotation (`-> Any`), finds nothing numeric, and picks `StringBaseState`. So:

```python
# src/hassette/models/states/sensor.py:111-119   (generated)
class SensorState(StringBaseState):
    domain: Literal["sensor"]
    attributes: SensorAttributes
```
```python
# src/hassette/models/states/base.py:224
class StringBaseState(BaseState[str | None]):
    value_type: ClassVar[...] = (str, type(None))
```

**Conversion is a two-registry pipeline** (ADR-0003, `design/adrs/0003-dumb-state-models-codec-owned-conversion.md`):
`StateRegistry` answers "which class?", `TypeRegistry` answers "which type for `value`?" by reading
the class's `value_type` ClassVar. Models are deliberately dumb — they must not import `conversion`,
enforced by `tools/check_module_boundaries.py`.

**The main access paths and what each is declared to return.** *(**`[CORRECTED v2]`** Revision 1
listed five paths here and drew conclusions from that set. There are ~20 call sites across 17 named
surfaces — the full inventory is in Q4. These five remain the representative ones.)*

| Path | Declared type | Where |
|---|---|---|
| `self.states.sensor["x"]` | `SensorState` | `state_manager.pyi:127-128` — a **hand-written** table of 55 domain properties, no generator, no freshness check |
| `self.states.get("sensor.x")` | `BaseState \| None` | `state_manager.pyi:165` |
| `self.states[X]` | `DomainStates[X]` | `state_manager.pyi:159` — **author names the class** |
| `await api.get_state(...)` | `BaseState` | `api/api.py:755` |
| `D.StateNew[X]` handler param | `X` | `event_handling/dependencies.py:124-127` — **author names the class** |

Eleven of the seventeen surfaces carry a caller-supplied class; six are erased to `BaseState`; and the
domain-accessor path is neither — it resolves its class from the registry once and holds it fixed.
`bus.on_state_change()` takes `handler: HandlerType` = `(*args: Any, **kwargs: Any)`
(`types.py:287-301`) and carries zero type information into the handler; all handler typing comes
from the DI annotations the author writes.

### Key constraints

- Pre-1.0; breaking changes acceptable if documented as `BREAKING CHANGE:`.
- Public API surface deliberately minimal (CLAUDE.md; `feedback_minimize-public-api-surface`). Today
  `models/states/__all__` has **192 names**.
- ADR-0003: models stay dumb, no conversion logic in generated models, registries are process-global.
- `whenever` types (`Date`, `ZonedDateTime`) for date/time, not stdlib.
- Codegen is a separate package with its own lockfile; freshness is CI-only (`.github/workflows/lint.yml:154-191`).
- Docs ship with the feature (`.claude/rules/design-completeness.md`).

---

## Answers to the Six Questions

### Q1 — Is the device-class dispatch path real?

**Verdict: genuinely wired, completely unused. Not half-built.** [Direct]

```python
# src/hassette/models/states/catalog.py:20-60
@dataclass(frozen=True)
class StateKey:
    domain: Hashable | None = None
    device_class: Hashable | None = None

def register_state_converter(state_class, domain: Hashable, device_class: Hashable | None = None) -> None:
    key = StateKey(domain=domain, device_class=device_class)
    _STATE_CATALOG[key] = state_class

def resolve(*, domain=None, device_class=None) -> type["BaseState"] | None:
    candidates = [StateKey(domain=domain, device_class=device_class)]
    if device_class is not None:
        candidates.append(StateKey(domain=domain, device_class=None))
    for k in candidates:
        if k in _STATE_CATALOG:
            return _STATE_CATALOG[k]
    return None
```

The exact→domain-only fallback chain works. Verified at runtime: registering a class under
`StateKey("sensor", "temperature")` makes `resolve(domain="sensor", device_class="temperature")`
return it, while `device_class="humidity"` correctly falls back to `SensorState`.

But **all 55 catalog entries have `device_class=None`** (verified by inspecting `_STATE_CATALOG` at
runtime), because the sole populator omits it:

```python
# src/hassette/models/states/base.py:155-158
def __init_subclass__(cls, **kwargs):
    super().__init_subclass__(**kwargs)
    with suppress(NoDomainAnnotationError):
        register_state_converter(cls, domain=cls.get_domain())
```

And all four production `resolve()` call sites pass `domain` only:
`conversion/state_registry.py:95`, `state_registry.py:134` (pass-through), `state_manager.py:251`,
plus docs snippets.

**Provenance** [Direct]: `git log` shows the parameter arrived in commit `347fced7` (2025-12-13,
PR #197, *"Wait until hitting user code to cast states to specific model"*). The predecessor
`c965375b` (PR #196) had a plain `dict[str, type[BaseState]]` with no device class. **PR #197's body
never mentions `device_class`** — it is about deferring conversion. So the parameter was added in
passing and has survived ~8 months and four refactors with no caller. `design/research/2026-05-01-type-state-registries/research.md:17,147`
later described the fallback chain as if it were live and validated it as "the same pattern HA's
entity registry uses" — the pattern was blessed, the population half was never built.

**So #717 is a codegen-shaped task at the leaf, but a registration-mechanism task in the middle.**
The catalog needs no redesign. `__init_subclass__` does — it has no way to express a device class,
and both workarounds fail (see Q5).

The single missing wire is one expression:

```python
# src/hassette/conversion/state_registry.py:95 — today
state_class = self.resolve(domain=domain)
# would become
state_class = self.resolve(domain=domain, device_class=data.get("attributes", {}).get("device_class"))
```

### Q2 — Where does `device_class` live at conversion time?

**It is reliably in scope, and reading it is free.** [Direct]

`try_convert_state(self, data: "HassStateDict", entity_id=None)` holds the full raw dict for its
entire body (`state_registry.py:67-111`), and `attributes` is a `Required` key of that TypedDict
(`events/hass/raw.py:30`). The domain is derived by string-splitting `entity_id` (`:93`), never from
the payload.

Behavior in the edge cases, all handled by the existing fallback chain:

| `attributes["device_class"]` | `resolve()` behavior |
|---|---|
| absent | `.get()` → `None` → single candidate `StateKey("sensor", None)` → `SensorState` |
| `None` | same as absent |
| unknown/custom string | exact key misses, falls back to `StateKey("sensor", None)` → `SensorState` |
| known string | exact hit → narrowed class |

HA writes the attribute itself. `homeassistant/helpers/entity_registry.py:450-452`:

```python
device_class = self.device_class or self.original_device_class
if device_class is not None:
    attrs[EntityStateAttribute.DEVICE_CLASS] = device_class
```

**Yes, it changes for live entities.** [Direct] That `or` is a user-facing override: the entity
registry stores a settable `device_class` (`entity_registry.py:226`) alongside the integration's
`original_device_class` (`:243`). A user changing device class in the HA UI produces a new
`state_changed` event carrying different attributes. Because state models are `frozen=True` and
constructed per-event, the next conversion simply picks a different class — no stale-model problem.
It does mean **the concrete Python class for a given entity is not stable over the process lifetime**,
which matters for any design that caches a class per entity ID or lets an author bind
`self.states[TemperatureSensorState]` to a device-class-scoped view.

### Q3 — Upstream source of truth: derivable or hand-maintained?

**Mechanically derivable. No hand-maintained table needed — HA does the same set subtraction itself.** [Direct]

```python
# homeassistant/components/sensor/const.py:556-561
NON_NUMERIC_DEVICE_CLASSES = {
    SensorDeviceClass.DATE,
    SensorDeviceClass.ENUM,
    SensorDeviceClass.TIMESTAMP,
    SensorDeviceClass.UPTIME,
}
```
```python
# homeassistant/components/sensor/websocket_api.py:17
_NUMERIC_DEVICE_CLASSES = list(set(SensorDeviceClass) - NON_NUMERIC_DEVICE_CLASSES)
```

And the runtime predicate confirms the per-device-class part is the whole story
(`sensor/__init__.py:126-145`) — the unit / state-class / precision checks only widen the numeric set
to sensors that declared *no* device class:

```python
def _numeric_state_expected(device_class, state_class, native_unit_of_measurement, suggested_display_precision) -> bool:
    if device_class in NON_NUMERIC_DEVICE_CLASSES:
        return False
    ...
    return device_class is not None
```

The three non-numeric shapes are individually special-cased in `SensorEntity.state`
(`sensor/__init__.py:599-754`): `timestamp`/`uptime` → tz-aware datetime, emitted as UTC
`isoformat(timespec="seconds")` (:656-681); `date` → `date.isoformat()` (:683-694); `enum` → a string
validated against `self.options` (:696-713).

**Counts** (HA 2026.8.0 in `~/source/core`; hassette pins 2026.7.1 in `codegen/ha-version.txt`):

| | count |
|---|---|
| `SensorDeviceClass` members, HA 2026.8.0 | 62 |
| `SensorDeviceClass` members, hassette's generated enum (2026.7.1) | **61** (verified at runtime; missing `RADON`) |
| non-numeric | **4** |
| numeric | 57 (hassette) / 58 (2026.8.0) |

So the derivation is: parse one `set` literal from `const.py` — the same file codegen already
AST-parses for the enum (`extractors/features.py:50-81`) — and hard-code the semantics of exactly
**four** members. `DEVICE_CLASS_STATE_CLASSES` (`const.py:810-889`, 62 keys, the 4 non-numeric ones
mapping to `set()`) is an exact cross-check and makes a good drift tripwire.

**What is *not* derivable** [Direct]: `int` vs `float`. No structure distinguishes them;
`_attr_native_value` permits `int | float | Decimal | str` for every numeric device class, and HA's
`state` property coerces to `int` opportunistically based on the string's shape (`:728-733`). The
honest mechanical answer is `int | float | Decimal | None` for all numerics. Do not attempt a 57-entry
int/float table.

Two other candidate signals are **wrong** and should be named so nobody reaches for them:
- `DEVICE_CLASS_UNITS` (57 keys) omits `MONETARY`, which *is* numeric.
- `UNIT_CONVERTERS` (41 keys) omits 17 numeric classes including `BATTERY`, `HUMIDITY`, `CO2`.

One thing genuinely *is* derivable per device class beyond the value shape: the unit literal.
`DEVICE_CLASS_UNITS` maps 57 device classes to their permitted unit sets, so
`TemperatureSensorState.attributes.unit_of_measurement: Literal["°C", "°F", "K"] | None` is
mechanical. That is the only real type information a per-device-class class adds over a
per-value-shape class. It is also a liability — custom integrations report off-spec units, and
`model_config` has `extra="allow"`, so a `Literal` would be a promise the runtime does not keep.

### Q4 — Does narrowing actually help the type checker?

> **`[CORRECTED v2]`** Revision 1 answered "two of five access paths gain; three cannot," and declared
> the accessor path permanently un-narrowable. Both halves were wrong: the inventory was a quarter of
> the real surface, and the accessor path is narrowable with a one-line stub edit. The corrected
> answer is below; the original erasure analysis for `bus.on_state_change` and the `cast`-based paths
> still stands.

**Corrected verdict: of 17 named surfaces (~20 call sites), 11 already carry a caller-supplied class
and narrow today; 6 are erased to `BaseState`; and the accessor path — previously written off — can
be narrowed cheaply and is the only surface where declared and runtime types can be made to agree
exactly.** [Direct]

#### The full access-path inventory

**Group 1 — author names the class (static narrowing works *today*, needs only the class to exist).**

| # | Surface | Declared return | Mechanism |
|---|---|---|---|
| 1 | `self.states[X]` | `DomainStates[X]` | `state_manager.py:266-285` — constructs `DomainStates` with the caller's model, no registry |
| 2 | `D.StateNew[X]` | `X` | `dependencies.py:124-127` → `annotation_converter.py:71-73` |
| 3 | `D.StateOld[X]` | `X` | `dependencies.py:151-154` |
| 4 | `D.MaybeStateNew[X]` | `X \| None` | `dependencies.py:137-140` |
| 5 | `D.MaybeStateOld[X]` | `X \| None` | `dependencies.py:165-168` |
| 6 | `D.TypedStateChangeEvent[X]` | `TypedStateChangeEvent[X]` | `dependencies.py:112-114` → `annotation_converter.py:165-193` |
| 7 | `D.EventData[X]` | `X` | `dependencies.py:227-230` — hits the same `BaseState` branch if `X` is a state class |
| 8 | `Api.get_entity(id, M)` / `get_entity_or_none` | `EntityT` | `api/api.py:723-745` — **entity**-level; `model.model_validate({"state": raw})` |
| 9 | `ApiSyncFacade.get_entity` / `get_entity_or_none` | `EntityT` | `api/sync.py:292-315` |
| 10 | `make_typed_state(cls, dict)` | `StateT` | `test_utils/helpers.py:278-294` |
| 11 | `RecordingApi.get_entity` | `BaseEntity` | `test_utils/recording_api.py:764+` |

**Group 2 — registry-dispatched, declared `BaseState` (erased; only *runtime* type can change).**

| # | Surface | Declared return | Failure behavior |
|---|---|---|---|
| 12 | `StateManager.get(entity_id)` | `BaseState \| None` | swallows the exception, returns `None` (`state_manager.py:316-325`) |
| 13 | `Api.get_state` | `BaseState` | raises `UnableToConvertStateError` (`api.py:755-765`) |
| 14 | `Api.get_state_or_none` | `BaseState \| None` | as above, plus `EntityNotFoundError` → `None` |
| 15 | `Api.get_states` | `list[BaseState]` | **`suppress(UnableToConvertStateError)` — failing entities silently vanish from the list** (`api.py:433`) |
| 16 | `ApiSyncFacade.get_state` / `_or_none` / `get_states` | same | `api/sync.py:133-142, 316-336` |
| 17 | `RecordingApi` / `RecordingSyncFacade` mirrors | same | `test_utils/recording_api.py:743-762`, `test_utils/sync_facade.py:282-298` |

**Group 3 — the domain-accessor path, which is neither of the above.**

`self.states.sensor[...]` resolves its class from the registry once (`__getattr__` →
`resolve(domain=...)`, `state_manager.py:250-264`) and then holds it fixed:
`DomainStates._validate_or_return_from_cache` calls
`STATE_REGISTRY.coerce_and_construct(self._model, ...)` (`:96`), never `try_convert_state`. So it
picks up neither Group 1's caller-supplied class nor Group 2's per-entity dispatch. Its declared type
comes from the hand-written stub.

**Three surfaces stay erased no matter what.** `bus.on_state_change(handler=...)` takes
`HandlerType = (*args: Any, **kwargs: Any)` (`types.py:287-301`) and carries no types;
`event.payload.data.new_state` on `RawStateChangeEvent` is `HassStateDict | None`
(`events/hass/hass.py:111`), a TypedDict that narrows to no model; and `Api.get_state_value` returns
`Any` by design.

#### The accessor path is narrowable — corrected

Revision 1 treated `state_manager.pyi` as a constraint. It is a **169-line hand-written file with no
generator and no freshness check** — I grepped `codegen/src/`, `scripts/`, and `tools/` for `.pyi`
and found nothing. Nothing ties a stub accessor to a real HA domain.

**Verified with pyright.** I temporarily added one property to the stub —
`def numeric_sensor(self) -> DomainStates[states.NumberState]: ...` — and type-checked:

```python
s = self.states.numeric_sensor["sensor.outdoor_temp"]
return (s.value or 0.0) + 1.0
```
```
error: Operator "+" not supported for types "Decimal" and "float" (reportOperatorIssue)
```

Pyright resolved the invented accessor and narrowed `s.value` to `int | float | Decimal | None`. The
diagnostic *is* the proof: it can only arise if the narrowing landed. (Stub restored; `git status`
clean.)

**A bonus finding from that error:** `int | float | Decimal | None` is hostile to authors —
`Decimal + float` is a type error, so every arithmetic expression needs a guard. This is a concrete
argument for typing `NumericSensorState.value` as `float | None` rather than mirroring
`NumericBaseState`'s full numeric union.

#### DI is not inert — corrected, in both directions

Revision 1 said `D.StateNew[X]` "bypasses the catalog entirely" and stopped there. Two corrections:

**(a) A stricter-than-reality annotation already fails loudly, not silently.** The
`suppress(UnableToConvertValueError)` at `state_registry.py:257` only skips the `TYPE_REGISTRY` step;
`model.model_validate(prepared)` runs next and rejects the value. Verified —
`D.StateNew[NumericSensorState]` on an enum sensor:

```
RAISED: ValidationError — 3 validation errors for NumericSensorState
  state.int      Input should be a valid integer   [input_value='running']
  state.float    Input should be a valid number    [input_value='running']
  state.decimal  Input should be a valid decimal   [input_value='running']
```

It raises, but as a raw Pydantic `ValidationError` about `state.int` — not "sensor.washer is an enum
sensor; you annotated a numeric class." And because DI calls `convert_state_dict_to_model` directly
rather than through `conversion_with_error_handling` (`state_registry.py:159-195`), it never gets
wrapped into the framework's `UnableToConvertStateError`. So the *legibility* is bad, not the safety.

**(b) A looser-than-reality annotation is genuinely silent.** Verified —
`D.StateNew[EnumSensorState]` (value typed `str`) on a temperature sensor:

```
NO RAISE. value = '23.5' | real device_class = temperature
```

This is the actual silent-failure mode, and it is the one an author hits by *under*-narrowing.

**(c) `D.TypedStateChangeEvent[X]` converts both states to one class.**
`annotation_converter.py:180-181` applies the same `state_tp` to `old_state` and `new_state`. Since
`device_class` is user-mutable at runtime (Q2), an event can straddle a device-class change, and
there is then no single correct `X`. In practice the old state would fail conversion and raise. Any
device-class-aware design must state a rule here; revision 1 never noticed the surface existed.

#### Before / after, the code an author actually writes

```python
# today
async def on_temp(self, new: D.StateNew[states.SensorState]) -> None:
    temp = float(str(new.value))          # str -> float, two casts, can raise
    if temp > self.app_config.threshold:
        ...

# with narrowed classes (Option A/E)
async def on_temp(self, new: D.StateNew[states.NumericSensorState]) -> None:
    if new.value is not None and new.value > self.app_config.threshold:
        ...

# with a narrowed accessor (Option E) — the path revision 1 said was impossible
for entity_id, s in self.states.numeric_sensor.items():
    self.logger.info("%s = %.1f", entity_id, s.value)   # s.value is float | None
```

**Empirically verified** — the conversion pipeline against a raw temperature state dict:

```
SensorState.value:              '23.5'  str
NumericSensorState.value:        23.5   float
```

**Three footguns found by running it, not by reading it** [Direct — all still stand]:

1. **Overriding `value_type` alone does nothing.** The naive subclass —
   `class TemperatureSensorState(SensorState): value_type = (float, type(None))` — still yields
   `'23.5'` as a `str`. `TypeRegistry` converts it to `23.5`, then Pydantic re-validates against the
   inherited `value: str | None` field and `coerce_numbers_to_str=True` (`base.py:72`) turns it back
   into a string. The subclass must re-declare the field.
2. **Re-declaring `value` must repeat the alias.** `base.py:105` is
   `value: StateValueT = Field(..., validation_alias=AliasChoices("state", "value"))` and there is no
   `populate_by_name`. A subclass that writes `value: float | None = None` without the alias silently
   stops being populated from state dicts.
3. **Pyright does not complain about the narrowing.** A probe with
   `value: float | None` overriding `value: str | None` produced zero diagnostics under this repo's
   `pyrightconfig.json` (`typeCheckingMode: "basic"`; `reportIncompatibleVariableOverride` is
   commented out at line ~95). No `# pyright: ignore` needed in generated code.

**Honest summary of the win, corrected.** Static narrowing is available on 11 surfaces today for the
cost of the classes existing, and on the accessor path for the cost of stub entries plus a
`DomainStates` predicate. What codegen buys is not inference — it is a *correct, maintained* class
that the author would otherwise hand-write, where the obvious hand-written version is silently wrong
(footguns 1 and 2). The 6 erased surfaces cannot be helped statically at all, and — see the
Recommendation — narrowing their *runtime* type without narrowing their declared type actively makes
them worse.

**A premise correction** [Direct]: the issue frames this around `native_value`. `native_value` is
never populated. HA's `SensorEntity.state_attributes` (`sensor/__init__.py:468-486`) emits only
`last_reset`; `capability_attributes` (`:376-386`) emits `state_class` or `options`. `native_value`
is an entity-side `@cached_property` (`:488-491`) that never reaches the state machine.
Hassette's `SensorAttributes.native_value` (`sensor.py:98`, with its duplicated `| None`) is a codegen
artifact from AST-scraping `_attr_*` declarations, and **no code in `src/`, `tests/`, `examples/`, or
`docs/` ever reads it**. The field users actually touch is `state.value`. Any design should target
`value` and should probably delete `native_value` from `SensorAttributes` while it's in there.

### Q5 — What breaks

> **`[CORRECTED v3]`** Revision 2 read the overwrite below as a bug. It is **the intended override
> mechanism** — how a user supplies a different definition for a domain. The mechanics recorded here
> are accurate and worth keeping; the "trap" framing is not. With Option G rejected, the recommended
> design registers nothing, so none of this is on the critical path. See Option G's rejection.

**The registration mechanism is where a naive implementation would go wrong, and the issue does not mention it.** [Direct — verified by running both branches]

`get_domain()` reads `get_annotations(cls)` — the class's *own* annotations, not inherited
(`base.py:197-218`). That creates a fork with no good side:

```
class TempA(SensorState): pass                      -> get_domain() raises NoDomainAnnotationError
                                                    -> suppressed -> never registered -> dispatch never fires
class TempB(SensorState): domain: Literal["sensor"] -> registers StateKey("sensor", None)
                                                    -> SensorState silently CLOBBERED
```

I confirmed the clobber at runtime: after defining a redeclaring subclass, `resolve(domain="sensor")`
returned the subclass and the catalog stayed at 55 entries — an overwrite, not an append. The
duplicate-domain guard at `conversion/validation.py:133-145` **cannot catch this**: identical keys
overwrite, so only one entry exists and the loop never sees a duplicate. Its warning text
("The first-registered class takes precedence") is also inaccurate for the device-class case, where
the domain-only entry always wins regardless of order.

The codegen template emits `domain: Literal["{{ domain }}"]` unconditionally
(`templates/state_model.py.j2:64-71`), so naive generation lands squarely on the clobbering branch.

**Resolution — `[CORRECTED v2]`, then superseded in v3.** The composite-key mechanism below is
verified and correct, but Option G is rejected (the overwrite it avoids is intentional) and the
recommended design re-declares no `domain` and registers no keys, so this fork never arises.
Revision 1 concluded: "generated subclasses must *not* re-declare
`domain`, and must be registered by an explicit `register_state_converter(...)` call." That was a
workaround aimed at the wrong layer, and it is what produced the critics' Finding 4
(`get_domain()` raises for such classes, so `self.states[NumericSensorState]` is unusable).

**The clobber exists only because `device_class` is not part of the key `__init_subclass__` derives.**
`__init_subclass__` calls `register_state_converter(cls, domain=cls.get_domain())` (`base.py:155-158`)
— one dimension of a two-dimensional key. Add a symmetric `get_device_class()` and the fork
disappears. Verified at runtime:

```
(a) TODAY: subclass redeclares domain -> current __init_subclass__ clobbers
    before: resolve(sensor) = SensorState  | size 55
    after : resolve(sensor) = TempClobber  | size 55        <- overwrite, not append

(b) PROPOSED: same class shape, composite-key derivation
    resolve(sensor)              = SensorState              <- survives
    resolve(sensor, temperature) = TempFixed
    get_domain()                 = sensor                   <- Finding 4 dissolved
    size: 56                                                <- append
```

So a generated subclass **can** safely re-declare `domain: Literal["sensor"]` (which the codegen
template already emits unconditionally, `templates/state_model.py.j2:64-71`) provided the derived key
carries its device class. This is written up as **Option G**.

Two further notes revision 1 missed:

- `StateRegistry.register()` (`state_registry.py:114-129`) is a **second public catalog writer** that
  already forwards `device_class` to `register_state_converter`. Any registration-semantics change has
  two entry points, not one.
- Registering with an explicit `device_class` does **not** require re-declaring `domain` — I verified
  a non-redeclaring subclass registers at `StateKey("sensor", "temperature")` without touching
  `StateKey("sensor", None)`. But such a class still fails `get_domain()`, so it works for
  `D.StateNew[...]` and not for `self.states[...]`. Composite-key derivation is what makes both work.

The remaining ADR-0003 point stands: `register_state_converter` lives in
`models/states/catalog.py`, the leaf module that exists precisely to break the models↔conversion
cycle, and `base.py` already imports it — so any of these registration shapes is legal from a
generated model module.

**Blast radius, quantified:**

| Surface | Count | Assessment |
|---|---|---|
| `isinstance` on state classes in `src/` | **0** | Free |
| `isinstance` on state classes in `tests/` | 22 (16 in `test_states.py`) | Only `test_app_test_harness.py:427` is at risk, and it passes if subclasses inherit `SensorState` |
| `STATE_REGISTRY` / catalog consumers | 114 refs / 40 files (9 in `src/`) | Mostly imports; `resolve()` call sites are 4 |
| `models/states/__all__` | 192 names today | Generated automatically by `generators/exports.py` AST scan — new classes export for free |
| Frontend / `openapi.json` | **0 hits** for `SensorState`, `BaseState`, `device_class` | Genuinely zero impact — qualifies for the `design-completeness.md` exception, state it explicitly in the design so the gate doesn't stall the PR |
| Tests touching states/conversion/registry | 239 tests / 14 files | ~10 new tests; `tests/unit/models/test_state_catalog.py` has only **2** tests and neither covers collision |

**Pydantic interactions:**

```python
# src/hassette/models/states/base.py:72
model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True, coerce_numbers_to_str=True, frozen=True)
```
- `coerce_numbers_to_str=True` is footgun 1 above, and makes `Field(discriminator=...)` unreliable —
  union member selection depends on non-matching members *failing*, and this config makes coercion
  permissive. Registry dispatch sidesteps it; a discriminated union does not.
- `extra="allow"` means a narrowed field never fails loudly — enforcement has to live in the codec's
  `value_type` path (`state_registry.py:258`), not in Pydantic field types.
- `frozen=True` means the device class must be read from the raw dict *before* construction.
- The codebase has **1** discriminated-union usage in all of `src/` (`web/models.py:332`), zero in
  `models/states/`, and `design/research/2026-05-01-event-state-models/research.md:151` explicitly
  declined them for state/event dispatch. Registry dispatch is the house pattern.

**Two public-API breaks the issue's ACs miss:**

1. **`StateKey` leaks to users.** `DomainStatesMapping.__iter__` / `keys()` / `items()`
   (`state_manager.py:403-417`, `state_manager.pyi:161-164`) yield `StateKey` objects. Adding N
   device-class keys changes the shape of user-visible iteration over `self.states` — 57+ extra
   `sensor` keys. Needs deduplication or an explicit `BREAKING CHANGE:` note.
2. **The documented override contract collides head-on.**
   `docs/pages/core-concepts/states/conversion.md:70-92` *teaches* users to override a built-in by
   subclassing with the same `Literal` domain, and the snippet
   (`snippets/state-registry/domain_override.py`) is exactly the clobbering shape. After this change,
   whether a user's `CustomSensorState` still wins over a generated `NumericSensorState` for a
   temperature sensor is decided by import order. **`[CORRECTED v3]`** This collision only exists if
   device-class keys are registered. With Option G rejected they are not, the documented override
   keeps working untouched, and no precedence rule is needed. Kept as the reason *not* to register.
   Note regardless: this framework's callers are user apps outside this repo — "no callers found"
   never means "no users."

Also stale after this change: `docs/pages/core-concepts/states/index.md:121` currently asserts
`states.SensorState has value: str | None, attributes.device_class: str | None` — the second half is
*already* wrong (`SensorAttributes.device_class` is `SensorDeviceClass | None`, `sensor.py:95`).

**One more inconsistency to design around** [Direct]: `DomainStates` does **not** call
`try_convert_state`. `_validate_or_return_from_cache` (`state_manager.py:96`) calls
`STATE_REGISTRY.coerce_and_construct(self._model, ...)` with the class fixed at construction. So
wiring device-class dispatch into `try_convert_state` alone makes `self.states.get("sensor.x")` return
a `NumericSensorState` while `self.states.sensor["x"]` returns a plain `SensorState` — two runtime
types for the same entity via two access paths. Fixing this means routing `DomainStates` through
dispatch too, which is safe *provided* every device-class class inherits `SensorState` (the declared
`StateT` stays true; only the runtime class narrows).

### Q6 — Scope and sequencing

**The scope ladder terminates at `sensor`. This is the most useful finding for sizing the work.** [Supported]

Ten domains carry a `device_class` field (`binary_sensor.py:41`, `button.py:16`, `cover.py:49`,
`event.py:28`, `humidifier.py:43`, `media_player.py:150`, `number.py:83`, `sensor.py:95`,
`switch.py:15`, `update.py:37`), plus a generic `str | None` on `AttributesBase` for all 55. But
**`sensor` is the only domain where the device class changes the value type.** `binary_sensor`'s 28
device classes are all `bool` — `BinarySensorEntity.state` is
`@final -> Literal["on", "off"] | None` (`binary_sensor/__init__.py:199-205`), and the enum members
carry only on/off semantics in comments. `number` is uniformly numeric. `cover`, `event`, `update`,
`switch`, `button`, `humidifier`, `media_player` all have uniform value types. HA has no
`DEVICE_CLASS_UNITS` / state-class analogue for any of them.

So the "sensor → sensor+binary_sensor → every domain with a device class enum" ladder collapses:
rungs 2 and 3 buy nothing. Price them at zero value, not at some cost.

> **`[CORRECTED v2]`** The rung numbering below was superseded by the C1/C2/C3 capability split in
> the Recommendation. Rungs 1 and 2 are not sequential stages of one change — C2 (accessors) and C3
> (dispatch) are independent of each other, and only C1 is a prerequisite for either. The scope
> analysis and the granularity counts below still stand.

The real ladder is about *granularity within `sensor`*:

| Rung | New public names | Static value type gained | Extra info | Effort |
|---|---|---|---|---|
| 0. Nothing structural | 0 | none | — | — |
| 1. Value-shape classes (4) | **4** | `float`/`str`/`ZonedDateTime`/`Date` | — | Medium |
| 2. + registry dispatch | 0 more | (runtime correctness on erased paths) | — | +Small |
| 3. Per-device-class classes | **57–61** | same as rung 1 | `device_class: Literal[...]`, unit `Literal` | Large |
| 4. Other domains | 0 useful | none | — | wasted |

**Rung 1+2 captures essentially all the type-system value.** Rung 3 adds 53+ classes whose `value`
type is identical to `NumericSensorState`'s; the only genuinely new information is the unit `Literal`,
which is a promise `extra="allow"` cannot keep for custom integrations.

**It lands incrementally.** A proving subset — wire dispatch, ship `NumericSensorState` +
`TimestampSensorState`, register only `temperature`/`humidity`/`timestamp` — exercises every mechanism
(registration without domain clobber, `try_convert_state` dispatch, `DomainStates` consistency, the
alias re-declaration, the fallback for unregistered device classes) with three registry entries. The
remaining 54 registrations are then a data change in one generated mapping.

---

## Feasibility Analysis

### What would need to change

Rows are tagged with the capability that needs them: **C1** (classes exist), **C2** (accessor
narrowing, Option E), **C3** (runtime dispatch, deferred), **G** (key derivation, Option G).

| Cap | Area | Files affected | Effort | Risk |
|---|---|---|---|---|
| C1 | The four narrowed classes | generated `sensor.py` | Low | Footguns 1-2: must re-declare `value` *and* the `AliasChoices` alias |
| C1 | Codegen: derive numeric set | `codegen/.../extractors/` (+1 extractor), `generators/states.py`, `templates/state_model.py.j2` | Medium | New generator surface; no override-file schema for per-device-class variants today |
| C1 | Codegen: manifest | `manifest.py:_path_matches_domains` | Low | Only breaks if new *files* are emitted; keep the classes in `sensor.py` and it is free |
| C2 | Four stub accessors | `state_manager.pyi` (169 hand-written lines, **no freshness check**) | Low | Four lines; no per-release regeneration since the type axis has 4 fixed members |
| C2 | `StateManager` properties | `state_manager.py` (real `@property`, shadows `__getattr__`) | Low | Reuses `_domain_states_for` cache (`:208-214`) |
| C2 | `DomainStates` membership predicate (port of HA's `_numeric_state_expected`) | `state_manager.py` — `__iter__`, `__len__`, `__contains__`, `__getitem__`; codegen extractor | **Medium-High** | `Mapping` invariant `len(m) == len(list(m))` is violated by the naive version (verified: 5 vs 2) |
| ~~G~~ | ~~key derivation / validator rewrite / overwrite guard~~ | — | — | **Cut in v3** — Option G rejected; the overwrite it avoided is the intended override mechanism |
| C3 | Conversion dispatch | `conversion/state_registry.py:95` | Low | One expression — but see the `cast()` inversion |
| C3 | `StateKey` iteration shape | `state_manager.py:403-417`, `.pyi:161-164` | Low | Public shape change (+61 keys) |
| F-lite | Legible conversion error | `conversion/state_registry.py:218-261` | Low | Purely additive |
| — | Docs | `states/index.md`, `states/conversion.md` (override rewrite), `states/custom-states.md`, `api/methods.md` (`cast` → `isinstance` if C3), `testing/factories.md` + snippets | Medium | The override-contract collision is the sharp edge |
| — | Tests | +~10-15; `test_state_catalog.py` needs collision coverage; a `Mapping`-invariant test for C2 | Medium | Global catalog means collisions are invisible per-test (`tests/conftest.py:225-227` snapshots it) |
| — | Frontend | **none** | — | Verified zero — qualifies for the `design-completeness.md` exception; state it in the design so the gate does not stall the PR |

### What already supports this

- The composite key and its fallback chain exist, work, and are validated as prior art matching HA's
  own entity registry (`design/research/2026-05-01-type-state-registries/research.md:147`).
- `register_state_converter` already accepts `device_class` and lives in the ADR-legal leaf module;
  `StateRegistry.register` (`state_registry.py:114-129`) already forwards it too.
- The raw attributes dict is in scope at the exact call site that needs it.
- **`state_manager.pyi` is hand-written with no generator** — which is what makes Option E's narrowed
  accessors a one-line-per-accessor change. Verified with pyright.
- `models/states/__init__.py` is generated by AST scan — new classes export with no generator change.
- `value_type` + `TypeRegistry` is a working per-class value-conversion mechanism; a narrowed class
  needs no validators (ADR-0003 stays intact).
- Zero production `isinstance` on state classes, so subclassing is `isinstance`-safe for free.
- `codegen` already AST-parses the exact `const.py` file that holds `NON_NUMERIC_DEVICE_CLASSES`.
- 11 of 17 access surfaces already accept a caller-supplied class, so C1's classes are immediately
  usable on all of them with no plumbing.
- Frontend impact is genuinely zero.

### What works against this

- `__init_subclass__` derives only the domain, so a subclass that re-declares `domain` consumes the
  user's override slot. **`[CORRECTED v3]`** Not a bug to fix (that overwrite is the override
  feature) — just a shape generated classes must avoid. The recommended design avoids it by not
  re-declaring `domain`.
- `coerce_numbers_to_str=True` + the `AliasChoices` alias make the obvious narrowing silently wrong.
- `DomainStates` is a `Mapping` whose `__len__` and `__iter__` disagree the moment filtering is
  introduced.
- `DomainStates` bypasses `try_convert_state`, so C3 would have to be wired twice or accept an
  inconsistency — and per critics' Finding 2, the obvious second wiring breaks
  `self.states[UnregisteredClass]` for every domain.
- The docs teach `cast` on the erased paths, which C3 would turn into a lie.
- The pinned HA version (2026.7.1) trails the local checkout (2026.8.0); generating against
  `~/source/core` will pull in `SensorDeviceClass.RADON` and trip `_warn_version_mismatch`.

> **`[CORRECTED v2]`** Revision 1 listed "`state_manager.pyi` is a fixed domain→class table — the most
> idiomatic access path can never narrow statically" here. That was wrong and has been removed; the
> stub's hand-written nature is now listed under *What already supports this*.

---

## Options Evaluated

### Option A — Four value-shape subclasses + device-class-keyed registry dispatch

> **`[CORRECTED v2]`** Revision 1 marked this *(recommended)*. Revision 2 recommends only its first
> half (the four classes, capability **C1**) and defers the registry-dispatch half (**C3**) — see the
> Recommendation. Option G supersedes this option's registration mechanism.

**How it works.** Codegen emits four classes into `sensor.py`, each subclassing `SensorState` and
re-declaring `value` with the narrowed annotation *and* the `AliasChoices` alias, plus a matching
`value_type` ClassVar: `NumericSensorState` (`int | float | Decimal | None`), `EnumSensorState`
(`str | None`), `TimestampSensorState` (`ZonedDateTime | None`), `DateSensorState` (`Date | None`).
None re-declares `domain`.

A new codegen extractor reads `NON_NUMERIC_DEVICE_CLASSES` from `homeassistant/components/sensor/const.py`
and emits a `device_class → class` mapping; the template emits explicit
`register_state_converter(cls, domain="sensor", device_class=dc)` calls at the module tail — 61
registrations onto 4 classes. `try_convert_state` passes
`data["attributes"].get("device_class")` to `resolve()`; `DomainStates` is routed through the same
dispatch so both access paths agree.

Authors get static narrowing via `D.StateNew[states.NumericSensorState]` and runtime narrowing on
`states.get()` / `api.get_state()`. Unknown and custom device classes fall through to `SensorState`
by the existing fallback.

**Pros**
- Adds **4** names to a 192-name `__all__`, honoring the minimal-public-API rule.
- Zero hand-maintained mapping — one `set` literal parsed from the file codegen already parses, plus
  4 hard-coded semantics. Cross-checkable against `DEVICE_CLASS_STATE_CLASSES` as a drift tripwire.
- Uses the pre-built seam exactly as `design/research/2026-05-01-type-state-registries` described it.
- Avoids the `domain`-clobber trap entirely by not re-declaring `domain`.
- Sidesteps `coerce_numbers_to_str`'s hostility to discriminated unions.
- Fixes the runtime-correctness half of the motivation, not just the type-checker half.
- Incrementally landable — three registry entries prove the whole mechanism.

**Cons**
- `NumericSensorState` is less discoverable than `TemperatureSensorState`; the DX/discoverability
  motivation is only partly served.
- No unit `Literal` narrowing.
- `self.states.sensor["x"]` still types as `SensorState` — unavoidable without #75.
- Requires resolving the documented override precedence and rewriting that docs section.
- Changes the shape of `self.states` iteration (extra `StateKey`s) unless deduplicated.

**Effort estimate:** Medium. The mechanism changes are small and localized (2 call sites, 1 template,
1 extractor). The weight is in the docs override-contract rewrite and the test coverage for collision
and precedence — areas with almost no coverage today.

**Dependencies:** none new. Codegen already has `jinja2`/`pyyaml`.

### Option B — Per-device-class subclasses (the issue as written)

**How it works.** Emit `TemperatureSensorState`, `HumiditySensorState`, … one per `SensorDeviceClass`
member (57–61), each locking `device_class: Literal[SensorDeviceClass.TEMPERATURE]`, narrowing `value`,
and optionally narrowing `attributes.unit_of_measurement` to a `Literal` derived from
`DEVICE_CLASS_UNITS`. Registration and dispatch are identical to Option A.

**Pros**
- Maximum discoverability — `TemperatureSensorState` is what an author would guess.
- `device_class: Literal[...]` gives real `isinstance`/exhaustiveness narrowing.
- Unit `Literal` narrowing is genuine added type information that Option A cannot provide.
- Matches the issue's ACs verbatim.

**Cons**
- **192 → ~253 exported names, +32% of the public state namespace**, against an explicit
  minimal-surface constraint. 53 of the new classes have an identical `value` type.
- 57+ extra `StateKey`s in user-visible `self.states` iteration.
- Unit `Literal`s are promises `extra="allow"` cannot keep — custom integrations report off-spec
  units, so the `Literal` will be a lie at runtime for some users.
- Grows with every HA release; each new device class is a new public name and a semver event.
- `DEVICE_CLASS_UNITS` covers only 57 of 62 device classes, so unit narrowing needs its own
  fallback rule (another decision, another docs paragraph).

**Effort estimate:** Large. Same mechanism work as Option A, plus a second derivation (units), a
naming/collision policy (`SensorDeviceClass.DATE` → `DateSensorState` collides with the `date` domain's
`DateState` naming space), a cap policy for which device classes get classes, and 57 more entries to
document.

**Dependencies:** none new.

### Option C — Generic parameterization: `SensorState[float]`

**How it works.** `BaseState` is already `BaseModel, Generic[StateValueT]` with
`value: StateValueT` (`base.py:69,105`). Make `SensorState` generic again —
`class SensorState(BaseState[StateValueT], Generic[StateValueT])` — with a PEP-696 TypeVar default of
`str | None` (via `typing_extensions.TypeVar` for 3.11 support) so bare `SensorState` keeps its
current meaning. Authors write `D.StateNew[states.SensorState[float]]`.

**Verified feasible.** I ran it: Pydantic builds a real concrete class on subscription, and the
conversion pipeline produces a `float`:

```
concrete is class: True   <class 'GSensorState[Union[float, NoneType]]'>
generic metadata:  {'origin': ..., 'args': (float | None,), 'parameters': ()}
value:             23.5   float
```

**Pros**
- **Zero new public names.** The strongest fit for the minimal-surface constraint.
- No registration problem at all — parameterized generics don't re-declare `domain`, so nothing
  clobbers.
- Composes naturally with `D.StateNew[...]` and `self.states[...]`.
- Smallest diff of any structural option.

**Cons**
- **No runtime dispatch and no discoverability.** The author must already know which device classes
  are numeric — precisely the knowledge the feature is supposed to encode. `states.get()` still
  returns a `str`-valued object.
- Correctness comes from Pydantic's lax `str → float` coercion at the field level, *not* from
  `value_type`. In my test, `value_type` was still `(str, NoneType)` and the right answer emerged
  anyway. That is fragile and cuts directly against ADR-0003's "the codec owns conversion" — it would
  need a `__pydantic_init_subclass__` hook deriving `value_type` from `__pydantic_generic_metadata__`.
- Bare `SensorState` semantics depend on a PEP-696 default working correctly in Pydantic *and* pyright
  at 3.11 — needs a proving spike before committing.
- Nothing stops `SensorState[list[int]]`.
- Codegen fidelity motivation is entirely unserved: HA's device-class knowledge is not encoded anywhere.

**Effort estimate:** Small-to-Medium for the mechanism, but with a real spike risk on the TypeVar
default. Serves roughly half the stated motivation.

**Dependencies:** `typing_extensions` (already a transitive dep via Pydantic; would become direct).

### Option D — Do less: no new types

**How it works.** Ship three cheap things instead: (1) delete the dead `native_value` field from
`SensorAttributes` and fix its duplicated `| None`; (2) add one narrow helper on `SensorState` —
`numeric_value: float | None` computed from `value` — with the device-class check inline; (3) write a
docs recipe showing the hand-written narrowing subclass, *including* the two footguns
(`value_type` alone is insufficient; the alias must be repeated).

**Pros**
- Smallest possible diff; removes a dead generated field.
- Fixes the day-to-day friction in the most common case (numeric sensors) with one property.
- No registry change, no codegen change, no public-name growth, no breaking change.
- Documents the footguns, which is the highest-value output of this research regardless of which
  option ships.

**Cons**
- `numeric_value` is a convenience API of exactly the kind this project has previously pushed back on;
  it needs its own justification.
- Does nothing for `timestamp`/`date`/`enum`.
- Leaves the codegen-fidelity and runtime-correctness motivations entirely unaddressed.
- Leaves `StateKey.device_class` dead — a permanently misleading piece of speculative generality.

**Effort estimate:** Small.

**Dependencies:** none.

---

### Option E — Four narrowed domain accessors  *(new in v2; simplified in v3; recommended)*

> **`[CORRECTED v3]`** Revision 2 proposed carrying the device class as an argument
> (`self.states.sensor.of(SensorDeviceClass.TEMPERATURE)`) with 61 stub overloads. **Rejected by the
> user**, on a principle worth recording: *this is a typing feature, and filtering to a specific
> device class is a data query.* The type axis has exactly four members, so four accessors cover it
> completely. Anyone who wants "all the temperature sensors" wants a different mechanism, not this one.

**How it works.** Option A's four value-shape classes, exposed as four accessors alongside
`self.states.sensor`:

```python
self.states.numeric_sensor      # DomainStates[NumericSensorState]    value: float | None
self.states.enum_sensor         # DomainStates[EnumSensorState]       value: str | None
self.states.timestamp_sensor    # DomainStates[TimestampSensorState]  value: ZonedDateTime | None
self.states.date_sensor         # DomainStates[DateSensorState]       value: Date | None
```

Three parts:

1. **Four stub entries** in `state_manager.pyi`. Verified sufficient for pyright (Q4).
2. **Four real properties on `StateManager`** — not `__getattr__` routing. `__getattr__` only fires
   when normal lookup fails, so a real `@property` shadows it cleanly and reuses `_domain_states_for()`'s
   per-class cache (`state_manager.py:208-214`). Routing through `__getattr__` would mean teaching it
   to parse accessor names into domain/device-class pairs — more machinery, worse errors.
3. **A membership predicate on `DomainStates`** — the real cost, and not optional.

**Nothing here touches the catalog, `register_state_converter`, `resolve()`, or `validate_registries`.**
The accessor names its class the way `self.states[X]` already does.

#### Why the predicate is not optional

I built a fake state proxy with five sensors (temperature, humidity, enum, timestamp, and one with no
device class) and drove a `NumericSensorState`-typed `DomainStates` with **no** predicate:

```
get_domain()                     -> sensor            (works: domain is redeclared)
len()                            -> 5                 <- WRONG
list(ds)                         -> 2 entries
ds['sensor.washer']              -> RAISED UnableToConvertStateError
ds['sensor.no_dc']               -> RAISED UnableToConvertStateError
ds.get('sensor.washer')          -> RAISED UnableToConvertStateError
```

Iteration "filters" only as a side effect of conversion failures being caught at
`state_manager.py:118-125` — and that path calls `LOGGER.error` per entity, so a 200-sensor install
would emit ~150 error lines per iteration. Meanwhile `len()` returns 5 while `list()` yields 2,
breaking the `Mapping` invariant `len(m) == len(list(m))`; `__contains__` is wrong for the same
reason. A correct implementation threads an explicit predicate through `__iter__`, `__len__`,
`__contains__`, and `__getitem__`.

Recommended behaviors, all falling out of the experiment: **iteration skips** non-members (at `debug`,
not `error` — a mismatch is expected for a filtered view, not exceptional); **direct access raises**
`UnableToConvertStateError`, since silently returning a `SensorState` from an accessor declared to
return `NumericSensorState` would be a type lie. Runtime device-class flips (Q2) land on the same
raise, which is the right answer.

#### The no-device-class question — revision 2 got this wrong

Revision 2 concluded: excluded, documented, `self.states.sensor` is the escape hatch. I surveyed the
user's live Home Assistant instance to check that, and it does not survive contact with real data.

**864 entities, 270 sensors. 124 of them — 46% — have no `device_class` at all.**

Classifying all 270 by metadata, then independently checking whether each value actually parses as a
number:

| Bucket | Count | Values that parse as numbers | Values that do not |
|---|---|---|---|
| `device_class` in the numeric set | 102 | 94 | **0** |
| `device_class` in `NON_NUMERIC_DEVICE_CLASSES` | 44 | 0 | 44 |
| No `device_class`, HA's predicate says numeric | 37 | **36** | **0** |
| No `device_class`, HA's predicate says non-numeric | 87 | 22 | 55 |

Revision 2's rule (`device_class` ∈ numeric set) would have **excluded all 124 no-device-class
sensors, of which 37 are genuinely numeric — 27% of the numeric population on this instance**,
including every container CPU/memory percentage, every mobile-app telemetry sensor, and a
`measurement`-class door-state sensor. `numeric_sensor` would have been missing a quarter of its
subject matter, silently.

**The fix is already written, in HA core.** `_numeric_state_expected`
(`homeassistant/components/sensor/__init__.py:126-145`) is HA's own answer to exactly this question:

```python
def _numeric_state_expected(device_class, state_class, native_unit_of_measurement,
                            suggested_display_precision) -> bool:
    if device_class in NON_NUMERIC_DEVICE_CLASSES:
        return False
    if (state_class is not None or native_unit_of_measurement is not None
            or suggested_display_precision is not None):
        return True
    return device_class is not None
```

Every input it needs is already a field on hassette's `SensorAttributes` (`sensor.py:92-102`):
`device_class`, `state_class`, `unit_of_measurement`. So the predicate is a direct port, not a new
invention — and it is derivable by codegen from the same file Q3 already reads.

On the live instance it scored **100% precision and ~86% recall**: 130 of 130 selected sensors really
were numeric-valued, and it missed 22 (Android volume levels — no device class, no state class, no
unit; indistinguishable from a string sensor by metadata alone).

**Recommendation: port HA's predicate.** Precision is what matters here — a false positive means a
declared `float | None` holding something that is not a float, which is the type lie this whole
feature exists to remove. False negatives are recoverable: the sensor is still reachable through
`self.states.sensor`, exactly as today. Value-parseability as a predicate is the wrong trade — it is
unstable (the same entity flips in and out of the view as its value changes, and `"unknown"` is
unclassifiable), and it would make `len()` a function of current values rather than of configuration.

Two implementation notes from the survey:

- `suggested_display_precision` **never appears in state attributes** (0 of 270), so that term of the
  predicate is inert at the state-machine boundary. The effective rule is
  `state_class is not None or unit_of_measurement is not None or device_class is not None`, minus the
  non-numeric set.
- HA's predicate takes `native_unit_of_measurement`; the state machine exposes `unit_of_measurement`.
  Substituting is correct — a sensor with a native unit always has a display unit.

#### A third dead codegen field

The same survey confirms `native_value` is never populated (0 of 270 sensors) — and turns up two more
in the same shape: **`native_unit_of_measurement` (0 of 270)** and **`suggested_display_precision`
(0 of 270)**. All three are entity-side `_attr_*` declarations that codegen scraped into
`SensorAttributes` and that never cross the state-machine boundary. Revision 1 caught one; there are
three.

**Pros**
- The only design where **declared type and runtime type agree exactly** on a narrowing path. No
  `cast()`, no `isinstance`, no lie.
- **Touches no catalog or registration code at all** — which is why every one of the critics' six
  findings is out of scope rather than mitigated.
- Fixes the one path Option A cannot touch, and the one an author meets first in autocomplete.
- Four accessors cover the type axis completely, so a new HA device class changes nothing: no new
  accessor, no stub regeneration, no public-name growth.
- Stub edit is trivial and verified with pyright.
- The predicate is a direct port of HA's own, mechanically derivable, measured at 100% precision on a
  real 270-sensor instance.

**Cons**
- Introduces a *view* concept: the same entity appears under `self.states.sensor` and
  `self.states.numeric_sensor` with different value types. Honest, but new.
- The `DomainStates` predicate touches four methods of a `Mapping` implementation, including fixing
  `__len__`/`__contains__` to agree with `__iter__`. This is the single largest code change in any
  option here.
- ~86% recall means some genuinely numeric sensors stay out of the view. Recoverable via
  `self.states.sensor`, but it must be documented or it reads as a bug.
- Four accessor names is four more public names, against the minimal-surface constraint. They are
  cheap names, but they are names.

**Effort estimate:** Medium. Stub and property work is trivial; the `DomainStates` predicate is the
weight, plus tests for the `Mapping` invariants the naive version violates.

**Dependencies:** Option A's classes. No catalog changes.

---

### Option F — Device-class-aware DI validation  *(new in v2)*

**How it works.** Teach `convert_state_dict_to_model` (`state_registry.py:218-261`) to compare the
annotated class against the entity's actual `(domain, device_class)` and raise a legible error on
mismatch, instead of letting Pydantic produce `3 validation errors for NumericSensorState /
state.int / state.float / state.decimal`. Two sub-variants:

- **F-lite (error legibility only).** Wrap the `model_validate` failure in a
  `UnableToConvertStateError` that names the entity, its real device class, and the annotated class.
  No registry consultation needed — the raw dict already has everything. Purely additive.
- **F-full (semantic validation).** Consult `resolve(domain, device_class)` and raise when the
  annotated class is incompatible. This catches the silent looser-annotation direction
  (`D.StateNew[EnumSensorState]` on a temperature sensor returning `'23.5'`), which F-lite does not.

**Pros**
- F-lite turns the single worst error message in the narrowing story into an actionable one, for very
  little code, and is useful whether or not any other option ships.
- F-full is the only option that addresses the genuinely silent failure direction.
- Directly serves the "runtime correctness" motivation without touching any declared type.

**Cons**
- F-full requires the device-class registrations to exist, so it inherits Option G's prerequisites —
  it is not independent.
- F-full makes DI stricter, which is a breaking change for anyone deliberately annotating a broad
  class (`D.StateNew[BaseState]` on a sensor is currently fine and would need an explicit exemption).
- Raising where the framework currently returns something is a behavior change on a hot path.

**Effort estimate:** Small for F-lite, Medium for F-full.

**Dependencies:** F-lite none; F-full depends on Option G.

---

### Option G — Device-class-aware key derivation  *(new in v2; **REJECTED in v3**)*

> **`[CORRECTED v3]`** Revision 2 recommended shipping this independently of #717, calling the catalog
> clobber "a bug fix disguised as a feature." **That premise was wrong.** The user states plainly:
> overwriting a domain's registered class is the *intended* override mechanism — it is how a user
> supplies a different definition for a domain. `catalog.py:39-40`'s bare
> `_STATE_CATALOG[key] = state_class` is doing its job, and the pattern documented at
> `conversion.md:70-92` is the feature working as designed, not a trap.

**What it was.** Add a `get_device_class()` classmethod symmetric to `get_domain()` and have
`__init_subclass__` derive the full `StateKey`, so generated subclasses could re-declare
`domain: Literal["sensor"]` without replacing `SensorState`.

**Why it is rejected.**

1. **It fixes something that is not broken.** Its entire justification was preventing an overwrite the
   framework deliberately allows. Adding an overwrite guard at `register_state_converter` would fight
   the documented override design — so the guard is cut, and with it the half of critics' Finding 3
   that proposed it.
2. **It requires the validator rewrite, which was self-inflicted.** The ~60 spurious "Duplicate domain
   'sensor'" warnings that critics' Finding 3 predicted only arise *because* Option G registers ~61
   device-class keys. No registrations, no false positives, no rewrite. The other half of Finding 3
   dissolves too.
3. **61 keys is the wrong shape for 4 types.** This is the deeper objection, and it generalizes.
   Registering 61 `StateKey`s that resolve to 4 classes encodes a data relationship as registry
   structure. The 61→4 mapping is a lookup table, not a set of keys. Expressing it as keys inflates
   the catalog 2×, leaks 61 entries into user-visible `self.states` iteration
   (`state_manager.py:403-417`), and forces the resolver to carry a second dimension that only one
   domain will ever use.

**What survives it.** Two verified findings from the revision-2 investigation stand on their own and
should be recorded even though the option is dead:

- Composite-key derivation *does* work — verified at runtime, `resolve(sensor)` survives while
  `resolve(sensor, temperature)` resolves to the subclass, and `get_domain()` then works. The
  mechanism is sound; it is simply not needed.
- `StateRegistry.register()` (`state_registry.py:114-129`) is a **second public catalog writer** that
  already forwards `device_class`. Any future registration change has two entry points, not one.

**If runtime dispatch (C3) is ever revisited**, price it as a **two-step lookup** — device class →
value shape → class, with one catalog entry per domain and the 61→4 mapping held as a plain dict in
the sensor conversion path. Do **not** re-propose 61 `StateKey`s. This is close to what critics'
Finding 6 argued for (a scoped, private lookup), reached by a different route: not to hide dispatch
from the validator, but because the relationship is data and belongs in a data structure.

---

## Concerns

### Technical risks

- **`[CORRECTED v3]` — the clobber is not a risk; it is the override feature.**
  `register_state_converter`'s bare dict assignment (`catalog.py:39-40`) is how a user replaces a
  domain's class, exactly as documented at `conversion.md:70-92`. Revision 1 treated it as a
  constraint to design around; revision 2 escalated it to "a live bug." Both were wrong. The real
  constraint is narrower: **a generated subclass must not re-declare `domain`**, or it would consume
  the user's override slot. The recommended design does not re-declare `domain` and registers
  nothing, so this concern does not apply to it at all.
- **The `cast()` inversion.** Narrowing the *runtime* type on the six `BaseState`-declared surfaces
  while their declared type stays `BaseState` makes the `cast("SensorState", ...)` the docs teach
  (`api/methods.md:41-43`) actively wrong rather than merely imprecise. Identified in v2; see the
  Recommendation. It is the reason runtime dispatch (C3) is deferred.
- **`DomainStates` is a `Mapping` whose invariants break under naive filtering.** Verified: a
  device-class-scoped `DomainStates` with no explicit predicate returns `len() == 5` while
  `list()` yields 2, because `__len__` delegates to `num_domain_states(self._domain)`
  (`state_manager.py:127-129`) while `__iter__` filters by catching conversion failures
  (`:118-125`). Any Option E implementation must thread the predicate through `__iter__`, `__len__`,
  `__contains__`, and `__getitem__`.
- **Accidental filtering is loud, not silent.** `__iter__`'s skip path calls `LOGGER.error` per
  entity. A 200-sensor install iterating a numeric-only view would emit ~150 error lines. Any filtered
  view needs a real predicate *and* a log-level decision (recommend `debug` — a mismatch is expected
  for a filtered view, not exceptional).
- **`device_class` is user-mutable at runtime** (`entity_registry.py:450`). Any design binding a
  device-class-scoped class to an entity for longer than one event is wrong. Verified behavior after a
  flip: `ds["sensor.washer"]` raises `UnableToConvertStateError`. `D.TypedStateChangeEvent[X]` is the
  sharpest case — it applies one `X` to both `old_state` and `new_state`
  (`annotation_converter.py:180-181`), so an event straddling a device-class change has no single
  correct annotation.
- **Two runtime types for one entity.** `DomainStates` bypasses `try_convert_state`
  (`state_manager.py:96`). If C3 ships, wiring dispatch in one place and not the other is a real
  correctness hazard. Critics' Finding 2 adds the sharper version: routing
  `_validate_or_return_from_cache` through `resolve()` would silently break the documented
  `self.states[UnregisteredClass]` contract for *every* domain. Moot under the C1+C2 recommendation,
  which never touches `_validate_or_return_from_cache`'s model selection.
- **HA version skew**: local checkout is 2026.8.0, pin is 2026.7.1. Regenerating against `~/source/core`
  pulls in `RADON` and mixes an unrelated bump into the PR.

### Complexity risks

- Option E introduces a *view* concept — the same entity visible under two accessors with two value
  types. Honest, but a new idea for users to hold.
- `state_manager.pyi` is 169 hand-written lines with no generator and no freshness check. **`[CORRECTED v3]`**
  Option E now adds four lines rather than 61 overloads, so it barely moves this pre-existing risk.
- **`[CORRECTED v3]`** Two bullets were removed here — the catalog's second key dimension and the
  override-precedence question. Both were consequences of Option G, which is rejected.
- Option B specifically: a naming policy, a cap policy, and a unit-fallback policy are three new
  decisions that each need documenting.

### Maintenance risks

- Option B obligates maintenance of ~60 public class names that track HA releases. Every new
  `SensorDeviceClass` member becomes a public API addition.
- Unit `Literal`s (Option B) are the kind of narrowing that generates bug reports from users of custom
  integrations. `extra="allow"` means they won't crash — they'll just be wrong.
- Option C obligates a `value_type` derivation hook whose correctness depends on Pydantic generic
  internals (`__pydantic_generic_metadata__`), a private-ish surface.
- **`[CORRECTED v3]`** Revision 2 listed "Option E's 61 stub overloads must track `SensorDeviceClass`."
  Gone with the `.of()` shape. The four-accessor form has **no** per-release maintenance: the type axis
  has four fixed members, so a new HA device class adds no accessor, no overload, and no class. The
  only thing that tracks HA releases is the numeric-predicate port, which codegen derives.

---

## Open Questions

> **`[CORRECTED v3]`** Three questions were removed here: the accessor shape (settled — four plain
> accessors, per correction 2), the override-precedence rule, and the overwrite guard. The latter two
> only existed because Option G registered device-class keys; with G rejected, nothing registers a
> second key and neither question arises.

- [ ] **`numeric_sensor` membership recall.** HA's `_numeric_state_expected` measured 100% precision
      and ~86% recall on a live 270-sensor instance; the 22 misses are metadata-less sensors (Android
      volume levels). Is 86% the right trade, or should the view be looser? I recommend the predicate
      as-is — precision is what protects the declared type — but the misses need documenting.
- [ ] **Should `self.states` iteration expose device-class `StateKey`s at all?** Deduplicating to
      domain-only keys preserves today's shape but makes the mapping lossy. Only bites if C3 ships.
- [ ] **Sensors with no device class**: confirmed excluded from a numeric view and raising on direct
      access. Template sensors commonly report numbers with no device class, so this may surprise
      people. Is the `self.states.sensor` escape hatch a sufficient answer?
- [ ] **`D.TypedStateChangeEvent[X]` across a device-class flip** — skip, raise, or fall back to
      `SensorState` for the mismatched half? No behavior exists to preserve; this is a fresh decision.
- [ ] **Does the PEP-696 TypeVar default (Option C) actually hold** across Pydantic + pyright at 3.11?
      Needs a 20-line spike; I verified the parameterized-generic mechanism but not the default.
- [ ] **Unknown — searched and not found**: I searched `git log --all`, merged PRs, `design/adrs/`,
      `design/audits/`, `design/research/`, and `design/specs/` for a rationale behind adding
      `device_class` to the catalog key. PR #197's body is about deferring conversion and never
      mentions it. There is no ADR, no issue, and no discussion. The most likely reading is speculative
      generality added in passing, but the evidence is absence-of-evidence, so treat it as unexplained
      rather than confirmed-accidental.

---

## Recommendation

> **`[CORRECTED v3]`** Revision 2 recommended C1 + C2 + Option G, with C3 deferred. Revision 3 cuts
> Option G (the clobber it fixed is intended behavior) and simplifies C2 to four plain accessors.
> **The recommendation is now C1 + C2, and it touches no catalog or registration code whatsoever.**

### The capability split still holds; one capability dropped out

| | Capability | Needs | Serves | Verdict |
|---|---|---|---|---|
| **C1** | The narrowed classes exist | 4 classes in generated `sensor.py` | Group 1's 11 author-names-the-class surfaces | **Ship** |
| **C2** | Static narrowing on the accessor path | C1 + 4 stub entries + 4 properties + a `DomainStates` predicate (Option E) | Group 3 | **Ship** |
| **C3** | Runtime dispatch on the erased paths | C1 + a device-class→value-shape lookup | Group 2's 6 surfaces | **Defer** |

C1 is a prerequisite for C2. C3 is independent of both. Critics' Finding 1 argued the work bundled
two moves that should be separated — correct instinct, and with Option G gone the separation is
cleaner than either revision proposed: **C1 + C2 is entirely additive.** No existing behavior changes,
no registration semantics change, no validator change, no `StateKey` shape change.

### The `cast()` problem — still why C3 is deferred

C3 narrows the *runtime* type on six surfaces whose *declared* type is `BaseState`. Because they are
erased, an author must already do something to use the result, and the docs tell them what:
`docs/pages/core-concepts/api/methods.md:41-43` teaches `cast`.

Today that cast is honest — `cast("SensorState", api.get_state(...))` yields an object whose `value`
really is a `str`. **After C3 it becomes a lie**: the declared `str` would sit on a runtime object
whose `value` is a `float`. No error, no narrowing, wrong type.

**Does correction 1's two-step-lookup reframing change this? No.** The `cast()` problem is about the
gap between declared and runtime types on the erased paths. How dispatch is implemented internally —
61 `StateKey`s, a private dict, or a two-step lookup — is invisible to that gap. The two-step lookup
is a better *implementation* of C3; it is not an argument for shipping it. C3 still needs a docs
migration from `cast` to `isinstance` to land safely, and that migration has to ship with it.

C3's benefit is not zero — `api.get_states()` silently dropping entities that fail conversion
(`api.py:433`) is a real bug. But it is a separable one, and the cast migration is the gate.

### Ship C1 + C2

**1. The four narrowed classes (C1).** `NumericSensorState`, `EnumSensorState`,
`TimestampSensorState`, `DateSensorState` — four names against a 192-name `__all__`, derived
mechanically from `NON_NUMERIC_DEVICE_CLASSES` (Q3). Type `NumericSensorState.value` as
`float | None`, **not** `int | float | Decimal | None`: the pyright probe in Q4 showed the full union
makes `Decimal + float` a type error and forces a guard into every arithmetic expression.

**2. The four narrowed accessors (C2, Option E).** `self.states.numeric_sensor`,
`.enum_sensor`, `.timestamp_sensor`, `.date_sensor`. Four stub entries, four properties, and a
membership predicate ported from HA's `_numeric_state_expected` — **not** the naive
`device_class ∈ numeric set` rule, which the live-instance survey showed would silently drop 27% of
numeric sensors. The `DomainStates` predicate is the real work and must fix `__len__`/`__contains__`
to agree with `__iter__`; the naive version violates the `Mapping` invariant (verified: 5 vs 2).

**3. Option F-lite — still stands on its own.** Wrapping the raw Pydantic `ValidationError` in an
error naming the entity, its real device class, and the annotated class. Re-checked against
correction 1: F-lite was never dependent on device-class registration — `convert_state_dict_to_model`
(`state_registry.py:218-261`) already holds the full raw dict, so `attributes["device_class"]` is in
scope with no registry involvement. It survives Option G's removal unchanged. F-*full* (semantic
validation) does not, since it needed `resolve()` to have something to resolve — drop it with C3.

**4. Delete the three dead codegen fields.** `native_value`, `native_unit_of_measurement`, and
`suggested_display_precision` on `SensorAttributes` are populated in 0 of 270 real sensors and
described by HA core as entity-side properties that never reach the state machine. Also fix the
duplicated `| None` at `sensor.py:98`. Independent of everything else here.

**Explicitly rejected**, with reasons:

- **Option G (composite-key derivation)** — fixes an overwrite that is the intended override
  mechanism, and encodes a 61→4 data relationship as registry keys.
- **Option B (57-61 per-device-class classes)** — 53 would carry an identical `value` type; the only
  new information is a unit `Literal` that `extra="allow"` cannot enforce.
- **Option C (generic `SensorState[float]`)** — verified feasible and name-free, but serves neither
  discoverability nor codegen fidelity, and its correctness rests on Pydantic's lax coercion rather
  than `value_type`, cutting against ADR-0003.
- **`sensor.of(device_class)` and 61 stub overloads** — a data query wearing a typing feature's
  clothes.
- **Other domains** — `sensor` is the only domain where device class varies the value type (Q6).
  `binary_sensor.state` is `@final -> Literal["on","off"] | None`. Zero value, not "later."
- **`self.states.sensor["x"]` narrowing per entity ID** — that is issue #75.
- **Entity wrappers (`TemperatureSensor`)** — blocked on #1449; `models/entities/` has no `sensor.py`.

### Granularity: four, on both axes

> **`[CORRECTED v3]`** Revision 2 answered "4 classes, but carry the device class as an argument."
> The second half is withdrawn.

**Four classes and four accessors.** The type axis has exactly four members — numeric, enum,
timestamp, date — and four accessors cover it completely. Fifty-seven numeric device classes share one
value type, so per-device-class names would spend public API on a distinction the type system cannot
see.

The device-class axis is simply **out of scope**. "Give me the temperature sensors" is a data query.
It may be worth building, but it is not a typing feature and should not be solved by one — and
critically, it does not grow with HA: a new numeric device class in the next release adds no accessor,
no overload, no class, and no stub edit. That is the property the four-accessor shape buys.

### On evidence and this repo's own code

> **`[CORRECTED v3]`** Revision 2 argued C2's benefit was "unevidenced by observed usage" because
> every `float(str(...))` site is a DI handler in `examples/` or `docs/`. **That reasoning was
> invalid.** Hassette is a framework; its callers are user applications outside this repository.
> Friction lives in user handlers and user automations this repo never exercises. Absence of a pattern
> in `examples/` is evidence about what the examples demonstrate — nothing about what app authors do.

Both access paths are assumed to have real users, and neither is ranked above the other on
repo-internal evidence. Three further instances of the same reasoning shape were found and corrected
in Q4 and the Recommendation. Counts over *internal* surfaces — the blast-radius tables,
`isinstance` call sites in `src/`, `resolve()` call sites — remain valid, because those measure what
this repo must change, not what users need. One caveat now attaches to the `isinstance` count: zero
production `isinstance` checks on state classes in `src/` means *internal* code is safe under
subclassing; it says nothing about app authors who may branch on `isinstance(s, SensorState)` in their
own handlers. Since the four classes inherit `SensorState`, they stay compatible either way.

### Suggested next steps

1. Decide the one remaining open question that blocks a design doc: the recall trade-off on
   `numeric_sensor` membership (port HA's predicate at ~86% recall / 100% precision, as recommended, or
   something looser). Route through `/mine-define`.
2. Ship C1 + Option F-lite in one PR: four generated classes, the legible conversion error, and the
   three dead-field deletions. Independently verifiable, no behavior change to existing paths.
3. Ship C2 in a second PR. Add a `Mapping`-invariant test (`len(m) == len(list(m))`) for the filtered
   `DomainStates` — the naive implementation fails it, so that test is the pin.
4. Port `_numeric_state_expected` in codegen alongside the `NON_NUMERIC_DEVICE_CLASSES` extraction, so
   the predicate tracks HA releases rather than drifting. Cross-check against
   `DEVICE_CLASS_STATE_CLASSES` (62 keys) as a drift tripwire.
5. Correct the stale claim at `docs/pages/core-concepts/states/index.md:121`
   (`attributes.device_class` is `SensorDeviceClass | None`, not `str | None`) while touching the
   states docs.
6. Noted, not recommended: `state_manager.pyi` is 169 hand-written lines with no freshness check. With
   the 61 overloads gone, this feature adds four lines and does not materially change that risk. It is
   a pre-existing gap worth its own issue, not part of this work.

---

## Sources

- [Pydantic — Unions and discriminated unions](https://pydantic.dev/docs/validation/latest/concepts/unions/)
- [Discriminated Union based on nested field — pydantic/pydantic Discussion #11174](https://github.com/pydantic/pydantic/discussions/11174)
- [Home Assistant core — `homeassistant/components/sensor/__init__.py`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/sensor/__init__.py)
- [Home Assistant developer docs — Sensor entity](https://developers.home-assistant.io/docs/core/entity/sensor/)
- [basedpyright — Type concepts advanced (narrowing limitations)](https://docs.basedpyright.com/v1.23.1/usage/type-concepts-advanced/)
- [`isinstance(instance, SubClass)` loses type instead of narrowing — microsoft/pyright #24](https://github.com/Microsoft/pyright/issues/24)

Primary evidence for every claim above is the local codebase at
`/home/jessica/source/hassette/.claude/worktrees/717` and the HA core checkout at
`/home/jessica/source/core` (2026.8.0), cited inline by `file:line`.
