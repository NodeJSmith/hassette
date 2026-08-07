---
task_id: "T02"
title: "Remove three dead SensorAttributes fields via TOML overrides"
status: "planned"
depends_on: []
implements: ["FR#16", "AC#12"]
---

## Summary

`SensorAttributes` declares `native_value`, `native_unit_of_measurement`, and
`suggested_display_precision` — three fields Home Assistant never puts on a sensor state. They are
codegen artifacts scraped from HA's entity-side `_attr_*` annotations. Remove them by adding a
`remove` capability to the per-domain TOML override system and declaring the three fields in
`sensor.toml`, then regenerate. This is a formal API removal that ships with a `BREAKING CHANGE:`
footer.

## Target Files

- modify: `codegen/src/hassette_codegen/overrides.py`
- modify: `codegen/src/hassette_codegen/overrides/sensor.toml`
- regenerate: `src/hassette/models/states/sensor.py`
- read: `codegen/src/hassette_codegen/extractors/properties.py`
- read: `codegen/src/hassette_codegen/pipeline.py`
- read: `codegen/src/hassette_codegen/overrides/number.toml`
- modify: `codegen/tests/test_overrides.py`

## Prompt

Read `context.md` first, then the design doc's `## Replacement Targets` section (the first bullet)
for the evidence that these fields are dead.

**Why they are dead, for every user — not just one instance.** Verified against HA core source: the
only two paths that put attributes on a sensor state are `capability_attributes`, which emits
`state_class` or `options` (`~/source/core/homeassistant/components/sensor/__init__.py:378-386`),
and `state_attributes`, which emits `last_reset` (`:468-486`). `native_value` appears upstream only
as an entity-side `@cached_property`, in the restore-state persistence store, and in a
property-caching shim — never in the state machine. A live-instance survey found all three populated
in 0 of 270 sensors, which corroborates rather than establishes this.

**Part 1 — add removal support to the override system.**

`codegen/src/hassette_codegen/overrides.py` defines `PropertyOverride` (fields: `name`, `wire_name`,
`type`, `add`) and `apply_property_overrides`, which today supports rename, retype, and add. Add a
`remove: bool = False` field, parse it in `load_overrides` alongside the existing `add` flag, and
handle it in `apply_property_overrides` by dropping the matching property from the returned list.

Keep `apply_property_overrides` non-mutating — it already builds a new list rather than editing the
input, and that must not change.

Decide and document the behavior when `remove` targets a property that does not exist. Prefer a
warning on stderr (matching how `load_overrides` and `validate_overrides` already report override
problems) rather than silence, so a field that upstream renames does not leave a dead override
entry that quietly does nothing.

**Part 2 — declare the three removals.**

Add three `[[property_overrides]]` entries with `remove = true` to
`codegen/src/hassette_codegen/overrides/sensor.toml` for `native_value`,
`native_unit_of_measurement`, and `suggested_display_precision`. The file already contains one
`add = true` entry for `unit_of_measurement` — follow its formatting.

**Part 3 — regenerate.**

```bash
cd codegen && uv run hassette-codegen generate --ha-core-path ~/source/core
```

Confirm `src/hassette/models/states/sensor.py` no longer declares the three fields. The duplicated
`| None` on the old `native_value` annotation disappears with it.

Add codegen unit tests for the `remove` flag in `codegen/tests/test_overrides.py`.

## Focus

**Do not implement this as an exclusion in `extract_properties()`.** That is what the design
originally proposed, and it is wrong: `extract_properties(init_py: Path)` is domain-agnostic — it
strips `_attr_*` from whatever entity class it is given, for every domain. The existing
`supported_features` exclusion at `codegen/src/hassette_codegen/extractors/properties.py:41` is
global on purpose. A global exclusion here would silently delete **live** fields from five other
domains:

- `src/hassette/models/states/date.py:10` — `native_value: Date | None`
- `src/hassette/models/states/datetime.py:12` — `native_value: ZonedDateTime | None` (plus a
  `field_validator` on it at `:14`)
- `src/hassette/models/states/number.py:89-90` — `native_unit_of_measurement`, `native_value`
- `src/hassette/models/states/text.py:23` — `native_value: str | None`
- `src/hassette/models/states/time.py:10` — `native_value: Time | None`

The TOML override system is the per-domain mechanism and is scoped correctly by construction. This
task is why it needs a `remove` capability it does not have yet.

**Blast radius is small.** Grep confirmed zero reads of these three fields anywhere in `tests/`,
`docs/`, `examples/`, or `scripts/`. No test asserts on `SensorAttributes` field membership today.

**`extra="allow"` softens the removal for custom integrations.** A custom integration that emits a
same-named key via `extra_state_attributes` still has it accessible on the model after removal — the
only behavior change is reading an *absent declared* field: `None` today, `AttributeError` after.
Do not add a deprecation shim; the design specifies outright removal.

**Regeneration rewrites every generated file.** After running codegen, check `git status` — anything
changed outside `src/hassette/models/states/sensor.py` is either T01's work (if that landed first)
or pre-existing drift. Report it rather than committing it silently.

## Verify

- [ ] FR#16: `SensorAttributes` in the regenerated `src/hassette/models/states/sensor.py` no longer
      declares `native_value`, `native_unit_of_measurement`, or `suggested_display_precision`, and
      the removal is driven by `sensor.toml` rather than a global extractor exclusion.
- [ ] AC#12: `grep -n "native_value\|native_unit_of_measurement\|suggested_display_precision"
      src/hassette/models/states/sensor.py` returns nothing.
