---
topic: "code generators and mixed generated/hand-written files in the same package"
date: 2026-05-10
status: Draft
---

# Prior Art: Code Generators Coexisting with Hand-Written Files

## The Problem

When a code generator produces files that live in the same package as hand-written code, you need a strategy that prevents three failure modes: (1) generator overwrites hand-written code on regeneration, (2) hand-written code gets orphaned when regenerated `__init__.py` drops its exports, (3) developer accidentally edits a generated file that gets overwritten next run. The harder constraint: the hand-written and generated files often need to share a package namespace (imports, re-exports, type registries).

## How We Do It Today

Hassette has no formal separation. The `states/` package mixes 38+ domain state files (which will become generated) alongside `simple.py`, `input.py`, `base.py`, and `features.py` (hand-written, no HA core source to generate from). The `__init__.py` is manually maintained with explicit imports and `__all__`. A `BaseState.__init_subclass__` hook auto-registers all state subclasses at import time, meaning all files must remain importable from the same package. The existing sync facade generator writes to a dedicated output path — it doesn't coexist with hand-written files in the same directory.

## Patterns Found

### Pattern 1: Separate Output Directory (Complete Isolation)

**Used by**: Buf (protobuf), gRPC-Go, many OpenAPI Generator configurations

**How it works**: Generated code lives in a dedicated `gen/` or `_generated/` directory. The entire directory can be deleted and recreated on each run. Hand-written code imports from the generated directory as a dependency. In Python, this means the generated subdirectory has its own `__init__.py` and the parent's `__init__.py` re-exports from both locations.

**Strengths**: Zero risk of overwriting. Clean regeneration (delete + recreate). Clear ownership. Easy to add CI rules ("no human edits in `_generated/`").

**Weaknesses**: Import paths get longer or require re-export layers. Can break automatic registration mechanisms (like `__init_subclass__`) if the registration happens at import time and the generated subpackage isn't imported early enough. Requires restructuring existing code.

**Example**: https://buf.build/docs/reference/cli/buf/generate/

### Pattern 2: Naming Convention Boundary (Suffix/Prefix)

**Used by**: Protocol Buffers (`_pb2.py`), SQLAlchemy teams, many internal tools

**How it works**: Generated files coexist in the same directory but use a distinctive suffix (e.g., `_pb2.py`, `_gen.py`). The generator only targets files matching its naming pattern. Hand-written files use different names.

**Strengths**: No extra directory hierarchy. Simple mental model. Works well when generated and hand-written code are tightly coupled. Easy to glob for CI checks.

**Weaknesses**: Relies on discipline — nothing mechanically prevents editing a generated file. `__init__.py` must import from both naming patterns. If hand-written files evolve to cover the same domain, naming collisions emerge.

**Example**: https://protobuf.dev/reference/python/python-generated/

### Pattern 3: Ignore File / Manifest (Selective Protection)

**Used by**: OpenAPI Generator (`.openapi-generator-ignore`), Swagger Codegen

**How it works**: A manifest file lists files the generator should never overwrite. OpenAPI Generator also writes a `.openapi-generator/FILES` list of everything it generated, providing a machine-readable record of ownership. Glob syntax allows patterns.

**Strengths**: Fine-grained. Familiar syntax. Allows gradual customization. The FILES manifest enables "stale file detection" — if a file is in FILES but no longer generated, it's orphaned.

**Weaknesses**: Requires manifest maintenance. Boundary is implicit (must read the file to understand). Can lead to "half-generated" files that drift.

**Example**: https://openapi-generator.tech/docs/customization/

### Pattern 4: Fenced Regions (Marker Comments)

**Used by**: mkinit (`# <autogen>` / `# </autogen>`), Qt Designer, WinForms

**How it works**: A single file (typically `__init__.py`) has marker comments delimiting generated vs hand-written sections. The generator only modifies content between markers.

**Strengths**: Single file to maintain. No separate directories. Clear visual boundary. Perfect for `__init__.py` where some exports are auto-generated and some are manual.

**Weaknesses**: Fragile if markers are deleted. Merge conflicts more likely. Only practical for "aggregation" files, not content files.

**Example**: https://github.com/Erotemic/mkinit

### Pattern 5: Generator Manifest (Explicit Ownership File)

**Used by**: OpenAPI Generator (`.openapi-generator/FILES`), emerging in modern generators

**How it works**: The generator maintains a file listing every path it owns. On regeneration: files in the manifest are overwritten freely; files NOT in the manifest are never touched; files in the manifest that the generator no longer produces are flagged as orphaned (and optionally deleted).

**Strengths**: Machine-readable ownership. Solves the orphan problem (stale files from removed domains). Solves the protection problem (unlisted files are safe). Enables "what changed" diffing.

**Weaknesses**: One more file to commit. Must be kept in sync. If the manifest is wrong, protection breaks.

**Example**: https://openapi-generator.tech/docs/customization/

## Anti-Patterns

- **"DO NOT EDIT" header as only protection**: No tooling programmatically respects this. It's documentation, not a mechanism. Always pair with a real boundary.
- **`--skip-overwrite` blanket flag**: Prevents updates to generated files when the schema changes. Files drift silently.
- **Subclassing generated classes**: Fragile base class problem. Protobuf explicitly warns against this. Use composition or companion modules.
- **Mixing generated and manual code in the same file without markers**: Guarantees data loss on regeneration.

## Relevance to Us

Hassette's constraint is unusual: `BaseState.__init_subclass__` auto-registers every state subclass at import time. This means all state files — generated or hand-written — must be importable from the same package to trigger registration. Pattern 1 (separate directory) works IF the parent `__init__.py` imports from both the generated subpackage and the hand-written files, triggering registration for both.

The existing structure has no naming convention distinguishing generated from hand-written state files (`light.py` looks like `simple.py`). Adding a suffix (`_gen.py`) would require renaming 30+ files and updating all imports — high cost.

**Best fit for our case:**
- **Pattern 3 (manifest)** for file-level ownership — the generator knows exactly which files it owns, never touches unlisted files, and can detect orphans.
- **Pattern 4 (fenced regions)** for `__init__.py` specifically — the generator updates its section of exports while preserving hand-written imports.
- These two combine naturally: manifest governs file-level ownership, fenced regions govern the shared `__init__.py`.

Pattern 1 (separate directory) would be cleaner architecturally but requires restructuring the existing package layout and ensuring `__init_subclass__` registration still fires for both locations.

## Recommendation

**Manifest + fenced regions** is the pragmatic choice:

1. A `.generated-files` manifest in `src/hassette/models/states/` (or the generator config) lists every file the generator owns. Files not in this list are never touched.
2. `__init__.py` uses fenced region markers. The generator rewrites the section between markers; hand-written imports above/below the markers are preserved.
3. The manifest enables orphan detection: if a domain is removed from HA core, the manifest flags its file for deletion.

This requires minimal restructuring — existing file paths stay the same, imports don't change, and `__init_subclass__` registration continues working because everything stays in the same package.

**Alternative worth considering:** If the team prefers a clean separation, Pattern 1 (separate `_generated/` subdirectory with `__init__.py` re-exporting into the parent namespace) is architecturally cleaner but requires a one-time migration of 30+ files and verifying that `__init_subclass__` fires correctly when the generated subpackage is imported.

## Sources

### Reference implementations
- https://buf.build/docs/reference/cli/buf/generate/ — Buf's separate output directory approach
- https://github.com/OpenAPITools/openapi-petstore/blob/master/.openapi-generator-ignore — OpenAPI ignore file example
- https://github.com/Erotemic/mkinit — Python __init__.py generator with fenced regions

### Blog posts & writeups
- https://erotemic.wordpress.com/2018/06/24/autogenerate-explicit-__init__-py-files-with-mkinit/ — mkinit fenced region pattern
- https://davecallan.com/run-scaffold-dbcontext-without-overwriting-custom-code-in-entity-framework-core/ — EF Core partial class pattern
- https://medium.com/@blackhorseya/streamlining-protobuf-code-generation-with-buf-in-golang-projects-b506316da7e2 — Buf gen/ directory pattern

### Documentation & standards
- https://protobuf.dev/reference/python/python-generated/ — Protobuf naming convention boundary
- https://grpc.io/docs/languages/python/generated-code/ — gRPC multi-file generation
- https://openapi-generator.tech/docs/customization/ — OpenAPI Generator ignore file + manifest
- https://alembic.sqlalchemy.org/en/latest/autogenerate.html — Alembic generate-once pattern
- https://docs.djangoproject.com/en/3.2/topics/migrations/ — Django migrations coexistence
- https://learn.scientific-python.org/development/patterns/exports/ — Python re-export patterns
