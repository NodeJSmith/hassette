# Design: Entity Code Generator

**Date:** 2026-05-10
**Status:** approved
**Scope-mode:** expand
**Research:** /tmp/claude-mine-define-research-Vj5q7M/brief.md, /tmp/claude-mine-prior-art-BR8Pos/codegen-feasibility.md

## Problem

Hassette maintains 10+ entity wrapper classes, 40-50+ state models, 7+ feature flag enums, and device class/unit constants — all derived from Home Assistant core definitions. These are currently hand-written and will drift as HA evolves. Each HA release can add entity properties, change service schemas, introduce new feature flags, or modify device class lists. Without automation, keeping these in sync requires manually comparing HA changelogs, reading source diffs, and updating dozens of files — a process that is error-prone, time-consuming, and produces silent type-safety regressions when missed.

## Goals

- Generate typed entity wrappers, state models, feature flag enums, and constants for 100% of HA core entity domains that have a `services.yaml` or entity class definition
- All generated output passes pyright strict mode with zero errors
- Detect drift between generated output and committed files in CI (non-zero exit on any difference)
- Reduce the cost of updating hassette for a new HA release from hours of manual comparison to a single command invocation followed by zero manual edits
- Domain-specific overrides are declarative files consumed by the generator — no human post-processing step required after generation

## Non-Goals (Phase 2)

- Generating documentation pages for entities (docs site integration)
- Generating test fixtures or mock data from entity definitions
- Supporting custom integrations outside HA core (only core entity platforms)
- Automatic PR creation when HA releases a new version (CI detects drift; humans decide when to update)

## User Scenarios

### Developer: Hassette maintainer
- **Goal:** Update hassette's typed models after a new HA release
- **Context:** HA has released a new version that adds properties, services, or entity types

#### Bump HA version

1. **Update the pinned HA core tag**
   - Sees: current pinned version in configuration
   - Decides: which HA release to target
   - Then: runs the generator against the new version

2. **Run the generator**
   - Sees: summary of what changed (new files, modified files, removed files)
   - Decides: whether the diff looks correct
   - Then: commits the regenerated output

3. **Verify in CI**
   - Sees: CI passes (generated output matches committed files)
   - Then: PR is ready for review

### Developer: New entity domain appears in HA
- **Goal:** Review and commit a newly-discovered entity domain after bumping the HA version
- **Context:** A new HA release introduces a new entity platform (e.g., `lawn_mower`) that the generator auto-discovers

#### New domain discovered

1. **Run the generator after version bump**
   - Sees: summary includes a new file that wasn't previously in the manifest
   - Decides: whether the generated output looks reasonable for the new domain
   - Then: if it needs an override (e.g., unusual base class), writes a TOML override and reruns

2. **Commit the new domain**
   - Sees: new state model + entity wrapper in the diff, manifest updated
   - Decides: whether to ship as-is or add documentation
   - Then: commits the new files alongside the version bump

### Developer: Handling generation failure
- **Goal:** Understand and resolve a domain that the generator cannot parse
- **Context:** HA has introduced a new pattern in a specific domain that breaks extraction

#### Unparseable domain

1. **Run the generator**
   - Sees: warning message naming the problematic domain and the extraction step that failed
   - Decides: whether the fix is an override file (data issue) or a generator code change (new pattern)
   - Then: all other domains generate successfully; the skipped domain retains its previous committed files

2. **Write an override file for the domain**
   - Sees: override file format documentation
   - Decides: what renames, type coercions, or exclusions to declare
   - Then: reruns the generator and the domain now generates correctly

### CI: Freshness enforcement
- **Goal:** Prevent drift between HA core definitions and committed hassette models
- **Context:** Any PR that touches entity/state/constant files or bumps the HA version pin

#### Drift detection

1. **CI runs generator in --check mode**
   - Sees: diff between generated output and committed files
   - Decides: (automated) pass if identical, fail if different
   - Then: blocks merge on failure with instructions to regenerate

## Functional Requirements

- **FR#1** The tool extracts IntFlag feature enums from HA core component `const.py` and `__init__.py` files and generates equivalent Python enums colocated with their domain's state model
- **FR#2** The tool extracts entity properties (names and types) from `CACHED_PROPERTIES_WITH_ATTR_` sets and `_attr_*` annotated class variables. Any `_attr_*` field declared without a default value is treated as `field_type | None = Field(default=None)` in the generated Pydantic model
- **FR#3** The tool parses service definitions from `services.yaml` via PyYAML (for field names, selectors, required/optional) and from `__init__.py` via AST (for schema structure), generating typed entity method signatures
- **FR#4** The tool generates Pydantic state model classes with typed attributes matching HA core's entity state representation
- **FR#5** The tool determines the correct state base class per domain via AST heuristics: ToggleEntity inheritance → BoolBaseState, numeric `state` property return type → NumericBaseState, otherwise → StringBaseState. An override table handles ambiguous cases (e.g., sensor)
- **FR#6** The tool generates `supports_*` property helpers on attribute classes from feature flag enum members
- **FR#7** The tool generates device class, unit of measurement, and state class constants from HA core definitions
- **FR#8** The tool accepts either `--ha-core-path` (local checkout) or `--ha-release-tag` (auto-clones at that tag) as the HA source
- **FR#9** The tool supports a `--check` mode that compares generated output against committed files and exits non-zero on drift
- **FR#10** The tool supports a `--domain` filter to regenerate specific domains only
- **FR#11** All generated output passes pyright strict mode and ruff formatting without modification
- **FR#12** The tool parses `services.yaml` directly with PyYAML for field definitions and selectors, and uses AST parsing on `__init__.py` for service registration schema structure (hassfest cannot be imported due to Python version and dependency constraints)
- **FR#13** The tool generates `__init__.py` export lists for state and entity modules
- **FR#14** Generated files are identified by the manifest (not by in-file headers) — the manifest is the single source of truth for which files the generator owns
- **FR#15** Domain-specific overrides are defined in declarative files (not inline code) that the generator reads and integrates into output automatically — no manual post-generation edits required
- **FR#16** When the tool encounters an unparseable domain (new pattern, malformed YAML, missing expected structure), it emits a warning and skips that domain. In `--check` mode, any skipped domain causes a non-zero exit (CI fails) to prevent silent staleness
- **FR#17** The generator maintains a manifest file listing every file it owns. Files not in the manifest are never touched. Orphaned files (in manifest but no longer generated) are flagged for deletion
- **FR#18** The generator produces complete `__init__.py` files by scanning all modules in the target package (both generated and non-generated), determining their public exports via static analysis, and producing a sorted import list covering everything
- **FR#19** On startup, the tool checks that `sys.version_info` meets HA core's `REQUIRED_PYTHON_VER` and fails with a clear error if the generator's Python is too old to AST-parse HA source files
- **FR#20** Each generated file is validated independently (ruff + py_compile) before writing. Files that pass validation are written; files that fail are skipped with a warning and their previous committed version is retained. The working tree is always valid — every written file passed validation
- **FR#21** Core entity domains are discovered automatically at generation time — any HA component with a class inheriting from Entity/ToggleEntity with `CACHED_PROPERTIES_WITH_ATTR_` is a target domain (no manual inclusion list)
- **FR#22** CI emits a warning (non-blocking) when the pinned HA version in `ha-version.txt` is behind HA's latest stable release (checked via GitHub releases API)
- **FR#23** The pinned HA version is displayed in the documentation site so users know which HA release hassette's typed models correspond to

## Edge Cases

- HA domain with no services (sensor, binary_sensor) — generates state model and attributes only, no entity methods
- HA domain with services but no feature flags (number) — generates entity with methods but no IntFlag enum
- Service params with preprocessor transforms (light's `preprocess_data`, media_player's `_rename_keys`) — handled via declarative override files
- `vol.Exclusive` groups (light color params) — does not enforce mutual exclusivity in generated code (HA validates at runtime)
- HA domain with multiple entity classes in one component (e.g., select, text) — generates one wrapper per entity class
- `_attr_*` fields with complex union types (e.g., `StateType | date | datetime | Decimal`) — maps to the full union type
- New HA domain added that doesn't match existing patterns — generator emits warning and skips domain
- Empty `services.yaml` or missing file — skip service method generation for that domain
- `--ha-release-tag` with invalid or non-existent tag — fail fast with clear error before any generation
- `--ha-release-tag` with network failure during clone — fail with error message including the URL attempted
- Domain with zero fields in services.yaml — generate entity method with no parameters (only entity_id targeting)
- ruff or pyright not available in environment — fail at startup with instructions to install, not mid-generation
- Override file references a domain or param that no longer exists in HA core — emit warning, skip that override entry

## Acceptance Criteria

- **AC#1** Running the tool against a pinned HA release tag produces output that passes `pyright --verifytypes` and `ruff check` with zero errors (FR#11)
- **AC#2** Running `--check` mode exits 0 when committed files are byte-identical (after ruff normalization) to generated output, and exits 1 with a file-by-file diff summary when they differ (FR#9)
- **AC#3** For each generated state model: the file contains a `{Domain}Attributes(AttributesBase)` class with fields matching HA core's `_attr_*` annotations (same names and types), and a `{Domain}State({Base}BaseState)` class with `domain: Literal["{domain}"]` (FR#4, FR#5)
- **AC#4** For each generated entity method: parameter names match the `fields:` keys in HA core's `services.yaml` for that service (after applying override renames), parameter types match the selector-to-Python mapping, and optional params default to `None` (FR#3)
- **AC#5** Generated feature flag enums match HA core's IntFlag definitions: same class name, same member names, same integer values (FR#1)
- **AC#6** The tool completes generation for all targeted domains in under 30 seconds on a local checkout (FR#8)
- **AC#7** Override files are read by the generator at generation time and their contents (renames, type coercions, extra imports) appear in the final output without manual intervention (FR#15)
- **AC#8** `--ha-release-tag` mode successfully shallow-clones and generates without requiring a pre-existing local checkout (FR#8)
- **AC#9** Running with `--domain fan` generates only fan-related files and leaves all other generated files untouched (FR#10)
- **AC#10** Generated `__init__.py` files export all state classes and entity classes in sorted order (FR#13)
- **AC#11** Generated files are tracked exclusively via the manifest — no in-file markers are required for ownership identification (FR#14)
- **AC#12** Generated attribute classes include `supports_{feature_name}` properties for each member of the domain's IntFlag enum (FR#6)
- **AC#13** When the tool encounters an unparseable domain, it prints a warning to stderr and continues generating all other domains. In `--check` mode, the exit code is non-zero if any domain was skipped (FR#16)
- **AC#14** The tool parses services.yaml with PyYAML and flattens nested sections (advanced_fields) into the method signature — verified by light.turn_on including all 10+ advanced_fields params (FR#12)
- **AC#15** The generator maintains a manifest listing owned files; running the generator never modifies files outside the manifest (FR#17)
- **AC#16** Generated `__init__.py` includes exports from both generated and non-generated modules (e.g., `simple.py`, `input.py`) — verified by the presence of `BinarySensorState` and `InputBooleanState` in the generated output (FR#18)
- **AC#17** Running the generator on Python < 3.14 against current HA core produces a clear startup error (not silent domain skips) (FR#19)
- **AC#18** If a generated file fails ruff or py_compile validation, it is skipped with a warning and its previous committed version is retained — other generated files that pass validation are still written (FR#20)

## Key Constraints

- Do not import hassfest or any HA Python module — HA core requires Python 3.14.2 and its full dependency tree; all extraction is static (AST + PyYAML) performed at generation time only
- The generator must run on Python 3.14+ to AST-parse current HA source files (which use PEP 758 syntax)
- Domain-specific overrides must be declarative TOML files in `codegen/src/hassette_codegen/overrides/` — no per-domain code, no post-generation manual edits
- Generated files must be deterministic — same HA input always produces identical output regardless of environment or execution order
- The generator must never touch files it does not own — a manifest governs file ownership; unlisted files (base.py, simple.py, input.py, colors.py) are protected

## Dependencies and Assumptions

- Home Assistant core repository available locally or cloneable via git tag
- Python 3.14+ available for running the generator (required to AST-parse HA source files using PEP 758 syntax)
- PyYAML and Jinja2 as dependencies of the `codegen/` package (isolated from hassette's runtime deps)
- ruff available for formatting (already in project dev dependencies)
- HA core maintains its current patterns (`CACHED_PROPERTIES_WITH_ATTR_`, `services.yaml`, `IntFlag` enums) — these are blessed patterns unlikely to change
- A pinned HA version file (`codegen/ha-version.txt`) identifies the target HA release for CI reproducibility

## Architecture

### Tool Structure

Standalone package at `codegen/` (repo root) with its own `pyproject.toml` and isolated virtual environment. NOT a dev dependency of hassette (incompatible Python version bounds — hassette requires <3.14, codegen requires >=3.14). Invoked via `cd codegen && uv run hassette-codegen`. Provides a `hassette-codegen` console script entry point.

```
codegen/
    pyproject.toml           # Package metadata, deps (jinja2, pyyaml), entry point
    src/hassette_codegen/
        __main__.py          # CLI entry point (argparse, --check, --ha-core-path/--ha-release-tag)
        __init__.py
        extractors/
            __init__.py
            features.py      # IntFlag enum extraction from const.py + __init__.py (AST)
            properties.py    # _attr_* and CACHED_PROPERTIES extraction (AST)
            services.py      # Service field extraction (PyYAML + AST hybrid)
            constants.py     # Device classes, units, state classes
            base_class.py    # Determines state base class via inheritance/return type heuristics
        generators/
            __init__.py
            states.py        # Generates state model .py files (Jinja2)
            entities.py      # Generates entity wrapper .py files (Jinja2)
            constants.py     # Generates const/*.py (Jinja2)
            exports.py       # Generates __init__.py via static analysis of sibling modules
        templates/
            state_model.py.j2    # Includes IntFlag enum + Attributes + State class
            entity_wrapper.py.j2
            constants.py.j2
            init_states.py.j2
            init_entities.py.j2
        type_mapping.py      # YAML selector → Python type mapping
        overrides/           # Domain-specific TOML override files
            light.toml
            media_player.toml
            sensor.toml
        manifest.py          # Tracks owned files, detects orphans
        ha_source.py         # HA core resolution (local path or git clone at tag)
        output.py            # Per-file validation, ruff formatting, drift checking
    ha-version.txt           # Pinned HA release tag for CI reproducibility
```

Invocation: `cd codegen && uv run hassette-codegen --ha-core-path ~/source/core` (uses codegen's own Python 3.14 venv, isolated from hassette's environment).

The existing `tools/generate_sync_facade.py` moves into this package (largely untouched) as a sibling generator. Its shared utilities (ruff pipeline, atomic write, drift checking) become internal modules that both generators use. Entry point: `hassette-codegen sync-facade [--check]`.

The pinned HA release tag starts at **2026.5.1** (latest stable as of design date).

### Data Flow

1. **Startup checks** — verify Python version ≥ HA's `REQUIRED_PYTHON_VER`; verify ruff available
2. **Resolve HA source** — validate `--ha-core-path` exists or shallow-clone `--ha-release-tag` (with 120s timeout)
3. **Load manifest** — read existing manifest to determine owned files
4. **Extract per domain** — for each targeted domain in `homeassistant/components/`:
   - `extractors/features.py` → AST-parses `const.py` AND `__init__.py` for IntFlag/StrEnum classes
   - `extractors/properties.py` → AST-parses `__init__.py` for `_attr_*` annotations and `CACHED_PROPERTIES_WITH_ATTR_`
   - `extractors/services.py` → parses `services.yaml` with PyYAML for field definitions + AST-parses `__init__.py` for service registration schema structure
   - `extractors/base_class.py` → checks ToggleEntity inheritance (→ Bool), `state` property return type (→ Numeric), fallback (→ String)
   - `extractors/constants.py` → collects device classes, units from HA helpers
5. **Merge and map types** — `type_mapping.py` converts YAML selectors to Python type annotations
6. **Apply overrides** — `overrides.py` provides per-domain renames, extra imports, type coercions, base class overrides
7. **Render templates** — Jinja2 templates produce `.py` file content (IntFlag enum colocated in state model file)
8. **Format and validate** — ruff format + ruff check + py_compile each file independently
9. **Write validated files** — files that pass validation are written to their target paths. Files that fail are skipped with a warning (previous committed version retained)
10. **Update manifest** — write updated manifest; flag orphaned files (previously generated, no longer produced)
11. **Generate __init__.py** — scan all modules in target packages (generated + non-generated), determine public exports via static analysis, produce complete sorted `__init__.py`

### Service Extraction (Hybrid PyYAML + AST)

hassfest cannot be imported (requires Python 3.14 + full HA dependency tree). Instead:

1. **PyYAML** parses `services.yaml` — gives field names, selectors (type info), required/optional, sections (advanced_fields). YAML anchors are resolved automatically by PyYAML.
2. **AST** parses `__init__.py` — gives `async_register_entity_service()` calls to confirm service names, method targets, and required feature flags per service.
3. **Section flattening** — when a top-level field entry has a `fields` key (section, e.g., `advanced_fields` in light), sub-fields are flattened into the service method parameters.

This hybrid gives the same data hassfest would provide, without the import dependency.

### Type Mapping Strategy

Two sources merged (YAML selectors are primary, AST annotations fill gaps):

| YAML Selector | Python Type |
|---|---|
| `number: {min: 0, max: 255}` | `int` |
| `number: {min: 0, max: 1, step: 0.01}` | `float` |
| `boolean:` | `bool` |
| `text:` | `str` |
| `select: {options: [...]}` | `Literal[...]` |
| `color_rgb:` | `tuple[int, int, int]` |
| `color_temp:` | `int` |
| `object:` | `Any` |
| `state:` | `str` |
| `entity:` | `str` |
| `area:` | `str` |
| `media:` | `dict[str, Any]` |
| `constant:` | `Any` |

Unknown selector types not in the mapping default to `Any` with a named warning emitted to stderr.

For entity properties, `_attr_*` AST annotations provide exact Python types directly. Fields declared without a default are widened to `type | None` with `Field(default=None)`.

### Override System

Declarative TOML files in `tools/entity_codegen/overrides/` — one per domain that needs special handling:

```toml
# codegen/src/hassette_codegen/overrides/light.toml
[extra_imports]
entity = ["from hassette.const.colors import Color"]

[param_type_overrides]
color_name = "Color"
```

```toml
# codegen/src/hassette_codegen/overrides/media_player.toml
[service_param_renames]
media_content_type = "media_type"
media_content_id = "media_id"
```

```toml
# codegen/src/hassette_codegen/overrides/sensor.toml
[state_base_class]
class = "NumericBaseState"  # Override AST heuristic (sensor returns str but value is numeric)
```

The generator loads all `.toml` files from the overrides directory at startup. If a domain has no override file, it generates without special handling. Override files that reference domains or params not found in the current HA core emit a warning.

### File Ownership (Manifest)

The generator maintains `.generated-manifest` in the project root listing every file it owns:

```
# Auto-maintained by hassette-codegen — do not edit
src/hassette/models/states/light.py
src/hassette/models/states/climate.py
src/hassette/models/states/fan.py
src/hassette/models/states/__init__.py
src/hassette/models/entities/light.py
src/hassette/models/entities/__init__.py
src/hassette/const/sensor.py
...
```

Domain module files NOT in this manifest are never touched (protects `base.py`, `simple.py`, `input.py`, `colors.py`).

`__init__.py` files ARE in the manifest (fully generated), but they include exports from all modules in the package — both generated and non-generated. The generator scans every `.py` file in the target directory, extracts public class names via static analysis (AST), and produces a complete sorted export list. This means `BinarySensorState` from `simple.py` appears in the generated `__init__.py` alongside `LightState` from the generated `light.py`.

### CI Integration

The generator requires Python 3.14+ and a pinned HA core checkout. CI strategy:

1. `codegen/ha-version.txt` contains the pinned HA release tag (e.g., `2026.5.1`)
2. CI reads this file, does a `--depth 1 --branch <tag>` sparse clone (only `homeassistant/components/`) with GitHub Actions cache keyed by the version tag
3. Generator runs as a **separate CI job** with Python 3.14 (not within hassette's test matrix). The `codegen/` package declares `requires-python = ">=3.14"` in its own `pyproject.toml`

```yaml
- name: Check entity codegen freshness
  run: |
    HA_TAG=$(cat codegen/ha-version.txt)
    # Clone cached by tag — see actions/cache step above
    cd codegen && uv run hassette-codegen --ha-core-path ${{ env.HA_CORE_CACHE }}/$HA_TAG --check
```

Note: This runs as a **separate CI job** with Python 3.14 (not within the hassette test matrix which uses 3.11-3.13). The `codegen/` package has its own `pyproject.toml` with `requires-python = ">=3.14"`, so `uv run` resolves Python 3.14 from the codegen package context, not hassette's.

The `--check` mode generates to a temp directory, compares each file against the committed version (both normalized through the same ruff binary), and exits 1 with a file-by-file diff summary on mismatch. Clone timeout is 120 seconds; on failure, the CI step fails with the URL and elapsed time.

## Alternatives Considered

### Import hassfest for service parsing

Use HA's own hassfest validation framework by adding `script/` to sys.path. Rejected because: (1) hassfest imports `homeassistant.*` which requires Python 3.14.2 and the full HA dependency tree (44+ packages), (2) `validate_services()` returns None — it's a validator, not a data extractor, (3) the services.yaml format is simple enough that PyYAML + 100 lines of selector mapping gives us the same data without any HA dependency.

### Runtime inspection (import HA core and introspect)

Import HA core as a package, instantiate platforms, inspect classes at runtime. Requires installing HA's massive dependency tree, fragile against version changes, and no advantage over static extraction for the data we need. Rejected.

### Separate generators per concern (4 scripts)

One script for features, one for states, one for entities, one for constants. Simpler per-script but duplicates CLI boilerplate, HA source resolution, and CI integration. A single tool with `--target` flag achieves the same flexibility without duplication.

### String-based code generation (like generate_sync_facade.py)

Use f-strings and textwrap instead of Jinja2. The sync facade does this for one output file. For 50+ output files across 4 different formats, string manipulation becomes unreadable — you can't see the shape of the output without mentally interpolating the template. Jinja2 templates are reviewable at a glance.

## Test Strategy

- **Unit tests per extractor** — test each AST extraction function against known HA component files (light, fan, sensor as representative domains)
- **Unit tests for type mapping** — cover all selector types and voluptuous validator patterns
- **Integration tests** — run the full generator against 3-4 domains (fan as "well-behaved", light as "complex", sensor as "read-only") and validate output passes py_compile + pyright
- **Golden-file validation** — for fan and sensor (stable, simple domains), commit expected output and assert byte-exact match after ruff normalization
- **`--check` mode test** — verify exit code behavior when files match and when they differ

## Documentation Updates

- `CLAUDE.md` — add generator invocation to "Common Commands" section
- `tools/README.md` (if exists) — document the generator's purpose and usage
- Docs site — display the pinned HA version (read from `ha-version.txt`) so users know which HA release the typed models correspond to. Could be a badge, a note in the entity docs, or a dedicated "compatibility" page

## Impact

Files affected:
- **New**: `codegen/` package (~10-12 source files, own pyproject.toml), templates (~5), override TOMLs (2-3), `.generated-manifest`, unit tests
- **Moved**: `tools/generate_sync_facade.py` → `codegen/src/hassette_codegen/sync_facade.py` (shared utilities extracted into internal modules)
- **Modified (regenerated, per manifest)**: `src/hassette/models/states/{domain}.py` (30+ domain files — IntFlag enum colocated), `src/hassette/models/entities/{domain}.py` (10+ files), `src/hassette/const/sensor.py`
- **Modified (fully regenerated via static analysis)**: `src/hassette/models/states/__init__.py`, `src/hassette/models/entities/__init__.py`
- **Never touched**: `base.py`, `simple.py`, `input.py`, `colors.py`
- **Deleted (prerequisite migration)**: `features.py` — enums move per-domain into generated state files. All imports (`from .features import XEntityFeature`) updated to per-domain paths (`from .light import LightEntityFeature`) in a one-time manual migration before the generator's first run. This is not a generator feature — it's a prep step
- **Modified (CI)**: `.github/workflows/lint.yml` (add codegen check step with Python 3.14)
- **New package**: `codegen/` at repo root with own venv (Python 3.14+, jinja2, pyyaml). NOT a hassette dev dependency — incompatible Python bounds. Invoked standalone via `cd codegen && uv run hassette-codegen`

Blast radius is high for generated files but bounded by the manifest — only listed files are modified. Hand-written files are mechanically protected.

## Open Questions

None — all resolved during design review.
