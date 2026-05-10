# Context: Entity Code Generator

## Problem & Motivation
Hassette maintains 30+ state models, 10+ entity wrappers, 7 feature flag enums, and sensor constants — all derived from Home Assistant core definitions. These are hand-written and drift silently as HA evolves. Each HA release can add entity properties, change service schemas, or introduce new entity platforms. Without automation, maintaining type safety requires hours of manual comparison per release and produces silent regressions when missed. The generator automates this entirely: one command regenerates everything from a pinned HA release.

## Visual Artifacts
None.

## Key Decisions
1. **No hassfest import** — HA core requires Python 3.14.2 and its full dependency tree. All extraction is static: PyYAML for services.yaml, AST for Python source. The generator itself must run on Python 3.14+.
2. **Manifest-based file ownership** — a `.generated-manifest` file lists every file the generator owns. Unlisted files are mechanically protected. No "DO NOT EDIT" headers.
3. **Auto-discovery of entity domains** — any HA component with `CACHED_PROPERTIES_WITH_ATTR_` and an Entity/ToggleEntity subclass is a target. No manual inclusion list.
4. **Feature enums colocated per-domain** — IntFlag enums live in the same file as their domain's state model (not a merged features.py).
5. **`__init__.py` fully generated** — scans all sibling modules (generated and non-generated) via static analysis. No fenced regions.
6. **Per-file validation** — files that fail ruff/py_compile are skipped with warnings, not blocking other domains.
7. **Standalone `codegen/` package** — own pyproject.toml, `requires-python = ">=3.14"`, installable as dev dependency.
8. **Sync facade consolidation** — `tools/generate_sync_facade.py` moves into codegen/ package; shared utilities (ruff pipeline, atomic write, drift check) become internal modules.
9. **Base class determined by AST heuristics** — ToggleEntity → Bool, numeric state return → Numeric, else String. Override table for ambiguous cases (sensor).
10. **CI runs as separate job** with Python 3.14, pinned HA version file, cached sparse clone.

## Constraints & Anti-Patterns
- Do NOT import any HA Python module at generation time (SyntaxError on Python < 3.14)
- Do NOT use "DO NOT EDIT" headers as a protection mechanism — the manifest is the single source of truth
- Do NOT implement anything in the Non-Goals section (doc pages, test fixtures, custom integrations, auto PR)
- Do NOT flatten all enums into a single features.py — they are per-domain
- Do NOT make `__init__.py` generation use fenced/marker regions — it's fully regenerated
- Do NOT use all-or-nothing write semantics — per-file validation, skip failures
- Generated files must be deterministic — same input always produces identical output
- Override files must be declarative TOML — no per-domain Python code

## Design Doc References
- `## Architecture` — tool structure, data flow, service extraction, type mapping, override system, manifest, CI integration
- `## Functional Requirements` — 23 FRs covering extraction, generation, validation, CI
- `## Edge Cases` — 13 specific edge cases to handle
- `## Test Strategy` — unit per extractor, integration against real HA domains, golden-file validation
- `## Key Constraints` — 5 hard constraints on implementation approach
