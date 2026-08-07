# Design: Device-class-specific sensor state subtypes

**Date:** 2026-08-06
**Status:** approved
**Scope-mode:** hold
**Research:** `design/research/2026-08-06-sensor-device-class-subtypes/research.md` (revision 3)

## Problem

`SensorState.value` is typed `str | None`, because `SensorState` extends `StringBaseState`
(`src/hassette/models/states/sensor.py:112`). Home Assistant sensors, however, carry four genuinely
different value shapes — numeric, enum, timestamp, and date — and the framework flattens all four
into a string.

App authors pay for that flattening on every numeric sensor read. The pattern appears throughout the
repo's own examples (`examples/climate_controller.py:90` and again verbatim at `:114`,
`docs/pages/recipes/snippets/debounce_sensor.py:26`, `examples/demo_stimulator.py:143`), and hassette
is a framework whose real callers are user automations outside this repository — so the observable
sites here are a sample of the problem, not its extent.

Two consequences follow. The type checker cannot help: `state.value + 1` is an error the author must
work around rather than a correctness check the tooling performs. And there is no way to ask the
framework for "the sensors whose values are numbers" — every sensor is a string sensor as far as the
type system is concerned.

## Goals

- `NumericSensorState.value` is `float | None`, and arithmetic on it type-checks without a cast.
- The four value shapes are reachable both by annotation (`D.StateNew[NumericSensorState]`) and by
  accessor (`self.states.numeric_sensor`).
- Membership in a narrowed accessor is decided by the same rule Home Assistant itself uses, plus
  successful conversion to the narrowed class, so the declared type and the runtime type agree.
- The rule's *data* stays correct across Home Assistant releases without hand maintenance.
- Registration *behavior* is unchanged — the four classes never register, `resolve(domain=...)`
  semantics and the domain-override mechanism work exactly as today, and `validate_registries`
  needs no edits — but the registration *API surface* does change: FR#18 deletes the never-used
  `device_class` dimension, a breaking (if inert) signature change on `StateRegistry.register`.

## Non-Goals

- **Runtime dispatch on the erased paths.** `states.get()`, `api.get_state()`, and `api.get_states()`
  continue to return `SensorState`. Deferred deliberately — see Alternatives Considered.
- **Device-class-keyed catalog registration.** Not needed by anything in this design — and the
  never-used `device_class` dimension the catalog already carries is *removed* by it (FR#18), so
  the capability doesn't linger as dead code. If runtime dispatch (C3) is ever built, it uses a
  two-step lookup (device class → shape → class) held as a plain dict, not registry keys.
- **Filtering by a specific device class** (`temperature` vs `humidity`). That is a data query, not a
  typing feature; it is out of scope for this change.
- **Per-device-class classes** (`TemperatureSensorState` and the rest of the ~62). Rejected — see
  Alternatives Considered.
- **Other domains.** `sensor` is the only domain whose device class varies the value type;
  `binary_sensor.state` is `@final -> Literal["on", "off"] | None` in HA core.
- **Bringing `state_manager.pyi` under codegen.** A real pre-existing gap, filed separately.

## User Scenarios

### App author: writes a hassette automation

- **Goal:** read a numeric sensor and do arithmetic on it
- **Context:** inside a bus handler or an `on_initialize` body

#### Reading one sensor by annotation

1. **Annotate the handler parameter `D.StateNew[NumericSensorState]`**
   - Sees: autocomplete offering the four narrowed classes alongside `SensorState`
   - Decides: which value shape this entity has
   - Then: `state.value` is `float | None`; `state.value + 1` type-checks after a `None` guard

2. **Point the annotation at the wrong shape** (an `enum` entity annotated as numeric)
   - Sees: an error naming the entity, its actual device class, and the annotated class
   - Then: the handler raises rather than silently coercing

#### Iterating the numeric sensors

1. **Access `self.states.numeric_sensor`**
   - Sees: a `DomainStates[NumericSensorState]` containing only sensors whose values are numbers
   - Then: `len()`, `in`, and iteration all agree on the same membership

2. **Look up a sensor that is not numeric**
   - Sees: `[]` raises `EntityNotInViewError` naming the entity, its device class, and the
     accessor's shape; `.get()` returns `None` (it is a `KeyError` subclass)
   - Decides: fall back to `self.states.sensor`, which still contains every sensor

## Functional Requirements

- **FR#1** Four state classes exist — `NumericSensorState`, `EnumSensorState`,
  `TimestampSensorState`, `DateSensorState` — each a subclass of `SensorState`.
- **FR#2** `NumericSensorState.value` is `float | None`.
- **FR#3** `EnumSensorState.value` is `str | None`; `TimestampSensorState.value` is
  `ZonedDateTime | None`; `DateSensorState.value` is `Date | None`.
- **FR#4** None of the four classes registers itself in the state catalog; `resolve(domain="sensor")`
  continues to return `SensorState`.
- **FR#5** `StateManager` exposes `numeric_sensor`, `enum_sensor`, `timestamp_sensor`, and
  `date_sensor` properties, each returning a `DomainStates` parameterized to the matching class.
- **FR#6** Each narrowed accessor contains exactly the sensors whose value shape matches its class
  **and** whose current state successfully converts to it. Membership requires both.
- **FR#7** `len()`, `__contains__`, and iteration over a narrowed accessor agree exactly on
  membership — the `Mapping` invariant `len(m) == len(list(m))` holds unconditionally, including for
  sensors whose metadata classifies as numeric but whose value fails conversion.
- **FR#8** A single shape classifier maps an entity's attributes to one of the four shapes or to
  "unknown", and both accessor membership and DI shape validation read from it.
- **FR#9** The classifier's numeric branch is decided by a port of Home Assistant's
  `_numeric_state_expected`, not by device-class-set membership alone.
- **FR#10** Sensors with device class `uptime` classify as the timestamp shape; there is no separate
  uptime class.
- **FR#11** The non-numeric device-class set is generated from Home Assistant core rather than
  hand-maintained.
- **FR#12** Direct lookup of a non-member entity through a narrowed accessor raises a new exception
  that subclasses **both `KeyError` and the existing state-error hierarchy** (working name
  `EntityNotInViewError`), whose message names the entity, its actual device class, and the
  accessor's expected shape. Because it subclasses `KeyError`, `Mapping.get()` returns `None` for
  non-members — consistent with `__contains__` returning `False`. Iteration skips non-members.
- **FR#13** Iteration skips are logged at `debug`, not `error`.
- **FR#14** A failed conversion during dependency injection raises an error naming the entity, its
  actual device class, and the annotated class.
- **FR#15** Dependency injection raises when the annotated state class's value shape does not match
  the entity's actual value shape, even when coercion would otherwise succeed. An entity that
  classifies as "unknown" does not raise.
- **FR#16** `SensorAttributes` no longer declares `native_value`, `native_unit_of_measurement`, or
  `suggested_display_precision`. This is a formal API removal and ships with a `BREAKING CHANGE:`
  footer (see Delivery Sequencing).
- **FR#17** Codegen snapshots the source text of HA's `_numeric_state_expected` and the freshness
  check fails when the upstream source no longer matches the committed snapshot, so an upstream
  logic change forces a human re-verification of the port at version-bump time.
- **FR#18** The catalog's dead `device_class` dimension is removed: the `device_class` field on
  `StateKey`, the exact→domain-only fallback chain in `resolve()`, and the `device_class` parameter
  on both public writers (`register_state_converter` and `StateRegistry.register`). The catalog
  becomes what it has always behaved as — one entry per domain. **`StateKey` survives as a
  one-field frozen dataclass** (`domain` only): the public name, both `__all__` exports, and the
  type yielded by `self.states` iteration are unchanged, so FR#18 removes the dead dimension
  without introducing a user-visible break beyond the writer signatures.

## Edge Cases

- **Sensor with no `device_class`.** Roughly 46% of sensors on a real instance. The ported predicate
  falls back to `state_class` and `unit_of_measurement`, so genuinely numeric ones are still
  included. A naive device-class-only rule would drop about 27% of the numeric population.
- **Sensor with no metadata at all** — no device class, no state class, no unit. Excluded from every
  narrowed accessor. Reachable through `self.states.sensor`. This is the accepted recall gap.
- **Unknown or custom `device_class` string.** A custom string *does* reach state attributes — the
  entity registry writes `device_class or original_device_class` into attrs unvalidated
  (`~/source/core/homeassistant/helpers/entity_registry.py:450-452`). What HA does is normalize at
  the point of use: its numeric logic runs the value through
  `try_parse_enum(SensorDeviceClass, ...)` (`sensor/__init__.py:609`, also `:343`), so an unknown
  string behaves as `None`. The ported classifier must include the same normalization step (see
  Architecture) — without it, a custom device class would satisfy the numeric branch's
  `device_class is not None` fallback and misclassify as numeric, the exact false positive this
  feature exists to prevent. After normalization these sensors fall to the no-device-class path
  above. (Separately and pre-existing: `SensorAttributes.device_class` is typed
  `SensorDeviceClass | None`, so *model conversion* of such a sensor already fails today; that
  behavior is unchanged by this design.)
- **`device_class` changes at runtime.** A user can edit it in the HA UI; the next `state_changed`
  event carries different attributes. Membership is recomputed per access, never cached across the
  change. Direct lookup after a flip raises `EntityNotInViewError`; iteration stops yielding the
  entity.
- **`state` is `unknown` or `unavailable`.** Normalized to `None` before coercion by existing
  preprocessing (`conversion/state_registry.py:249-255`); `value` is `None` and the entity remains a
  member.
- **Empty accessor.** No sensors match — `len()` is 0 and `bool()` is `False`, matching existing
  `DomainStates` behavior.
- **A numeric sensor whose state does not parse as a number.** The predicate says it should be
  numeric but coercion fails. **Excluded from membership everywhere** — iteration skips it at
  `debug`, `len()` does not count it, `__contains__` is `False`, and direct lookup raises
  `EntityNotInViewError` (the `Mapping` invariant holds; FR#7). This makes `len()` and `in`
  value-dependent for exactly this edge — a deliberate trade, bounded to misbehaving integrations,
  since `unknown`/`unavailable` normalize to `None` and stay members. The alternative (membership by
  predicate alone) breaks either the `Mapping` invariant or aborts `items()` loops mid-iteration on
  one flaky sensor.
- **`D.TypedStateChangeEvent[NumericSensorState]` across a device-class flip.** The event's
  `old_state` and `new_state` are converted to the same class; when an event straddles a
  device-class change, the mismatched half fails shape validation (FR#15) and the handler raises.
  There is no fallback to `SensorState` for one half — a half-narrowed event would be a type lie.
- **A narrowed annotation pointed at the wrong shape** (`D.StateNew[EnumSensorState]` on a
  temperature sensor). Coercion would succeed — a float becomes a string — so this is caught by shape
  validation rather than by conversion failure. Raises.
- **A plain `SensorState` annotation on any sensor.** Makes no shape claim, so shape validation does
  not apply. Unchanged from today.
- **A narrowed annotation on a sensor with no metadata**, where the classifier returns "unknown".
  Treated as unknown rather than as a mismatch — no shape claim can be contradicted, so this does not
  raise.
- **`self.states[NumericSensorState]`** — generic indexing raises `NoDomainAnnotationError`, because
  `StateManager.__getitem__` (`state_manager.py:266-285`) constructs `DomainStates` without an
  explicit domain and the four classes deliberately do not re-declare `domain`. This is an accepted
  limitation, not an oversight: the four dedicated accessors exist for exactly this access, and
  making generic indexing work would require either re-declaring `domain` (which clobbers
  `SensorState` — see Key Constraints) or an MRO walk in `get_domain()`. The lesson is encoded in
  the error, not just docs: an optional accessor-hint ClassVar on the four classes lets
  `get_domain()`'s raise path include "use `self.states.numeric_sensor`" in
  `NoDomainAnnotationError`'s message (requires small changes in `models/states/base.py`,
  `exceptions.py`, and the hint values themselves on the classes in `sensor_shapes.py` — see
  Impact). Class docstrings say the same. **All accessor-naming text — the
  error hint and the docstring pointers — ships in PR 2 with the accessors themselves**, so PR 1
  never references an accessor that doesn't exist yet (see Delivery Sequencing).

## Acceptance Criteria

- **AC#1** `uv run pytest tests/unit/models/ -k sensor_shape` passes, covering FR#1–FR#3.
- **AC#2** A test asserts `resolve(domain="sensor") is SensorState` after importing the four classes,
  covering FR#4.
- **AC#3** `prek pyright -a --stage pre-push` reports no error for a snippet doing arithmetic on
  `NumericSensorState.value` after a `None` guard, and reports an error for the same arithmetic on
  `SensorState.value` — covering FR#2 and proving the narrowing is real.
- **AC#4** A test builds a `DomainStates` over a fixture proxy containing all four shapes, an
  unmatched sensor, **and a numeric-metadata sensor whose value fails conversion**, and asserts
  `len(ds) == len(list(ds))` and that `__contains__` agrees — covering FR#7 including the
  unconvertible edge.
- **AC#5** A fixture-driven test asserts the classifier's result over a recorded real-instance sensor
  sample, covering FR#8–FR#9 — including at least one numeric sensor with no device class, one
  sensor with no metadata at all (expecting "unknown"), one with a custom/unknown `device_class`
  string and no other metadata (expecting "unknown" via the normalization step, not numeric), and
  one of each non-numeric shape. The
  fixture is sanitized before commit: entity ids and names anonymized (no household, person, or
  device names from the source instance).
- **AC#6** A unit test asserts the classifier maps an entity with device class `uptime` to the
  timestamp shape, covering FR#10. (The accessor-level assertion — the same entity appearing in
  `self.states.timestamp_sensor` — lives in AC#17, which lands with PR 2.)
- **AC#7** `cd codegen && uv run hassette-codegen generate --ha-core-path ~/source/core` leaves
  `git diff --exit-code` clean, and `NON_NUMERIC_DEVICE_CLASSES` appears in
  `src/hassette/const/sensor.py`, covering FR#11.
- **AC#8** A test asserts direct lookup of a non-member entity raises `EntityNotInViewError`, that
  the error is a `KeyError` subclass, that `.get()` on the same entity returns `None`, and that
  iteration omits it, covering FR#12.
- **AC#9** A test using `caplog` asserts no record at `ERROR` is emitted while iterating a narrowed
  accessor containing non-matching entities, covering FR#13.
- **AC#10** A test asserts the DI conversion error message contains the entity id, the actual device
  class, and the annotated class name, covering FR#14.
- **AC#11** A test annotates `EnumSensorState` against a temperature-sensor state dict and asserts it
  raises rather than returning a string value, covering FR#15. Companion tests assert a matching
  annotation still converts, that a plain `SensorState` annotation is unaffected, and that an entity
  classifying as "unknown" does not raise.
- **AC#12** `grep -n "native_value\|native_unit_of_measurement\|suggested_display_precision"
  src/hassette/models/states/sensor.py` returns nothing, covering FR#16.
- **AC#13** `prek -a` and `prek pyright -a --stage pre-push` both exit 0.
- **AC#14** `uv run pytest tests/unit tests/integration -n 4` passes with no regressions.
- **AC#15** With the committed `_numeric_state_expected` source snapshot deliberately modified, the
  codegen freshness check fails with a message directing a re-verification of the port; restored, it
  passes — covering FR#17.
- **AC#16** `grep -rn "device_class" src/hassette/models/states/catalog.py` returns nothing, a test
  asserts `inspect.signature(StateRegistry.register)` has no `device_class` parameter, all existing
  catalog and registration tests pass against the domain-only key, and the documented
  domain-override pattern still works — covering FR#18.
- **AC#17** An integration test asserts each of the four `StateManager` accessor properties returns
  a `DomainStates` parameterized to its matching class, that membership is exactly the sensors
  whose shape matches **and** whose state converts (a fixture spanning all four shapes, an
  unknown-shape sensor, and an unconvertible numeric-metadata sensor), and that an `uptime` sensor
  appears in `self.states.timestamp_sensor` — covering FR#5–FR#6 (and the accessor half of FR#10).

## Key Constraints

- **Do not add `device_class` to the catalog key.** The existing single-key overwrite is the
  *intended* override mechanism — a user subclassing with the same domain to supply their own
  definition is a supported pattern, not a bug. Nothing in this design may change that.
- **The four classes must not re-declare `domain`.** Doing so registers them under
  `StateKey("sensor", None)` and silently replaces `SensorState` process-wide
  (`models/states/base.py:155-158`). `DomainStates` gets the domain by another route instead — see
  Architecture.
- **Do not narrow `NumericSensorState.value` to `int | float | Decimal | None`.** A pyright probe
  during research showed the full union makes `Decimal + float` a type error, forcing a guard into
  every arithmetic expression and defeating the feature's purpose.
- **Do not add a `.of(device_class)` method or per-device-class stub overloads.** Filtering to a
  specific device class is a data query wearing a typing feature's clothes; the type axis has four
  members and the accessors match it exactly.
- **Do not rank the DI path and the accessor path by in-repo usage counts.** Callers are user apps
  outside this repository; both paths have real users.

## Dependencies and Assumptions

- **Home Assistant core checkout** at `~/source/core`, currently at 2026.8.0, matching the repo pin
  in `codegen/ha-version.txt`. Codegen reads `NON_NUMERIC_DEVICE_CLASSES` from
  `homeassistant/components/sensor/const.py`.
- **Accepted risk — the ported predicate is not literally HA's.** HA's `_numeric_state_expected`
  takes `native_unit_of_measurement` and `suggested_display_precision`; neither appears in real state
  attributes, so the port reads `unit_of_measurement` and drops the precision term. *Mitigation:* the
  data half is generated (FR#11), the logic half is pinned by a fixture test (AC#5), and upstream
  drift trips the source-snapshot freshness check (FR#17) — the fixture test alone cannot detect HA
  changing *their* logic. Per `git log -L` on the HA checkout, the logic was introduced as a
  property in 2023-02, extracted into the standalone function in 2023-10, and modified once since
  (2026-02) — slow enough that generating the logic would not pay for its fragility, and recent
  enough that leaving it unguarded would not be safe.
- **Accepted risk — recall is not total.** The predicate measured 100% precision and roughly 86%
  recall against a real instance. Precision is the property that protects the declared type; the
  misses are sensors with no metadata, which remain reachable through `self.states.sensor`.
- **Shape validation (FR#15) is additive, not breaking.** It triggers only when the annotation is one
  of the four classes this change introduces, and plain `SensorState` annotations are explicitly
  excluded. No code written before this ships can annotate a class that does not yet exist, so no
  existing user automation changes behavior. This is worth stating explicitly because "DI now raises
  where it used to return a value" reads like a breaking change and is not one — the scoping to the
  new classes is what makes it safe, so that scoping must not be widened later without treating it as
  a breaking change at that point.
- **`state_manager.pyi` has no generator and no freshness check.** This change hand-adds four
  entries. Because the per-device-class overloads were rejected, these four do not change when HA
  adds a device class — `RADON` landing in 2026.8.0 is a worked example. The generator gap is filed
  separately.

## Architecture

### Where the four classes live

A new hand-written module, `src/hassette/models/states/sensor_shapes.py`.

They are not emitted by codegen. `templates/state_model.py.j2` renders exactly one
`{{ domain_title }}State` per domain, and teaching it to emit a subclass loop would be machinery
built for four classes that never vary — the thing that varies across HA releases is the
device-class *set*, which is generated (below). `sensor.py` itself is generated output, so the
classes cannot live there without being overwritten.

Exports need no work: `codegen/src/hassette_codegen/generators/exports.py` scans "both generated and
non-generated modules" in the package directory, so the four names flow into
`models/states/__init__.py` and `__all__` automatically.

Each class subclasses `SensorState` and re-declares `value` — it is not enough to override
`value_type`, because `coerce_numbers_to_str=True` converts the coerced number back to a string. The
re-declaration must repeat `validation_alias=AliasChoices("state", "value")` or the field silently
stops populating. Neither class re-declares `domain` (see Key Constraints).

### The shape classifier

One function decides all four shapes, not just "is it numeric." Membership for every accessor
(FR#6), and the shape comparison in DI validation (FR#15), both read from it.

Before branching, the classifier normalizes `device_class`: a string that is not a known
`SensorDeviceClass` member is treated as `None`, mirroring HA's `try_parse_enum` at
`sensor/__init__.py:609`. HA's `_numeric_state_expected` receives an already-parsed enum-or-`None`;
the port receives a raw string, so the normalization step is part of a faithful port, not an
addition. Skipping it would let custom device classes satisfy the numeric branch's
`device_class is not None` fallback.

It returns one of four results plus "unknown", classifying from the entity's attributes:

| Result | Condition | Class |
|---|---|---|
| date | `device_class` is `date` | `DateSensorState` |
| enum | `device_class` is `enum` | `EnumSensorState` |
| timestamp | `device_class` is `timestamp` **or** `uptime` | `TimestampSensorState` |
| numeric | HA's `_numeric_state_expected` logic returns true | `NumericSensorState` |
| unknown | none of the above — no device class and no `state_class` or unit to infer from | none |

**`uptime` maps to timestamp, and there is no `UptimeSensorState`.** HA's
`NON_NUMERIC_DEVICE_CLASSES` has four members — `date`, `enum`, `timestamp`, `uptime` — but only
three distinct value shapes, because HA renders `timestamp` and `uptime` through the identical branch
(`~/source/core/homeassistant/components/sensor/__init__.py:657-674`): both produce a tz-aware ISO
datetime, with `uptime` differing only by a drift-normalization step that does not change the type.
Adding a fifth class for a shape identical to `TimestampSensorState` would spend a public name on no
type information.

"unknown" is a distinct result from any shape, and the distinction is load-bearing. For accessor
membership it means excluded from all four (the recall gap in Dependencies and Assumptions). For DI
validation it means *do not raise* — an entity whose shape cannot be determined contradicts no claim.

Two pieces, split by what changes.

**The data** — `NON_NUMERIC_DEVICE_CLASSES` — is generated into `src/hassette/const/sensor.py`
alongside the existing `DEVICE_CLASS` literal. `codegen/src/hassette_codegen/extractors/constants.py`
gains a set-literal extractor shaped like the existing `_extract_strenum_members`, and
`generators/constants.py` renders it. This is the part that moves when HA adds a device class.

**The logic** — a hand-written function in `sensor_shapes.py`. Its numeric branch ports HA's
`_numeric_state_expected` (`homeassistant/components/sensor/const.py:556-561` for the set;
`sensor/__init__.py:126-145` for the function) with the two documented substitutions. A comment
records why it diverges and points at the fixture test that pins it.

**The drift guard (FR#17)** — the fixture test pins *hassette's* behavior but cannot detect *HA*
changing theirs. Codegen therefore also extracts the source text of `_numeric_state_expected` and
compares it against a committed snapshot (e.g. `codegen/snapshots/numeric_state_expected.py.txt`);
a mismatch fails the freshness check with a message directing a human re-verification of the port
and a snapshot update. Per the HA checkout's git history the function's body has changed once
since its 2023-10 extraction (2026-02), so this fires rarely — and when it does, it lands at
exactly the version-bump moment where the `ha-version-bump` flow already surfaces manual
follow-ups.

**Input type.** The classifier takes the raw attributes mapping — `state["attributes"]` — not a
parsed `SensorAttributes`. `DomainStates` receives `HassStateDict` from
`state_proxy.yield_domain_states()` (`types/types.py:282`, `core/state_proxy.py:389`), so taking a
parsed model would force a Pydantic construction on every membership check across four `Mapping`
methods. It reads three keys as plain strings: `device_class`, `state_class`, `unit_of_measurement`.

### Filtering in `DomainStates`

`DomainStates.__init__` gains two optional parameters: an explicit `domain`, and a membership
predicate over the raw state dict (see the classifier's input type above).

The predicate is the shape classifier above, compared against the accessor's shape.

The explicit `domain` exists because `DomainStates.__init__` currently derives it via
`model.get_domain()` (`state_manager.py:75`), and `get_domain()` reads the class's *own* annotations
only (`base.py:197-218`) — so a subclass that does not re-declare `domain` raises
`NoDomainAnnotationError`. Passing the domain explicitly is a smaller change than an MRO walk and
keeps the registration behavior in Key Constraints intact. It defaults to `model.get_domain()`, so
every existing caller is unaffected.

The predicate must thread through four methods, because today they disagree. `__iter__` filters only
as a side effect of catching conversion failures (`state_manager.py:118-125`), while `__len__`
(`:127-129`) and `__contains__` (`:131-139`) consult the state proxy directly. Research measured
`len() -> 5` against `list()` yielding 2 on a five-sensor fixture — a `Mapping` invariant violation
that a naive implementation ships.

**Membership is predicate AND convertibility, enforced identically in all four methods** (`__iter__`,
`__len__`, `__contains__`, `__getitem__`). The predicate is the cheap first gate (three dict-key
reads); conversion is the second, and its cost is amortized by the existing per-entity
`_validate_or_return_from_cache` cache, so repeated `len()` calls only re-validate entities whose
state changed. This is the "skip everywhere" resolution of the unconvertible edge: a
numeric-metadata sensor holding a garbage value is out of the view in every method at once, keeping
`len(m) == len(list(m))` unconditional and keeping `items()` loops from aborting mid-iteration. The
resulting value-dependence of `len()`/`in` is confined to that edge (see Edge Cases).

The skip log in `__iter__` drops from `error` to `debug`. At `error` a 200-sensor install would emit
roughly 150 lines per iteration; for a deliberately filtered view a non-match is expected, not
exceptional.

### The accessors

Four real `@property` declarations on `StateManager`, not `__getattr__` routing. `__getattr__` fires
only when normal attribute lookup fails, so a real property shadows it cleanly and avoids teaching
`__getattr__` to parse accessor names into shapes. Each returns a `DomainStates` built with
`domain="sensor"`, the matching class, and the matching predicate.

Caching reuses the existing per-class `_domain_states_cache` (`state_manager.py:189, 208-214`), which
is keyed by state class — the four classes are distinct keys, so each accessor caches independently
and the existing `sensor` accessor is untouched. `_domain_states_for` needs to learn to construct
with a domain and predicate; today it delegates to `__getitem__`, which passes neither.

Four matching entries go into `src/hassette/state_manager/state_manager.pyi` beside the existing
`sensor` property (`:127-128`). The stub is what makes the narrowing visible to pyright; research
verified an invented accessor narrows correctly.

### The DI error wrapper and shape validation

`convert_state_dict_to_model` (`conversion/state_registry.py:218-260`) already holds the full raw
dict, so `attributes["device_class"]` is in scope with no registry involvement. Two changes land
here.

**Legible failures (FR#14).** When `model.model_validate` raises, wrap the Pydantic
`ValidationError` in an error naming the entity, its actual device class, and the annotated class.

**Shape validation (FR#15).** The more damaging case is the one that does *not* fail. Annotating
`D.StateNew[EnumSensorState]` against a temperature sensor returns `'23.5'` with no error, because a
float coerces to a string happily — the author gets a plausible value and no signal. When the
annotated class is one of the four narrowed sensor shapes, compare the shape it declares against the
shape the predicate computes for the entity, and raise when they disagree.

This is what research called Option F-full and deferred, on the grounds that it needed `resolve()` to
have device-class entries to resolve against. That reason does not survive this design: the predicate
is a standalone function over the raw attributes mapping, which is already in scope here, so
validation needs no catalog, no registration, and no `resolve()`.

Validation applies only when the annotation is one of the four narrowed classes. Annotating plain
`SensorState` stays unvalidated and unchanged — it makes no shape claim, so there is nothing to
contradict.

## Implementation Preferences

- `whenever` types for the temporal shapes — `ZonedDateTime` for `TimestampSensorState`, `Date` for
  `DateSensorState`. Both are already imported in `models/states/sensor.py`.
- No `from __future__ import annotations`, no `Optional[X]`, no lazy imports.
- The shape classifier takes the raw attributes mapping and reads three string keys — see
  Architecture for why a parsed `SensorAttributes` would be the wrong input here.
- Follow the existing `StrEnum` extractor shape in `extractors/constants.py` for the set extractor
  rather than inventing a new extraction style.

## Replacement Targets

- **`SensorAttributes.native_value`, `.native_unit_of_measurement`, `.suggested_display_precision`**
  (`models/states/sensor.py:98`, `:99`, `:102`) — removed outright, not deprecated. Dead **by
  construction for every user**, verified against HA core source, not just one instance: the only
  paths that put attributes on a sensor state are `capability_attributes` (emits `state_class` or
  `options` only, `sensor/__init__.py:378-386`) and `state_attributes` (emits `last_reset` only,
  `:468-486`). `native_value` appears upstream solely as an entity-side `@cached_property`, in the
  restore-state persistence store, and in a property-caching shim — never in the state machine. The
  0-of-270 live-instance count is corroborating, not the basis. A custom integration that emits a
  same-named key via `extra_state_attributes` still works after removal (`extra="allow"` keeps
  payload keys accessible); the only behavior change is reading an absent field: `None` today,
  `AttributeError` after. **This is a formal API removal and the PR carries a `BREAKING CHANGE:`
  footer naming all three fields.** Removal happens through the per-domain TOML override system
  (new `remove = true` support, entries in `sensor.toml`) so the generated file stops emitting
  them — scoped to `sensor` only, since `native_value` is live on five other domains. The
  duplicated `| None` on the `native_value` annotation goes with it.

- **The catalog's `device_class` dimension** (`models/states/catalog.py:20-60`,
  `conversion/state_registry.py:114-129`) — removed (FR#18). Added in passing by PR #197
  (2025-12-13), never populated (all 55 entries have `device_class=None`), never consumed (all four
  production `resolve()` call sites pass `domain` only), and this design deliberately does not use
  it — leaving it would be permanently misleading speculative generality. Removal covers the
  `StateKey.device_class` field, `resolve()`'s two-candidate fallback chain, and the `device_class`
  parameter on both public writers. **`StateKey` itself is kept** as a one-field frozen dataclass:
  it is exported from both `models/states/__all__` and `conversion/__all__`, is the yield type of
  `DomainStatesMapping.__iter__`/`items()`/`keys()` (mirrored in `state_manager.pyi:161-164`), and
  is `isinstance`-checked at `conversion/validation.py:118` — collapsing it to a plain `str` key
  would add a third user-visible break for no functional gain, so the removal stays confined to the
  dead dimension. This is a public-signature change on `StateRegistry.register` and joins the
  `BREAKING CHANGE:` footer.

Nothing else is replaced; the rest of the change is additive.

## Convention Examples

### Domain state class with a narrowed value shape

**Source:** `src/hassette/models/states/sensor.py`

```python
class SensorState(StringBaseState):
    """Representation of a Home Assistant sensor state.

    See: https://www.home-assistant.io/integrations/sensor/
    """

    domain: Literal["sensor"]

    attributes: SensorAttributes
```

The four new classes follow this shape minus the `domain` line, and add a re-declared `value`.

### Extracting a constant set from HA core

**Source:** `codegen/src/hassette_codegen/extractors/constants.py`

```python
def _extract_strenum_members(filepath: Path, class_name: str) -> list[str]:
    """Extract string values from a StrEnum class."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name != class_name:
            continue
        ...
```

The set extractor mirrors this: parse, walk, match a named target, return values, tolerate a
`SyntaxError` by returning empty.

### Conversion error carrying entity context

**Source:** `src/hassette/exceptions.py:363-369`

```python
class UnableToConvertStateError(StateRegistryError):
    """Raised when a state dictionary cannot be converted to a specific state class."""

    def __init__(self, entity_id: str, state_class: type["BaseState"]) -> None:
        super().__init__(f"Unable to convert state for entity_id '{entity_id}' to class {state_class.__name__}.")
        self.entity_id = entity_id
        self.state_class = state_class
```

The DI wrapper follows this pattern — a message plus structured attributes, not a bare string.

## Alternatives Considered

- **Runtime catalog dispatch** (`states.get()` returning the narrowed class). Deferred, not rejected
  on merit. The docs teach the cast pattern — "The return annotation is `BaseState`, so type checkers
  see the base type. A cast narrows it to the specific subclass"
  (`docs/pages/core-concepts/api/methods.md:41-43`), demonstrated as
  `cast("states.LightState", state)` in `docs/pages/core-concepts/api/snippets/api_get_state.py:10`.
  Today that cast is honest; the sensor equivalent after dispatch would be a lie — declared `str`,
  runtime `float`, no error. Landing it safely requires migrating
  the docs from `cast` to `isinstance` in the same change, a cost nobody had priced. Its real benefit
  — `api.get_states()` silently dropping entities that fail conversion (`api.py:433`) — is a
  separable bug.
- **Composite-key registration** (`StateKey("sensor", "temperature")`). Rejected. It fixes an
  overwrite that is the intended override mechanism, and it encodes a 62→4 data relationship as
  registry keys, adding ~62 entries to `self.states` iteration to express four types.
- **Per-device-class classes**, the issue as written. Rejected. Every device class outside
  `NON_NUMERIC_DEVICE_CLASSES` — the large majority of `SensorDeviceClass` — would carry an identical
  `value` type; the only additional information is a unit `Literal` that `extra="allow"` cannot
  enforce. (The research brief quotes 53 and 57 for this in places; both predate `RADON` arriving in
  2026.8.0, which is itself the argument — the count is a moving target and the four shapes are not.)
- **`self.states.sensor.of(SensorDeviceClass.TEMPERATURE)`** with 62 stub overloads. Rejected. It
  merges a 62-valued filter with a 4-valued type distinction; the filter is a data query and does not
  belong in the typing feature. `RADON` arriving in 2026.8.0 is a concrete example of the churn this
  avoids.
- **Generic `SensorState[float]`.** Verified feasible and adds no public names, but serves neither
  discoverability nor codegen fidelity, and its correctness rests on Pydantic's lax coercion rather
  than `value_type`, cutting against ADR-0003.
- **Multiple inheritance** — `class NumericSensorState(SensorState, NumericBaseState)`. Rejected.
  `SensorState`'s parameterized ancestor resolves from `BaseState[str | None]` and
  `NumericBaseState`'s from `BaseState[int | float | Decimal | None]`: two distinct concrete classes
  reaching unparameterized `BaseState` by different MRO paths, where Pydantic's field-collection
  order decides which `value` definition wins. Re-declaring the field is explicit and inspectable.
- **Device-class-only membership** (`device_class in NUMERIC_SET`). Rejected on measured evidence: it
  would exclude 37 genuinely numeric sensors on a real 270-sensor instance, 27% of the numeric
  population.
- **Value-parseability as the membership rule** (include a sensor if its current value parses as a
  number). Rejected — membership would become a function of current values, so `len()` would change
  as sensors update.

## Test Strategy

### Required Test Types

Unit — the four classes, the predicate, and the `DomainStates` membership methods are all directly
constructible and are where the invariants live. Integration — the accessors reach through
`StateManager` to a state proxy, which is the seam where the domain-passing and caching changes
could regress. No E2E layer is required: the change is invisible to the frontend (0 hits for
`SensorState`, `BaseState`, or `device_class` in `frontend/` and `openapi.json`).

### Existing Tests to Adapt

- `tests/integration/test_states.py` — `isinstance` assertions on state classes. Verify none assumes
  `SensorState` is the only sensor class.
- `tests/integration/test_app_test_harness.py` — also carries `isinstance` assertions on state
  classes; same check.
- `tests/unit/conversion/test_registry_validation.py` — asserts catalog contents; must still show
  `resolve(domain="sensor") is SensorState` (AC#2).
- `tests/unit/models/test_state_catalog.py` — currently 2 tests, neither covering collision. The new
  AC#2 assertion belongs here.
- `tests/unit/conversion/test_registry_validation.py:88` and `:151` — construct
  `StateKey(domain=..., device_class=...)` directly. These break on FR#18 (the field is gone) and
  must be rewritten against the domain-only key. Distinct from the AC#2 assertion above, which is
  about the same file for a different reason.
- `codegen/tests/test_overrides.py`, `test_extractors.py`, `test_constants_and_exports.py`,
  `test_integration.py` — cover the override system and the constants extractor, both of which
  this change modifies. CI runs them via `cd codegen && uv run pytest tests/`.
- `tests/unit/state_manager/test_domain_states_statereader.py` and `tests/unit/test_state_manager.py`
  — construct `DomainStates(proxy, Model)` positionally at ~15 call sites. The new `domain` and
  predicate parameters must be optional and appended so these keep passing unchanged (a
  Behavioral Invariant); this is also the natural home for the new membership tests.
- Any test asserting on `SensorAttributes` field membership will break on FR#16.

### New Test Coverage

- FR#1–FR#3 — unit, per-class value typing and construction from a state dict.
- FR#4 — unit, catalog unchanged after import.
- FR#5–FR#6 — integration, accessor returns the right class and the right membership.
- FR#7 — unit, `Mapping` invariant across all four methods. This is the regression that a naive
  implementation ships; it needs a fixture covering matched, unmatched, and unconvertible entities.
- FR#8–FR#9 — unit, fixture-driven, over a recorded real-instance sample (AC#5). Must cover all four
  shapes plus "unknown", not just the numeric branch.
- FR#10 — unit, `uptime` classifies as timestamp.
- FR#11 — codegen-level, `NON_NUMERIC_DEVICE_CLASSES` generated and freshness-clean (AC#7).
- FR#12–FR#13 — unit, raise-vs-skip behavior, `KeyError`/`.get()` semantics, and log level.
- FR#14 — unit, error message contents.
- FR#15 — unit, all four cases: mismatched narrowed annotation raises, matching narrowed annotation
  converts, plain `SensorState` annotation is unaffected, "unknown" entity does not raise.
- FR#16 — grep-based absence check on the regenerated `sensor.py` (AC#12).
- FR#17 — freshness-check failure on a modified snapshot, pass on restore (AC#15).
- FR#18 — catalog grep, `StateRegistry.register` signature assertion, and existing
  catalog/registration tests green against the domain-only key (AC#16).

### Tests to Remove

No tests to remove. The three deleted attribute fields have no dedicated coverage.

## Documentation Updates

- `docs/pages/core-concepts/states/` — a section covering the four value shapes, both access paths,
  and the membership rule including its recall gap and the `self.states.sensor` escape hatch. Also
  covers lookup semantics on narrowed accessors: `.get()` returns `None` for non-members, `[]`
  raises `EntityNotInViewError`.
- **The view/projection concept gets explicit, prominent treatment** — this is the one genuinely new
  mental model in the change and must not be left implicit. The docs must state plainly: the four
  narrowed accessors are *filtered views (projections) over the same underlying sensor states*, not
  new domains and not a partition. The same entity appears under `self.states.sensor` (as
  `SensorState`, `value: str | None`) **and** under its shape accessor (with the narrowed value
  type) — two typed lenses on one state, unlike every other state class, which corresponds 1:1 with
  a domain. Membership is computed from metadata per access, so a view is dynamic where a domain
  accessor is total. A short table or diagram contrasting "domain accessor" vs "shape view"
  (totality, value type, membership rule, failure behavior) is the suggested form.
- Docstrings on the four classes and the four accessors. The class docstrings must state that
  `self.states[<class>]` is unsupported and name the accessor instead (see Edge Cases) — this
  accessor-naming sentence is added in PR 2, when the accessor exists.
- `docs/pages/core-concepts/states/index.md:121` **and `:122`** — fix the pre-existing stale claim
  that `attributes.device_class` is `str | None`. It is `SensorDeviceClass | None` on line 121
  (`SensorState`) and `BinarySensorDeviceClass | None` on line 122 (`BinarySensorState`); both are
  wrong in the same way. Cheap to correct while this change is already editing the same page.
- The predicate function's docstring records the two divergences from HA's version and points at the
  fixture test.
- No changelog entry — release-please generates it from the commit.

## Impact

<!-- Gap check 2026-08-07: 5 gaps included — FR#16 mechanism over-reach (extract_properties is
domain-agnostic; native_value live on date/datetime/number/text/time) → T02 Focus + Changed Files
corrected to overrides.py/sensor.toml; test_registry_validation.py:88,151 construct
StateKey(device_class=) → T03 Target Files + Test Strategy; codegen/tests/{test_overrides,
test_extractors,test_constants_and_exports,test_integration}.py cover changed codegen surfaces →
T01/T02 Target Files + Test Strategy; DomainStates(proxy, Model) positional call sites in
tests/unit/state_manager/ and tests/unit/test_state_manager.py → T06 Focus (new params must be
optional/appended); docs index.md:122 carries the same stale device_class claim as :121 → T08
Part 3. Categories searched: tests, callers, validators/guards, documentation, generated code, type
aliases, data structures. Skipped: CSS/layout, SQL, real-time paths (no such surfaces in scope —
frontend impact verified zero). -->

### Changed Files

- `modify` `src/hassette/state_manager/state_manager.py` — `DomainStates.__init__` gains `domain` and
  predicate parameters; `__iter__`/`__len__`/`__contains__`/`__getitem__` consult the predicate;
  skip log drops to `debug`; `_domain_states_for` constructs with domain and predicate; four
  properties added. Highest-risk file — it is on every state read path.
- `modify` `src/hassette/state_manager/state_manager.pyi` — four property entries.
- `modify` `src/hassette/models/states/catalog.py` — remove the `device_class` dimension: `StateKey`
  field, `resolve()` fallback chain, `register_state_converter` parameter (FR#18).
- `create` `src/hassette/models/states/sensor_shapes.py` — the four classes and the predicate
  (PR 1).
- `modify` `src/hassette/models/states/sensor_shapes.py` — second touch in PR 2: the accessor-hint
  ClassVar on the four classes and the docstring sentence naming each class's accessor (deferred
  from PR 1 so no text references a not-yet-existing accessor).
- `modify` `src/hassette/conversion/state_registry.py` — DI error wrapper and shape validation in
  `convert_state_dict_to_model`; `StateRegistry.register` loses its `device_class` parameter
  (FR#18, public-signature change). Second-highest risk: this function is on the DI path for every
  domain, so the shape check must be scoped to the four sensor classes and skip everything else.
- `modify` `src/hassette/exceptions.py` — PR 1: the new DI conversion error and the shape-mismatch
  error (FR#14–FR#15). PR 2: `EntityNotInViewError` (subclassing `KeyError` and the state-error
  hierarchy, FR#12) and the optional accessor-hint on `NoDomainAnnotationError`'s message (see
  Edge Cases).
- `modify` `src/hassette/models/states/base.py` — `get_domain()`'s raise path reads an optional
  per-class accessor-hint ClassVar (set only on the four shape classes) so
  `NoDomainAnnotationError` can name the dedicated accessor (PR 2).
- `modify` `codegen/src/hassette_codegen/extractors/constants.py` — set-literal extractor;
  source-text extraction of `_numeric_state_expected` for the drift guard.
- `modify` `codegen/src/hassette_codegen/overrides.py` — `PropertyOverride` gains a `remove: bool`
  flag and `apply_property_overrides` honors it (FR#16). **Not** an exclusion inside
  `extract_properties()`: that function is domain-agnostic, and `native_value` is a live field on
  `date`, `datetime`, `number`, `text`, and `time` (plus `native_unit_of_measurement` on `number`),
  so a `supported_features`-style global exclusion would delete fields FR#16 never scoped. The
  TOML override system is already the per-domain mechanism and already supports rename/retype/add.
- `modify` `codegen/src/hassette_codegen/overrides/sensor.toml` — three `remove = true` entries for
  `native_value`, `native_unit_of_measurement`, and `suggested_display_precision` (FR#16).
- `modify` `codegen/src/hassette_codegen/generators/constants.py` — render the new set. Today every
  `ExtractedConstantSet` renders as a `Literal[...]` type alias; `NON_NUMERIC_DEVICE_CLASSES` needs
  a runtime `frozenset` path, since the classifier compares against it at runtime.
- `modify` `codegen/src/hassette_codegen/pipeline.py` — wire the FR#17 snapshot comparison into the
  `--check` freshness path that CI runs.
- `create` `codegen/snapshots/numeric_state_expected.py.txt` — committed source snapshot for the
  FR#17 freshness check (exact path per existing codegen layout conventions).
- `regenerate` `src/hassette/const/sensor.py` — gains `NON_NUMERIC_DEVICE_CLASSES`.
- `regenerate` `src/hassette/models/states/sensor.py` — loses the three dead fields.
- `regenerate` `src/hassette/models/states/__init__.py` — gains the four names.
- `create` tests per Test Strategy, including the real-instance fixture. New fixture-building
  helpers (the multi-shape `DomainStates` fixture proxy, the sanitized sensor sample) follow
  `.claude/rules/test-conventions.md`: check `src/hassette/test_utils/` for existing factories
  first, and add shared factories there rather than local `make_*` copies if used across 3+ files.
- `modify` `docs/pages/core-concepts/states/` — new documentation section.

### Behavioral Invariants

- `resolve(domain="sensor")` returns `SensorState`.
- `self.states.sensor` contains every sensor, with `value` still `str | None`.
- `states.get()`, `api.get_state()`, and `api.get_states()` return exactly what they return today.
- Existing `DomainStates` construction — `self.states.light`, `self.states[CustomClass]` — is
  unaffected; the new parameters default to today's behavior.
- The documented override pattern (subclass with the same `domain` to replace a built-in) keeps
  working.
- Dependency injection against any pre-existing state class — including plain `SensorState` — behaves
  exactly as it does today. Shape validation applies only to the four new classes.

### Blast Radius

`DomainStates` is on every typed state read, so a regression in the membership methods affects every
domain, not just sensor. That risk is contained by the parameters defaulting to current behavior and
by AC#14 (full unit and integration suite green).

Frontend impact is genuinely zero — 0 hits for `SensorState`, `BaseState`, or `device_class` in
`frontend/` and `openapi.json`. This qualifies for the documented exception in
`.claude/rules/design-completeness.md`; no screenshots or type regeneration are required, and the PR
should carry the `no-visual-change` label.

## Delivery Sequencing

The work lands as **two PRs**, per the sequence-verifiable-units rule — the risky `Mapping` surgery
lands on a green baseline established by the purely additive half:

- **PR 1 — the classes and the codegen half (additive except FR#16/FR#18).** The four state
  classes, the shape classifier, the DI error wrapper and shape validation (FR#14–FR#15), the
  dead-field removal (FR#16), the catalog `device_class`-dimension removal (FR#18), the codegen
  extractors, `NON_NUMERIC_DEVICE_CLASSES` generation, and the FR#17 drift snapshot. Ships as
  `feat!` with one `BREAKING CHANGE:` footer covering both removals (the three dead attribute
  fields; the `device_class` parameter/key dimension). Independently verifiable: the classes work
  on every author-names-the-class surface (`D.StateNew[...]` etc.) with no accessor support yet.
- **PR 2 — the accessors.** The `DomainStates` predicate/membership changes,
  `EntityNotInViewError`, the four `StateManager` properties, the four stub entries, the
  accessor-naming text (the `NoDomainAnnotationError` accessor hint and the class-docstring
  pointers — deferred here so PR 1 never references an accessor that doesn't exist yet), and the
  docs section covering both access paths. Plain `feat`. Touches the highest-risk file
  (`state_manager.py`, on every state read path) with PR 1 already green underneath it.

The design remains one spec; task planning in `/mine-plan` should group tasks so the PR boundary
falls between the two sets.

## Open Questions

None.
