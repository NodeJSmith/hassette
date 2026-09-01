---
proposal: "Auto-widen int attribute types to int | float in hassette's codegen pipeline when HA platform implementations aren't provably int-only"
date: 2026-09-01
status: Draft
flexibility: Leaning
motivation: "Pydantic validation crashes in production when HA platforms return floats for int-typed attributes (confirmed: media_player.media_duration with fractional seconds)"
constraints: "Must integrate into existing codegen pipeline without breaking the override escape hatch; must not widen fields that are genuinely always int (e.g. media_track)"
non-goals: "Runtime coercion/truncation of float values; blanket float typing for all numeric attributes"
depth: normal
---

# Research Brief: Auto-Widen Int Attribute Types to Float

**Initiated by**: Issue #1751 -- auto-widen `int` attribute types to `int | float` when HA platform implementations assign floats

## Context

### What prompted this

HA core's base entity classes annotate numeric attributes as `int`, but individual platform integrations routinely assign `float` values without casting. The confirmed crash: `media_player.media_duration` received `3600.073313` from a platform, and Pydantic's `int` validator raised `int_from_float`. An audit referenced in the issue found 136 unsafe assignment sites across multiple fields and domains.

### Current state

The codegen pipeline (`codegen/src/hassette_codegen/pipeline.py`) reads HA core's base entity class annotations via `extract_properties()` (`extractors/properties.py`), which AST-parses the domain's `__init__.py` and copies the declared type verbatim as a string into `ExtractedProperty.python_type`. There is no numeric type analysis or cross-platform validation -- the base class says `int`, so the generated Pydantic model gets `int | None`.

The pipeline already has a manual override mechanism (`overrides.py` + per-domain TOML files in `overrides/`) that can retype any field via `PropertyOverride.type`. Overrides run after property extraction (pipeline.py:598, after extraction at line 594), so they would naturally take precedence over an automated widening step inserted between the two.

Notably, `int | float | None` is already an established convention in the generated models -- `supported_features` (base.py:47), `battery_level` and `gps_accuracy` (device_tracker.py), and several fields in automation, script, input, and update models already use this union type. The proposed widening would extend an existing pattern, not introduce a new one.

### Key constraints

- The override TOML escape hatch must remain authoritative over the heuristic (already satisfied by pipeline ordering)
- Fields provably int-only across all platforms (e.g. `media_track`) must remain `int`-only
- No data-loss coercion (truncating 3600.07 to 3600 is rejected by the issue's own design rationale)

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| New extractor module | 1 new file (`extractors/type_widening.py`) | Med | Core heuristic correctness -- edge cases in AST classification |
| Pipeline integration | 1 file (`pipeline.py`, 2-3 lines) | Low | Minimal -- insertion point is clean, `ha_core_path` already available |
| Generated state models | 5 files (`light.py`, `fan.py`, `media_player.py`, `weather.py`, `cover.py`) | Low | Output of re-running codegen, not manual edits |
| Codegen tests | 1-2 files (`test_extractors.py` or new `test_type_widening.py`) | Med | Needs real HA core fixture data; infrastructure already exists |
| Regression test | 1 file (`tests/unit/test_state_attributes.py`) | Low | Straightforward fractional-value acceptance test |

**Actual field count: 8 fields across 5 domains** (not 6 as stated in the issue):
- `media_player`: `media_duration`, `media_position` (not `media_track` -- stays int)
- `light`: `brightness`, `color_temp_kelvin`
- `fan`: `percentage`
- `cover`: `current_cover_position`, `current_cover_tilt_position`
- `weather`: `cloud_coverage`

### What already supports this

1. **Pipeline architecture is ready.** `ha_core_path` is already a parameter of `_extract_domain()` (line 581) but currently unused inside it -- it exists precisely for cross-platform scanning. The insertion point between `extract_properties()` (line 594) and `apply_property_overrides()` (line 598) is clean with no ordering risk.

2. **Override escape hatch works without modification.** `apply_property_overrides()` runs after extraction and does simple string replacement on `python_type`. A widening step before it means overrides always win -- no new code needed in `overrides.py`.

3. **`python_type` is an opaque string.** The generators (`generators/states.py`) render it verbatim into Pydantic model source. Changing `"int"` to `"int | float"` requires zero downstream generator changes.

4. **Established convention.** Multiple generated fields already use `int | float | None`. This is not a novel type pattern.

5. **Zero downstream consumers.** No code in `src/hassette/`, `tests/`, `frontend/`, or the OpenAPI export pipeline performs `isinstance(x, int)`, int-specific arithmetic, or int-only serialization on any of the 8 affected fields. The frontend type generation pipeline does not touch state models at all. Pydantic v2's smart union mode handles `int | float` transparently -- integer inputs stay `int`, fractional inputs become `float`.

6. **Codegen test infrastructure is ready.** `codegen/tests/test_extractors.py` already has HA-core-gated test classes, and the local checkout at `~/source/core` means tests will execute (not skip). The pattern for adding a `TestTypeWidening` class is established.

### What works against this

1. **The AST heuristic has real gaps.** Sampling 17 assignment/return sites across 8 HA platforms for `media_duration`/`media_position` revealed that the proposed classification rules don't cover all expression shapes found in practice. Details in the Options section below.

2. **Third-party library types are opaque.** ~47% of sampled sites (8/17) are raw attribute access on objects from external libraries (`plexapi`, `pychromecast`, etc.). The scanner can flag these conservatively but cannot confirm whether widening is actually needed -- it's a defensible hedge, not a proven classification.

3. **The int/float binary framing has a structural blind spot.** At least one HA platform (mpd) returns `str` at runtime for `media_duration`, which the int/float heuristic can't represent or detect. Widening to `int | float` would not fix that site.

## Options Evaluated

### Option A: AST-based type widening (the proposed approach)

**How it works**: A new module `extractors/type_widening.py` exports `widen_float_risk_types(properties, domain, ha_core_path)`. For each `ExtractedProperty` with `python_type` containing bare `int`, it globs `ha_core_path/homeassistant/components/*/DOMAIN.py`, AST-parses each platform file, and scans for `self._attr_FIELD = ...` assignments and `def FIELD(self) -> ...: return ...` property returns. Each site is classified as "provably int" or "float-risky." If any site for a field is float-risky, the field's type is widened from `int` to `int | float`.

The heuristic validation against real HA core code produced these results across 17 sampled sites:

**Reliably correct (5 sites):** `int()` casts, `round()` wraps, and `/` division all classified correctly every time. These are the heuristic's strong patterns.

**Conservative hedges, unverifiable (8 sites):** Raw attribute access on third-party objects (`self.media.position`, `self.coordinator.data.media.duration`). The scanner would flag these as float-risky, which is a safe default -- it may over-widen some fields, but over-widening (`int | float` where `int` alone would suffice) is harmless since `int` is a subtype of `int | float` in Pydantic's smart union mode.

**Likely false positives (2 sites):** Kodi's dict-subscript arithmetic (`hours * 3600 + minutes * 60 + seconds`) matches neither the "provably int" rules nor the named "float-risky" patterns. If unmatched expressions default to float-risky (the safe default), these are false positives -- the values are genuinely always int. Harmless in practice (over-widening).

**Likely false negative (1 site):** VLC's `media_position` uses multiplication (`get_position() * self._attr_media_duration`), which produces `float` but isn't covered by the heuristic (only `/` is listed, not `*`). This is a real gap.

**Category miss (1 site):** MPD returns `str` for `media_duration` via `.get()` and `.split()`. The int/float binary taxonomy cannot represent this. The widening fix wouldn't help here regardless.

**Heuristic refinements suggested by the data:**
- Add `*` to the float-risky operators alongside `/` -- catches VLC's false negative
- Classify by outermost expression node, not by scanning for any sub-expression (Spotify's `round(item.duration_ms / 1000)` is provably int despite containing `/` inside the `round()`)
- Recurse into `IfExp` (ternary) branches -- several platforms wrap the return in `x if cond else None`
- Walk instance method bodies (especially `update()`, `async_update()`), not just class-body assignments -- VLC's float-producing division is inside `update()`, not at class level
- Default unmatched expression shapes to float-risky (safe over-widening) rather than provably-int

**Pros**:
- Catches drift automatically as HA core evolves -- new platforms adding float assignments to int-typed fields get detected without manual auditing
- Self-documenting: the widening decision traces back to specific platform code, not a manual "we think this might be float" judgment
- Low downstream risk: zero consumers, established type pattern, transparent Pydantic behavior
- Clean integration: no signature changes, no generator changes, override escape hatch works without modification

**Cons**:
- AST scanning is inherently approximate -- third-party library types are opaque, and some expression shapes require heuristic defaults rather than proven classification
- Adds ~200-400 lines of new code (the scanner) for a problem that currently affects 8 known fields
- Scanning ~100+ platform files per domain adds latency to codegen runs (no timing data available, but the issue's audit scanned 963 sites total, so the per-domain glob is non-trivial)
- The string-typed edge case (mpd) is outside the heuristic's detection capability entirely

**Effort estimate**: Medium -- the scanner itself is the bulk of the work; pipeline integration, test infrastructure, and generated-output changes are all low-effort

**Dependencies**: None new -- uses only stdlib `ast` and `pathlib`, plus the existing `ExtractedProperty` dataclass

### Option B: Hand-maintained override TOML for the 8 known fields

**How it works**: Add `[[property_overrides]]` entries to the existing per-domain TOML files (`media_player.toml`, `light.toml`, `fan.toml`, `cover.toml`, `weather.toml`) with `type = "int | float | None"` for each affected field. No new code, no AST scanning.

**Pros**:
- Zero new code -- uses only existing, tested infrastructure
- Each widened field is an explicit, reviewable decision
- No false positives or false negatives -- every override is manually verified

**Cons**:
- Does not scale: future HA core changes that add new float-risky fields won't be caught automatically -- requires manual auditing each time HA updates
- The issue explicitly rejects this approach: "Neither approach scales past the fields we happen to notice"
- 8 TOML entries across 5 files is a small diff but a recurring maintenance burden

**Effort estimate**: Small -- 8 lines of TOML across 5 existing files, plus a regression test

### Comparison

Option A is more work upfront but catches future drift automatically. Option B is a quick fix for the known fields but requires ongoing vigilance. The issue leans toward Option A, and the codebase investigation confirms the integration point is clean enough that the additional complexity is bounded. The main risk in Option A is heuristic edge cases, but the "default to float-risky" strategy means false positives (harmless over-widening) are far more likely than false negatives (missed unsafe sites).

A pragmatic hybrid is also possible: ship Option B immediately for the 8 known fields (quick fix), then build Option A as a follow-up that validates and eventually replaces the manual overrides. This de-risks the AST scanner by giving it a known-good baseline to test against.

## Concerns

### Technical risks

- **Heuristic edge cases are real, not hypothetical.** The sampling found 1 false negative (multiplication not covered) and 2 false positives (dict-subscript arithmetic defaults to risky) in 17 sites. The false negative is fixable by adding `*` to the risky-operator list. The false positives are harmless (over-widening). The heuristic will need the refinements listed above to avoid the VLC-style false negative.
- **The string-typed edge case (mpd returning `str` for `media_duration`) is outside scope.** The int/float heuristic cannot detect or fix this. It's a separate bug in the mpd platform, not a flaw in the widening approach, but worth noting that the widening won't catch every type mismatch between base-class annotations and platform reality.

### Complexity risks

- The AST scanner adds a new analysis layer to the codegen pipeline that future maintainers need to understand. The `extractors/` directory already has 5 modules (`properties.py`, `features.py`, `constants.py`, `base_class.py`, `services.py`), so a 6th is consistent with the existing structure, but the total surface grows.
- "Provably int" classification requires careful outermost-node analysis (not naive sub-expression scanning) to avoid misclassifying `round(x / 1000)` as risky. This subtlety is a maintenance burden.

### Maintenance risks

- The scanner depends on HA platform code following recognizable assignment patterns (`self._attr_X = ...`, `@property def X(self): return ...`). If HA core introduces new patterns (e.g., descriptor-based attributes, `__init_subclass__` wiring), the scanner would need updates.
- The HA core checkout at `~/source/core` must be kept reasonably current for the heuristic to reflect actual platform behavior. Stale checkout = stale classifications.

## Open Questions

- [ ] **Should `*` (multiplication) be added to the float-risky operator list?** The VLC false negative suggests yes, but this may increase false positives for platforms that do integer-only arithmetic. Sampling more domains (beyond media_player) would clarify the false-positive rate.
- [ ] **What's the acceptable codegen performance budget?** Scanning ~100+ platform files per domain via AST parsing adds latency. Is sub-second-per-domain acceptable, or does the scanner need caching/parallelization?
- [ ] **Should the mpd string-typed edge case be tracked separately?** It's outside the int/float widening scope but represents a real production risk (Pydantic would also reject a string for an `int | float`-typed field).
- [ ] **Should the hybrid approach (Option B now, Option A follow-up) be considered, or go straight to Option A?** The issue leans toward A directly, but the known-field list is small enough that B could ship as an interim fix in a single PR while A is developed.

## Recommendation

The proposed AST-based approach (Option A) is feasible and well-supported by the existing codebase architecture. The integration point is clean, downstream impact is zero, and the type pattern is already established in other generated fields.

The heuristic needs refinement beyond what the issue describes -- specifically, adding `*` to risky operators, classifying by outermost expression node, recursing into ternary branches, and walking instance method bodies. These are implementation details, not design flaws -- the core approach of "scan platform code, classify assignment sites, widen when any site is risky" is sound.

The "default unmatched expressions to float-risky" strategy is the right call: false positives (unnecessary `| float` on a genuinely-int field) are harmless in Pydantic's smart union mode, while false negatives (missing a float-producing site) are the actual production crash the issue exists to prevent.

The field count is 8 across 5 domains, not 6 as stated in the issue -- `light.color_temp_kelvin` and `cover.current_cover_tilt_position` were missed in the issue's enumeration.

### Suggested next steps

1. Write a design doc via `/mine-define` covering the heuristic refinements identified here (multiplication operator, outermost-node classification, ternary recursion, method body walking) -- these details matter for correctness and aren't fully specified in the issue.
2. Consider shipping the 8 known-field overrides (Option B) as a quick fix first, providing an immediate safety net while the AST scanner is developed and validated against them.
3. File a separate issue for the mpd string-typed edge case -- it's a real bug but outside the int/float widening scope.
