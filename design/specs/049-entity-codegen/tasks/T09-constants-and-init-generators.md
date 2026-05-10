---
task_id: "T09"
title: "Implement constants generator and __init__.py generator"
status: "planned"
depends_on: ["T04", "T06", "T07", "T08"]
implements: ["FR#7", "FR#13", "FR#18", "AC#10", "AC#16"]
---

## Summary
Builds two generators: (1) constants extractor/generator for sensor device classes, units of measurement, and state classes; (2) the __init__.py generator that scans all sibling modules (generated + non-generated) via static analysis and produces complete sorted export lists.

## Prompt
Create:

**`codegen/src/hassette_codegen/extractors/constants.py`:**
- Extract sensor device classes from HA core's `homeassistant/components/sensor/const.py` — find `SensorDeviceClass(StrEnum)` members
- Extract units from `homeassistant/const.py` — find `UNIT_*` constants or `UnitOf*` enums
- Extract state classes from sensor's `SensorStateClass(StrEnum)` members
- Return structured data for each constant set

**`codegen/src/hassette_codegen/generators/constants.py`:**
- Input: extracted constant data
- Render `src/hassette/const/sensor.py` containing `DEVICE_CLASS`, `UNIT_OF_MEASUREMENT`, `STATE_CLASS` as `Literal[...]` types
- Template: `codegen/src/hassette_codegen/templates/constants.py.j2`
- Match existing format in `src/hassette/const/sensor.py`

**`codegen/src/hassette_codegen/generators/exports.py`:**
- Input: target package directory path (e.g., `src/hassette/models/states/`)
- Scan all `.py` files in the directory (excluding `__init__.py` itself)
- For each file, AST-parse to find public class names (classes not prefixed with `_`)
- Also find module-level type aliases and IntFlag enums
- Produce a complete `__init__.py` with:
  - Sorted `from .{module} import {Class1, Class2}` lines grouped by module
  - `__all__` list containing all exported names in sorted order
- Non-generated modules (`simple.py`, `input.py`, `base.py`) are scanned the same way — their exports appear in the generated `__init__.py`

Unit tests:
- Constants extraction finds `SensorDeviceClass` members from HA core
- `__init__.py` generator includes exports from both a generated module and a hand-written module
- Sorted order is deterministic (alphabetical by module name, then by class name within module)
- Generated `__init__.py` passes py_compile

## Focus
- Existing `src/hassette/const/sensor.py` defines `DEVICE_CLASS = Literal["apparent_power", "aqi", ...]` with 60+ values, `UNIT_OF_MEASUREMENT` with 182 values, `STATE_CLASS` with 4 values. Match this format exactly.
- The `__init__.py` scanner must handle: regular classes, IntFlag enums, type aliases (`TypeAlias`), and re-exports
- `base.py` exports `BaseState`, `BoolBaseState`, `StringBaseState`, `NumericBaseState`, `AttributesBase`, etc. — all must appear in the generated `__init__.py`
- `simple.py` exports 12+ state classes (BinarySensorState, SwitchState, etc.) — all must appear
- The existing `__init__.py` uses explicit `from .module import (Class1, Class2)` syntax — not `import *`

## Verify
- [ ] FR#7: Device class, unit of measurement, and state class constants are generated from HA core definitions
- [ ] FR#13: __init__.py export lists are generated for state and entity modules
- [ ] FR#18: __init__.py is produced by scanning all sibling modules (generated + non-generated) via static analysis
- [ ] AC#10: Generated __init__.py exports all state/entity classes in sorted order
- [ ] AC#16: Generated __init__.py includes exports from non-generated modules (e.g., BinarySensorState from simple.py, InputBooleanState from input.py)
