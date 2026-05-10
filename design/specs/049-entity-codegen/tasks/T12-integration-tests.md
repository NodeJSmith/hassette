---
task_id: "T12"
title: "Add integration tests and golden-file validation"
status: "planned"
depends_on: ["T10"]
implements: ["FR#11", "AC#1", "AC#5", "AC#6"]
---

## Summary
End-to-end integration tests that run the full generator against real HA core domains and validate the output. Includes golden-file comparisons for stable domains (fan, sensor) and pyright verification of all generated output. Proves the generator produces correct, type-safe code.

## Prompt
Create `codegen/tests/test_integration.py`:

**Full-pipeline tests (against ~/source/core):**
- Run the generator for `fan` domain → validate:
  - Output file exists at expected path
  - Contains `FanEntityFeature(IntFlag)` with correct members
  - Contains `FanAttributes(AttributesBase)` with expected fields
  - Contains `FanState(BoolBaseState)` with `domain: Literal["fan"]`
  - Contains `FanEntity(BaseEntity[FanState, str])` with service methods (turn_on, turn_off, set_percentage, etc.)
  - Passes `py_compile`
  - Passes `ruff check`

- Run the generator for `light` domain (most complex) → validate:
  - IntFlag in state file (not separate features.py)
  - All advanced_fields params appear in turn_on method signature
  - Color type override applied (color_name: Color)
  - Passes py_compile + ruff

- Run the generator for `sensor` domain (read-only, no services) → validate:
  - State model generated with NumericBaseState (via override)
  - NO entity wrapper generated (no services.yaml)
  - Constants file generated with DEVICE_CLASS, UNIT_OF_MEASUREMENT, STATE_CLASS

**Golden-file tests:**
- Commit expected output for `fan` domain as `codegen/tests/golden/fan_state.py` and `codegen/tests/golden/fan_entity.py`
- After generation, compare via `check_drift()` (ruff-normalized) against golden files
- These are intentionally brittle — they break when HA changes, which is the signal to update

**pyright verification:**
- After generating all domains, run `pyright --verifytypes hassette.models.states` and `hassette.models.entities`
- Assert exit code 0 (all public types are fully annotated)

**Performance test:**
- Time the full generation of all 30 domains
- Assert < 30 seconds on local checkout (AC#6 — tested here since T10's unit test mocks are fast)

## Focus
- Tests use the real HA core at `~/source/core` — they require the checkout to exist (skip with `pytest.mark.skipif` if not available)
- Golden files should be minimal — just fan (medium complexity, stable) is enough for golden comparison. Light is too volatile.
- `pyright --verifytypes` requires the generated files to be in place (importable) — run generation first, then pyright
- The 30-second performance target includes AST parsing + YAML loading + template rendering + ruff formatting for 30 domains. Ruff is the bottleneck — the test validates this doesn't regress.

## Verify
- [ ] FR#11: All generated output passes pyright strict mode and ruff formatting with zero errors
- [ ] AC#1: Running pyright --verifytypes + ruff check against generated output produces zero errors
- [ ] AC#5: Generated IntFlag enums match HA core definitions (same names, same values) — verified via fan golden file
- [ ] AC#6: Full generation of all 30 domains completes in under 30 seconds on a local checkout
