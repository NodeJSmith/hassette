---
task_id: "T04"
title: "Add the four sensor shape classes and the shape classifier"
status: "done"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#8", "FR#9", "FR#10", "AC#1", "AC#2", "AC#3", "AC#5", "AC#6"]
---

## Summary

Create `src/hassette/models/states/sensor_shapes.py` holding the four narrowed state classes —
`NumericSensorState`, `EnumSensorState`, `TimestampSensorState`, `DateSensorState` — and the single
shape classifier that decides which shape an entity has. The classes make narrowing available
immediately on every surface where the author names the class (`D.StateNew[...]`,
`self.states[...]`, `Api.get_entity`, and the rest). The classifier is the one function that both
accessor membership (T06) and DI shape validation (T05) will read from.

## Target Files

- create: `src/hassette/models/states/sensor_shapes.py`
- create: `tests/unit/models/test_sensor_shapes.py`
- read: `src/hassette/models/states/sensor.py`
- read: `src/hassette/models/states/base.py`
- read: `src/hassette/const/sensor.py`
- read: `src/hassette/conversion/type_registry.py`
- read: `tests/unit/models/test_state_catalog.py`
- modify: `tests/unit/models/test_state_catalog.py`
- regenerate: `src/hassette/models/states/__init__.py`
- read: `~/source/core/homeassistant/components/sensor/__init__.py`

## Prompt

Read `context.md` first, then the design doc's `## Architecture → Where the four classes live` and
`## Architecture → The shape classifier` sections in full.

**Part 1 — the four classes (FR#1, FR#2, FR#3, FR#4).**

Create `src/hassette/models/states/sensor_shapes.py` as a hand-written module. Do not put these in
`sensor.py` — that file is generated output and would overwrite them. Do not teach codegen to emit
them: the template renders exactly one `{{ domain_title }}State` per domain, and a subclass loop
would be machinery built for four classes that never vary.

Each class subclasses `SensorState` and re-declares `value`:

| Class | `value` type |
|---|---|
| `NumericSensorState` | `float \| None` |
| `EnumSensorState` | `str \| None` |
| `TimestampSensorState` | `ZonedDateTime \| None` |
| `DateSensorState` | `Date \| None` |

Three hard requirements on the re-declaration, each of which was verified to fail silently if
skipped:

1. **Re-declare the `value` field itself.** Overriding the `value_type` ClassVar alone does nothing
   — `coerce_numbers_to_str=True` (`base.py:72`) converts the coerced number straight back to a
   string.
2. **Repeat `validation_alias=AliasChoices("state", "value")`.** `base.py:105` declares it and there
   is no `populate_by_name`, so a re-declared field without the alias silently stops being populated
   from state dicts.
3. **Do not re-declare `domain`.** Doing so registers the class under `StateKey("sensor", None)` and
   silently replaces `SensorState` process-wide (`base.py:155-158`). Their *not* being registered is
   what FR#4 requires.

Also set the `value_type` ClassVar to match each narrowed type, so the `TYPE_REGISTRY` conversion
step targets the right type. Use `whenever` types (`ZonedDateTime`, `Date`) — both are already
imported in `models/states/sensor.py`; do not use stdlib `datetime`/`date`.

Write class docstrings describing each shape. **Do not yet add the sentence naming the dedicated
accessor** — the accessors do not exist until T07, and PR 1 must not reference them. T07 adds that
text.

**Part 2 — the shape classifier (FR#8, FR#9, FR#10).**

One function in the same module maps an entity's attributes to one of four shapes or to "unknown".

**Input type:** the raw attributes mapping (`state["attributes"]`), *not* a parsed
`SensorAttributes`. `DomainStates` receives `HassStateDict` from `state_proxy.yield_domain_states()`,
so taking a parsed model would force a Pydantic construction on every membership check across four
`Mapping` methods. Read three keys as plain strings: `device_class`, `state_class`,
`unit_of_measurement`.

**Normalize first.** Before branching, treat a `device_class` string that is not a known member as
`None`, mirroring HA's `try_parse_enum(SensorDeviceClass, ...)` at `sensor/__init__.py:609`. The
valid member set is available at runtime from the generated `DEVICE_CLASS` Literal in
`src/hassette/const/sensor.py` via `typing.get_args`. Skipping this step would let a custom device
class satisfy the numeric branch's `device_class is not None` fallback and misclassify as numeric —
the exact false positive this feature exists to prevent.

**Then branch:**

| Result | Condition |
|---|---|
| date | `device_class` is `date` |
| enum | `device_class` is `enum` |
| timestamp | `device_class` is `timestamp` **or** `uptime` |
| numeric | HA's `_numeric_state_expected` logic returns true |
| unknown | none of the above |

The numeric branch is a port of HA's `_numeric_state_expected`
(`~/source/core/homeassistant/components/sensor/__init__.py:126-145`) with two documented
substitutions: it reads `unit_of_measurement` where HA reads `native_unit_of_measurement` (a sensor
with a native unit always has a display unit), and it drops the `suggested_display_precision` term
(that attribute never reaches state attributes — 0 of 270 on a real instance). Record both
divergences in the function's docstring and point at the fixture test that pins it.

Return an enum or `Literal`, not a bare string — "unknown" must be a distinct, checkable result,
because T05 and T06 both branch on it differently (membership: excluded; DI validation: do not
raise).

**Part 3 — tests.**

Create `tests/unit/models/test_sensor_shapes.py` (the name matters: AC#1 selects with
`-k sensor_shape`). Cover per-class value typing and construction from a state dict (FR#1–FR#3), and
drive the classifier from a fixture sample covering all four shapes plus every "unknown" path
(FR#8–FR#10).

Add the FR#4 assertion — `resolve(domain="sensor") is SensorState` after importing the four classes
— to `tests/unit/models/test_state_catalog.py`, which currently has 2 tests.

## Focus

**Depends on T01.** The classifier reads `NON_NUMERIC_DEVICE_CLASSES` from
`src/hassette/const/sensor.py`, which T01 generates. Do not hand-write that set.

**Structural note on the port.** Because `date`, `enum`, `timestamp`, and `uptime` are all handled
by explicit branches above the numeric one, HA's leading `if device_class in
NON_NUMERIC_DEVICE_CLASSES: return False` is technically unreachable in your arrangement. Keep the
check anyway and keep the branch order aligned with HA's — the whole point of FR#17's source
snapshot is that a human can diff your port against upstream when it changes, and a restructured
port makes that diff useless. Add a comment saying so.

**`uptime` is not a fifth class.** HA's `NON_NUMERIC_DEVICE_CLASSES` has four members but only three
distinct value shapes: `timestamp` and `uptime` render through the identical branch
(`sensor/__init__.py:657-674`), differing only by a drift-normalization step that does not change
the type.

**Do not narrow to `int | float | Decimal | None`.** A pyright probe showed the full union makes
`Decimal + float` a type error, forcing a guard into every arithmetic expression. `float | None` is
the requirement.

**Exports are automatic.** `codegen/src/hassette_codegen/generators/exports.py` scans both generated
and non-generated modules in the package directory, so the four names flow into
`models/states/__init__.py` and `__all__` with no generator change. Run codegen after creating the
module and commit the regenerated `__init__.py`.

**`ZonedDateTime` and `Date` conversion already works.** `conversion/type_registry.py` registers
`from_string_to_zoned_date_time` (which handles offset-ISO, plain, and date-only strings, lines
291-299) and `str → Date` via `Date.parse_iso` (line 278). No new converters are needed.

**Sanitize the AC#5 fixture before committing.** If you build it from a real instance, anonymize
entity ids and friendly names — no household, person, or device names.

**Test isolation is handled.** `tests/conftest.py:225-227` snapshots and restores `_STATE_CATALOG`
around each test, so an import-order-sensitive catalog assertion will not leak into other tests.

## Verify

- [ ] FR#1: `NumericSensorState`, `EnumSensorState`, `TimestampSensorState`, and `DateSensorState`
      exist in `src/hassette/models/states/sensor_shapes.py`, each a subclass of `SensorState`.
- [ ] FR#2: `NumericSensorState.value` is `float | None` and a temperature state dict converts to a
      `float` at runtime.
- [ ] FR#3: `EnumSensorState.value` is `str | None`, `TimestampSensorState.value` is
      `ZonedDateTime | None`, and `DateSensorState.value` is `Date | None`.
- [ ] FR#4: None of the four classes appears in the catalog after import.
- [ ] FR#8: A single classifier function returns one of four shapes or "unknown" from a raw
      attributes mapping, and "unknown" is a distinct checkable result.
- [ ] FR#9: The numeric branch is a port of `_numeric_state_expected` — a sensor with no device class
      but a `state_class` or `unit_of_measurement` classifies as numeric.
- [ ] FR#10: An entity with device class `uptime` classifies as the timestamp shape, and no
      `UptimeSensorState` class exists.
- [ ] AC#1: `uv run pytest tests/unit/models/ -k sensor_shape` passes.
- [ ] AC#2: A test asserts `resolve(domain="sensor") is SensorState` after importing the four
      classes.
- [ ] AC#3: `prek pyright -a --stage pre-push` reports no error for arithmetic on
      `NumericSensorState.value` after a `None` guard, and reports an error for the same arithmetic
      on `SensorState.value`.
- [ ] AC#5: A fixture-driven test asserts the classifier's result over a sanitized real-instance
      sample including a numeric sensor with no device class, a sensor with no metadata at all
      (expecting "unknown"), a sensor with a custom/unknown `device_class` string and no other
      metadata (expecting "unknown", not numeric), and one of each non-numeric shape.
- [ ] AC#6: A unit test asserts the classifier maps device class `uptime` to the timestamp shape.
