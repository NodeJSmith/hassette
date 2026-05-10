---
task_id: "T06"
title: "Implement override system and manifest management"
status: "planned"
depends_on: ["T02"]
implements: ["FR#14", "FR#15", "FR#17", "AC#7", "AC#11", "AC#15"]
---

## Summary
Builds the declarative TOML override system and the manifest-based file ownership tracker. Overrides provide per-domain customization (renames, type coercions, extra imports, base class overrides). The manifest tracks which files the generator owns, prevents touching unlisted files, and detects orphans.

## Prompt
Create two modules:

**`codegen/src/hassette_codegen/overrides.py`:**
- Load all `.toml` files from `codegen/src/hassette_codegen/overrides/` at startup
- Parse each into a `DomainOverride` dataclass:
  - `service_param_renames: dict[str, str]` — old param name → new param name
  - `extra_imports: dict[str, list[str]]` — target ("entity"/"state") → import lines
  - `param_type_overrides: dict[str, str]` — param name → Python type string
  - `state_base_class: str | None` — override the AST heuristic
- Provide `get_override(domain: str) -> DomainOverride | None`
- Warn to stderr if an override references a domain not found in the discovered domain list
- Warn if `service_param_renames` references a param not found in the extracted service fields

Create initial override files:
- `codegen/src/hassette_codegen/overrides/light.toml` — extra_imports for Color, param_type_overrides for color_name
- `codegen/src/hassette_codegen/overrides/media_player.toml` — service_param_renames
- `codegen/src/hassette_codegen/overrides/sensor.toml` — state_base_class = "NumericBaseState"

**`codegen/src/hassette_codegen/manifest.py`:**
- Manifest file location: `.generated-manifest` at hassette repo root
- `load_manifest() -> set[Path]` — read the manifest, return owned file paths
- `save_manifest(owned: set[Path]) -> None` — write sorted paths with header comment
- `detect_orphans(previous: set[Path], current: set[Path]) -> set[Path]` — files in previous but not current
- `is_owned(path: Path, manifest: set[Path]) -> bool` — check if generator owns this file
- On first run (no manifest exists): treat as empty set (all files are new)

Unit tests in `codegen/tests/test_overrides.py` and `codegen/tests/test_manifest.py`:
- Override loading from TOML produces correct DomainOverride
- Unknown domain in override emits warning
- Manifest round-trip (save + load produces same set)
- Orphan detection identifies removed files
- `is_owned` returns False for unlisted files

## Focus
- TOML parsing uses Python 3.11+ stdlib `tomllib` (read-only) — no external dep needed
- The manifest path `.generated-manifest` is relative to the hassette repo root, not the codegen/ package
- Override files live inside the codegen package (`codegen/src/hassette_codegen/overrides/`) — shipped with the tool
- The warning for stale override entries (referencing removed HA params) needs the extracted service data — this module will be called AFTER extraction, with results passed in for validation

## Verify
- [ ] FR#14: Generated files are identified by the manifest — no in-file headers needed for ownership
- [ ] FR#15: Override TOML files are loaded and their contents (renames, type coercions, extra imports) integrated into generation without manual post-processing
- [ ] FR#17: Manifest tracks owned files; orphaned files are detected and flagged for deletion
- [ ] AC#7: Override file contents appear in final generated output automatically
- [ ] AC#11: File ownership is determined exclusively by the manifest
- [ ] AC#15: Running the generator never modifies files outside the manifest
