# Docker — Managing Dependencies

**Status:** Exists (193 lines), structure solid, voice polish needed
**Voice mode:** Getting-started — "you" allowed, procedural

## Outline

### H2: Overview
How Hassette's Docker entrypoint handles dependency installation at startup. Brief mental model.

#### H3: How Constraints Work
Hassette pins its own deps via constraints file to prevent conflicts.

### H2: How the Startup Script Works
What happens at container start: detect project type, install deps, launch. **`HASSETTE__INSTALL_DEPS=1`** must be set to activate dependency installation — without it, no requirements/pyproject install runs.

#### H3: Key Behaviors
Bulleted list of the script's decisions.

### H2: Understanding APP_DIR vs PROJECT_DIR
When to use which env var. Canonical env var: `HASSETTE__APPS__DIRECTORY` (legacy fallback: `HASSETTE__APP_DIR`). Table or short comparison.

### H2: Project Structures
#### H3: Simple Flat Structure
Directory layout, compose snippet.
#### H3: Traditional src/ Layout
Directory layout, compose snippet.

### H2: Using pyproject.toml
#### H3: With a Lock File (Required)
How uv.lock works in Docker context.

### H2: Using requirements.txt
Simpler alternative, when to use it.

### H2: Startup Performance
#### H3: Using uv.lock for Faster Starts
#### H3: Pre-building a Custom Image
Dockerfile example for baking deps into the image.
#### H3: Known Limitations — Local Path Dependencies

### H2: Complete Examples
Two full examples with compose + project structure.

## Snippet Inventory

All existing snippets (20+) are keeps — they demonstrate specific compose configurations and project structures. Full list:

| Snippet | Status |
|---|---|
| `deps-example1-compose.yml` | Keep |
| `deps-example1-requirements.txt` | Keep |
| `deps-example2-compose.yml` | Keep |
| `deps-example2-pyproject.toml` | Keep |
| `deps-flat-compose.yml` | Keep |
| `deps-flat-dir-structure.txt` | Keep |
| `deps-install-deps-env.yml` | Keep |
| `deps-requirements-dir-structure.txt` | Keep |
| `deps-src-compose.yml` | Keep |
| `deps-src-dir-structure.txt` | Keep |
| `deps-startup-flow.mmd` | Keep |
| `custom-image-compose.yml` | Keep |
| `custom-image.dockerfile` | Keep |
| `pyproject-example.toml` | Keep |
| `requirements-example.txt` | Keep |

## Cross-Links

- **Links to:** Docker Setup, Image Tags
- **Linked from:** Docker Setup (next steps), Docker Troubleshooting
