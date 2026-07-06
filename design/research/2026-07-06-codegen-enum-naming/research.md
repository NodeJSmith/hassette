---
proposal: "Fix codegen pipeline to produce consistent enum class names for state models, addressing casing and missing 'Entity' segment issues"
date: 2026-07-06
status: Draft
flexibility: Exploring
motivation: "Two generated state model files have naming inconsistencies — a casing mismatch in geo_location and a missing 'Entity' segment in water_heater — surfaced by CodeRabbit on PR #1197"
constraints: "Fix should make the pipeline produce correct names by construction, not just patch the two known cases"
non-goals: "none stated"
depth: normal
---

# Research Brief: Codegen Enum Naming Inconsistencies

**Initiated by**: Issue #1199 — fix naming inconsistencies in codegen state model output

## Context

### What prompted this

CodeRabbit flagged two naming inconsistencies in PR #1197 (HA 2026.7 state model regeneration). The generated files have mixed conventions:

1. `geo_location.py` has `GeolocationEntityStateAttribute` alongside `GeoLocationAttributes` and `GeoLocationState` — the StrEnum uses lowercase-l `Geolocation` while the Pydantic classes use uppercase-L `GeoLocation`
2. `water_heater.py` has `WaterHeaterCapabilityAttribute` and `WaterHeaterStateAttribute` (missing `Entity` segment) alongside `WaterHeaterEntityFeature` (which correctly includes it)

### Current state

The codegen pipeline constructs class names through **two independent paths** that do not coordinate:

**Path 1 — Template-generated names (consistent).** `domain_to_title()` in `codegen/src/hassette_codegen/domain_data.py` (line 15) converts domain strings to PascalCase: `domain_name.replace("_", " ").title().replace(" ", "")`. The Jinja template at `codegen/src/hassette_codegen/templates/state_model.py.j2` uses this to build `{domain_title}Attributes` (line 38) and `{domain_title}State` (line 62). These names are always internally consistent.

One override exists: `_TITLE_OVERRIDES = {"datetime": "DateTime"}` — without it, `str.title()` would produce `Datetime` (lowercase `t`).

**Path 2 — HA-verbatim names (the source of both bugs).** `extract_strenum()` and `extract_features()` in `codegen/src/hassette_codegen/extractors/features.py` walk HA core's AST and store class names via `node.name` (line 78 and line 44 respectively). No normalization is applied. The Jinja template renders these names verbatim via `{{ enum.name }}` (lines 23 and 31).

The two paths produce names that sit side-by-side in the same generated file but use different conventions for the same domain.

**The only post-extraction rename logic** is `_rename_collisions()` in `generators/states.py` (line 54), which appends `Value` when an HA StrEnum name collides with the Pydantic state class name (e.g., `AlarmControlPanelState` StrEnum becomes `AlarmControlPanelStateValue`). This handles a different concern entirely.

**Exports propagate automatically.** `generators/exports.py` AST-scans the generated `.py` files and builds `__init__.py` from whatever class names exist. No manual export list to update.

### Key constraints

- All affected files are auto-regenerated — no hand-edited code references these names (verified: no hits in `tests/`, `docs/`, or runtime `src/hassette/` outside `models/states/`)
- State catalog registration uses the `domain` literal from `Literal["geo_location"]` annotations, not class names — renames do not affect domain resolution
- The user wants the fix to be structural ("by construction"), not a patch for these two specific cases

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Enum rename logic | 1 file (`generators/states.py`) | Low | Low — isolated to generator, no runtime impact |
| Tests for rename | 1 file (`codegen/tests/test_state_generator.py`) | Low | None |
| Regenerated output | 3 files (`geo_location.py`, `water_heater.py`, `__init__.py`) | Low | Auto-generated |

### What already supports this

- `_rename_collisions()` already demonstrates the pattern of renaming extracted enums before template rendering — the infrastructure for modifying enum names post-extraction exists and works
- `domain_to_title()` already produces the canonical PascalCase prefix — the "correct" prefix is always available
- The Jinja template accepts whatever `enum.name` it receives — no template changes needed
- Exports regenerate automatically from the output files — no manual propagation
- No downstream consumers reference the buggy names — zero migration burden

### What works against this

- Detecting which enums are "domain-prefixed" (and therefore should be normalized) vs. standalone (like `ColorMode`, `HVACMode`) requires a heuristic — the extraction does not tag enums as domain-specific vs. independent
- HA core's naming is the upstream source of truth — renaming away from HA's names could confuse users who cross-reference HA docs, though hassette already diverges via `domain_to_title()` for Pydantic classes

## Root Cause Deep-Dive

Both bugs originate in HA core's own naming inconsistencies, which the codegen faithfully reproduces.

**geo_location casing.** HA core (`homeassistant/components/geo_location/const.py:6`) defines `GeolocationEntityStateAttribute` — treating "geolocation" as a single word with lowercase `l`. But the domain directory is named `geo_location` (with underscore), which `domain_to_title()` splits into two words: `Geo` + `Location` = `GeoLocation`. This is the only multi-word domain where HA's enum prefix casing diverges from what underscore-splitting produces. (Confirmed: `alarm_control_panel` = `AlarmControlPanel` in both paths, `binary_sensor` = `BinarySensor` in both, `media_player` = `MediaPlayer` in both, etc.)

**water_heater missing Entity.** HA core (`homeassistant/components/water_heater/const.py:8,17`) defines `WaterHeaterCapabilityAttribute` and `WaterHeaterStateAttribute` — uniquely omitting the `Entity` segment. A grep across all 40+ HA domains with these enum types confirms `water_heater` is the only domain that does this. Even `water_heater`'s own IntFlag (`WaterHeaterEntityFeature`) includes `Entity`, making the omission appear to be an HA-side oversight.

## Options Evaluated

### Option A: Systematic enum prefix normalization in the generator

**How it works**: Add a normalization pass in `generators/states.py` that runs after extraction and before template rendering. For each StrEnum, check whether its name starts with a variant of the domain title (case-insensitive comparison). If it does, replace the domain prefix with the canonical `domain_to_title()` output and ensure the `Entity` segment is present.

The detection logic:

1. Compute the canonical prefix: `domain_to_title(domain.name)` (e.g., `"GeoLocation"`, `"WaterHeater"`)
2. For each StrEnum, check if `enum.name.lower()` starts with `canonical_prefix.lower()` — this catches both exact matches (`WaterHeater...`) and casing variants (`Geolocation...`)
3. If matched, identify the known suffix pattern after the prefix: look for `Entity{Type}Attribute` or `{Type}Attribute` (where `Type` is `State` or `Capability`)
4. Reconstruct: `{canonical_prefix}Entity{Type}Attribute`

Concrete transforms:
- `GeolocationEntityStateAttribute` — prefix `Geolocation` matches `GeoLocation` (case-insensitive) — reconstruct as `GeoLocationEntityStateAttribute`
- `WaterHeaterCapabilityAttribute` — prefix `WaterHeater` matches — no `Entity` found — reconstruct as `WaterHeaterEntityCapabilityAttribute`
- `WaterHeaterStateAttribute` — same pattern — reconstruct as `WaterHeaterEntityStateAttribute`
- `ColorMode`, `HVACMode`, `StreamType` — prefix `Climate`/`Light` does not match — left untouched

**Pros**:
- Handles both known bugs and any future HA naming inconsistencies for domain-prefixed enums
- Fits the user's requirement of fixing "by construction"
- Works within the existing `_rename_collisions()` pattern — just another rename pass
- No configuration files to maintain

**Cons**:
- The case-insensitive prefix matching is a heuristic — could theoretically produce false positives if an HA enum's name happens to start with a domain title by coincidence (no such case exists today across 40+ domains)
- More complex than a static rename map — the suffix pattern detection needs to handle `EntityStateAttribute`, `EntityCapabilityAttribute`, `StateAttribute`, and `CapabilityAttribute`
- Renames away from HA's official class names, which could confuse users who read HA source

**Effort estimate**: Small — one function (~20-30 lines) in `generators/states.py`, plus unit tests in `test_state_generator.py`

**Dependencies**: None

### Option B: Explicit rename map

**How it works**: Add a `_ENUM_RENAMES` dictionary in `domain_data.py` (alongside `_TITLE_OVERRIDES`) that maps HA enum names to hassette enum names. Apply the renames in `generators/states.py` after extraction, before template rendering.

```python
_ENUM_RENAMES: dict[str, str] = {
    "GeolocationEntityStateAttribute": "GeoLocationEntityStateAttribute",
    "WaterHeaterCapabilityAttribute": "WaterHeaterEntityCapabilityAttribute",
    "WaterHeaterStateAttribute": "WaterHeaterEntityStateAttribute",
}
```

**Pros**:
- Simplest implementation — a dict lookup and a 3-line function
- Explicit and readable — no heuristics, no false-positive risk
- Follows the existing `_TITLE_OVERRIDES` pattern

**Cons**:
- Requires manual maintenance when HA introduces new naming inconsistencies
- Does not satisfy the user's stated preference for fixing "by construction"
- Each HA version update could introduce new inconsistencies that silently pass through

**Effort estimate**: Small — ~5 lines of code plus tests

**Dependencies**: None

### Option C: Align hassette convention to HA (reverse direction)

**How it works**: Instead of normalizing HA names to match hassette's convention, adjust hassette's convention to match HA. For `geo_location`, add `"geo_location": "Geolocation"` to `_TITLE_OVERRIDES` so template-generated names use `GeolocationAttributes` and `GeolocationState` (matching HA's `GeolocationEntityStateAttribute`).

**Pros**:
- Eliminates the casing inconsistency for geo_location with a one-line change
- Template-generated names match HA source, reducing cross-reference confusion

**Cons**:
- Cannot fix the water_heater issue — the missing `Entity` segment is in the HA-verbatim path, not the template path. A title override changes `WaterHeaterAttributes` to... still `WaterHeaterAttributes` (no effect)
- Surrenders hassette's consistent naming convention (`domain_to_title` produces predictable output) to HA's inconsistency
- Only a partial fix — still needs Option A or B for water_heater

**Effort estimate**: Small (but incomplete — only fixes 1 of 2 bugs)

**Dependencies**: None

## Concerns

### Technical risks

- **False-positive prefix matching (Option A only)**: A StrEnum whose name coincidentally starts with the domain title but is not domain-prefixed would be incorrectly renamed. Risk is low — surveyed all 40+ domains and no such case exists. The suffix pattern check (`*StateAttribute`, `*CapabilityAttribute`) further narrows the match. Enums like `ColorMode`, `HVACMode`, `StreamType` have completely different suffixes and would not match.
- **HA upstream renames**: If HA fixes its own naming inconsistencies in a future release, Option A would produce the same correct output (the normalization is idempotent — `GeoLocationEntityStateAttribute` stays `GeoLocationEntityStateAttribute`). Option B would have a stale entry in the rename map that never matches.

### Complexity risks

- Option A adds ~20-30 lines of logic that future maintainers need to understand. The motivation ("HA sometimes names enums inconsistently") should be documented in a code comment.
- The interaction between `_rename_collisions()` (existing) and the new normalization pass needs clear ordering: normalize first, then check for collisions with the Pydantic class name.

### Maintenance risks

- Option B creates an ongoing maintenance obligation: each HA version update requires checking whether new inconsistencies were introduced. Option A handles this automatically.
- Both Options A and B create a divergence from HA's upstream names. If hassette users look up `WaterHeaterEntityCapabilityAttribute` in HA docs, they will find `WaterHeaterCapabilityAttribute` instead. This is a documentation/discoverability concern, not a correctness concern.

## Open Questions

- [ ] **Which direction should the normalization go?** The issue assumes hassette's convention wins (normalize HA names to match `domain_to_title()`). The alternative is aligning hassette to HA (Option C). This is a product decision about whose naming convention takes precedence.
- [ ] **Should standalone enums like `TrackerEntityStateAttribute` and `ScannerEntityStateAttribute` (in `device_tracker`) also be normalized?** These are domain-specific but not prefixed with `DeviceTracker`. The current approach (Options A/B/C) would leave them untouched, which is likely correct — they represent sub-entity types, not the domain itself.
- [ ] **Should a CI check be added to detect future naming inconsistencies?** A lint step could compare extracted enum prefixes against `domain_to_title()` output and flag mismatches during codegen, surfacing them at generation time rather than at code review.

## Recommendation

**Option A (systematic prefix normalization)** is the best fit for the stated constraints. It fixes both known bugs, handles future HA inconsistencies automatically, and satisfies the "by construction" requirement. The implementation is small (~20-30 lines), risk is low (no false positives across current HA domains, idempotent if HA fixes its naming), and it extends an existing pattern (`_rename_collisions`).

Option B is a defensible fallback if the heuristic approach feels too clever — it trades ongoing maintenance for simplicity. Option C is incomplete and should not be pursued alone.

### Suggested next steps

1. Implement Option A in `codegen/src/hassette_codegen/generators/states.py` — add a `_normalize_enum_prefixes()` function that runs before `_rename_collisions()`
2. Add unit tests in `codegen/tests/test_state_generator.py` covering: geo_location casing fix, water_heater Entity insertion, no-op for correctly-named enums, no-op for standalone enums like `ColorMode`
3. Regenerate affected state models and verify the output matches expectations

## Key Files

| File | Role |
|------|------|
| `codegen/src/hassette_codegen/domain_data.py` (lines 10-19) | `_TITLE_OVERRIDES` dict and `domain_to_title()` function |
| `codegen/src/hassette_codegen/extractors/features.py` (lines 50-81) | `extract_strenum()` — uses `node.name` verbatim from HA AST |
| `codegen/src/hassette_codegen/generators/states.py` (lines 23-26, 54-66) | `generate_state_model()` — where `domain_title` is computed and `_rename_collisions()` runs |
| `codegen/src/hassette_codegen/templates/state_model.py.j2` (lines 23, 31) | Template renders `{{ enum.name }}` verbatim |
| `codegen/tests/test_state_generator.py` | Existing state generator tests (no naming-specific tests yet) |
| `src/hassette/models/states/geo_location.py` | Generated output with casing mismatch |
| `src/hassette/models/states/water_heater.py` | Generated output with missing Entity segment |
| `~/source/core/homeassistant/components/geo_location/const.py` | HA source: `GeolocationEntityStateAttribute` |
| `~/source/core/homeassistant/components/water_heater/const.py` | HA source: `WaterHeater{Capability,State}Attribute` (no Entity) |
