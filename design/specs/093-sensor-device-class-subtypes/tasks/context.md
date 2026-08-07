# Context: Device-class-specific sensor state subtypes

## Problem & Motivation

`SensorState.value` is typed `str | None` because `SensorState` extends `StringBaseState`
(`src/hassette/models/states/sensor.py:112`). Home Assistant sensors carry four genuinely different
value shapes — numeric, enum, timestamp, and date — and the framework flattens all four into a
string. App authors pay for that on every numeric sensor read: `float(str(new_state.value))` appears
throughout this repo's own examples and docs, sometimes with a `# pyright: ignore` attached. The
type checker cannot help, and there is no way to ask the framework for "the sensors whose values are
numbers."

Hassette is a framework — its real callers are user automations outside this repository. The
friction sites visible in this repo are a sample of the problem, not its extent. Do not rank access
paths or judge demand by in-repo usage counts.

## Visual Artifacts

None. Frontend impact is verified zero (0 hits for `SensorState`, `BaseState`, or `device_class` in
`frontend/` and `openapi.json`). The PR carries the `no-visual-change` label.

## Key Decisions

1. **Four value-shape classes, not sixty-two per-device-class classes.** `NumericSensorState`,
   `EnumSensorState`, `TimestampSensorState`, `DateSensorState`. The type axis has exactly four
   members; 57+ numeric device classes share one value type, so per-device-class names would spend
   public API on a distinction the type system cannot see. A new HA device class adds no class, no
   accessor, and no stub entry.

2. **`uptime` maps to the timestamp shape; there is no `UptimeSensorState`.** HA's
   `NON_NUMERIC_DEVICE_CLASSES` has four members but only three distinct value shapes — `timestamp`
   and `uptime` render through the identical branch
   (`~/source/core/homeassistant/components/sensor/__init__.py:657-674`), differing only by a
   drift-normalization step that does not change the type.

3. **Membership is decided by a port of HA's `_numeric_state_expected`, not by device-class-set
   membership.** A naive `device_class in NUMERIC_SET` rule was measured against a real 270-sensor
   instance and would have silently excluded 37 genuinely numeric sensors — 27% of the numeric
   population — because 46% of real sensors carry no device class at all. The ported predicate
   measured 100% precision / ~86% recall. Precision is what protects the declared type; the misses
   stay reachable through `self.states.sensor`.

4. **Membership is predicate AND convertibility, enforced identically in all four `Mapping`
   methods.** A sensor whose metadata says numeric but whose value fails conversion is out of the
   view everywhere at once. This keeps `len(m) == len(list(m))` unconditional and keeps `items()`
   loops from aborting mid-iteration on one flaky sensor. Accepted tradeoff: `len()` and `in` become
   value-dependent for that one edge.

5. **The classifier normalizes unknown `device_class` strings to `None`.** Custom device classes do
   reach state attributes unvalidated; HA normalizes at the point of use via
   `try_parse_enum(SensorDeviceClass, ...)` (`sensor/__init__.py:609`). Without the same step, a
   custom device class would satisfy the numeric branch's `device_class is not None` fallback and
   misclassify as numeric — the exact false positive this feature exists to prevent.

6. **Non-member lookup raises a `KeyError` subclass.** `EntityNotInViewError` subclasses both
   `KeyError` and the state-error hierarchy, so `[]` fails loudly with a legible message while
   `Mapping.get()` returns `None` — consistent with `__contains__` returning `False`, and preserving
   the standard "might not be there" idiom on a view where non-membership is common.

7. **Nothing registers in the catalog.** The four classes deliberately do not re-declare `domain`,
   which is what keeps `__init_subclass__` from registering them and clobbering `SensorState`.
   `DomainStates` receives the domain explicitly instead. `resolve(domain="sensor")` returns
   `SensorState` before and after.

8. **The catalog's dead `device_class` dimension is removed rather than left unused.** It was added
   in passing by PR #197 (2025-12-13), never populated, never consumed. `StateKey` survives as a
   one-field frozen dataclass — it is publicly exported and is the yield type of `self.states`
   iteration, so collapsing it to a plain `str` would add a third user-visible break for no gain.

9. **Runtime dispatch on the erased paths is deferred, not rejected.** The docs teach `cast` on
   `states.get()` / `api.get_state()`; narrowing the runtime type without narrowing the declared
   type would turn that honest cast into a lie. Landing it safely requires a docs migration from
   `cast` to `isinstance` that nobody has priced.

10. **The dead-field removal is scoped to `sensor` via the TOML override system.**
    `extract_properties()` is domain-agnostic and `native_value` is a live field on `date`,
    `datetime`, `number`, `text`, and `time` — a `supported_features`-style global exclusion would
    delete fields this change never scoped.

## Constraints & Anti-Patterns

- **Do not add `device_class` to the catalog key.** The single-key overwrite is the *intended*
  override mechanism — a user subclassing with the same domain to supply their own definition is a
  supported pattern, not a bug.
- **The four classes must not re-declare `domain`.** Doing so registers them under
  `StateKey("sensor", None)` and silently replaces `SensorState` process-wide
  (`models/states/base.py:155-158`).
- **Do not type `NumericSensorState.value` as `int | float | Decimal | None`.** A pyright probe
  showed the full union makes `Decimal + float` a type error, forcing a guard into every arithmetic
  expression and defeating the feature's purpose. It is `float | None`.
- **Do not add a `.of(device_class)` method or per-device-class stub overloads.** Filtering to a
  specific device class is a data query wearing a typing feature's clothes.
- **Do not rank the DI path against the accessor path by in-repo usage counts.** Callers are user
  apps outside this repository; both paths have real users.
- **Overriding `value_type` alone does nothing.** `coerce_numbers_to_str=True` (`base.py:72`)
  converts the coerced number back to a string. The subclass must re-declare the `value` field.
- **A re-declared `value` field must repeat `validation_alias=AliasChoices("state", "value")`.**
  There is no `populate_by_name`, so omitting the alias makes the field silently stop populating
  from state dicts.
- No `from __future__ import annotations`, no `Optional[X]`, no lazy imports.
- Do not implement any Non-goal: runtime catalog dispatch, device-class-keyed registration,
  filtering by a specific device class, per-device-class classes, other domains, or bringing
  `state_manager.pyi` under codegen.

## Design Doc References

- `## Problem` — why `str`-typed sensor values cost app authors on every numeric read.
- `## Goals` / `## Non-Goals` — the scope boundary, including what is deferred vs rejected.
- `## Functional Requirements` — FR#1–FR#18, the authoritative requirement list.
- `## Edge Cases` — no-device-class sensors, custom device-class strings, runtime device-class
  flips, unconvertible values, `self.states[<class>]` generic indexing.
- `## Acceptance Criteria` — AC#1–AC#17, each naming the FR it covers.
- `## Key Constraints` — the five hard rules restated above.
- `## Architecture` — where the classes live, the shape classifier and its drift guard, filtering in
  `DomainStates`, the accessors, and the DI error wrapper plus shape validation.
- `## Replacement Targets` — the three dead `SensorAttributes` fields and the catalog's
  `device_class` dimension, with the evidence for each removal.
- `## Test Strategy` — required test types, existing tests to adapt, new coverage per FR.
- `## Impact` — changed files, behavioral invariants, blast radius.
- `## Delivery Sequencing` — the two-PR split and why the risky half lands second.

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
