# Docker — Managing Dependencies

**Status:** Rewrite from blank
**Voice mode:** Getting-started — "you" allowed, procedural
**Page type:** How-to
**Reader's job:** Add a Python package their apps need
**One sentence:** "I need `httpx` in my app — how do I get it into the container?"

## What was cut (and where it goes)

The original outline had 15 snippets, a Mermaid diagram of the startup script,
APP_DIR vs PROJECT_DIR comparison, two project structure layouts, performance
tips, and constraints file internals. The reader's job is "add a package" — they
don't need to understand the startup script to do that.

Startup script internals, constraints, APP_DIR vs PROJECT_DIR, and performance
tuning belong in an Operating or Advanced Docker page.

## Outline

### H2: Using requirements.txt
The simple path. Create `requirements.txt` in your project, add packages,
set `HASSETTE__INSTALL_DEPS=1` in compose, restart. Show the 3 files
(requirements.txt, compose snippet with env var, the app that imports the package).

This is the 80% case. Lead with it.

### H2: Using pyproject.toml
For projects that already have a pyproject.toml. Needs a `uv.lock` file.
Show: run `uv lock` locally, mount the project dir, set `HASSETTE__PROJECT_DIR`.

### H2: Known Limitations
- Local path dependencies (`file:///...`) don't work inside Docker
- First startup with new deps is slower (subsequent starts use the uv cache volume)

Link to Troubleshooting for "dependency installation fails" problems.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `requirements-example.txt` | Keep | Simple requirements file |
| `deps-install-deps-env.yml` | Keep | Compose with INSTALL_DEPS |
| `pyproject-example.toml` | Keep | pyproject.toml example |
| `deps-startup-flow.mmd` | Drop | Internals, not needed for the job |
| `deps-flat-compose.yml` | Drop | Redundant with main compose |
| `deps-flat-dir-structure.txt` | Drop | Unnecessary |
| `deps-src-compose.yml` | Drop | Advanced layout, not getting-started |
| `deps-src-dir-structure.txt` | Drop | Unnecessary |
| `deps-requirements-dir-structure.txt` | Drop | Unnecessary |
| `deps-example1-*` | Drop | Over-engineered for this page |
| `deps-example2-*` | Drop | Over-engineered for this page |
| `custom-image-*` | Drop | Future feature |

## Cross-Links

- **Links to:** Docker Setup, Troubleshooting
- **Linked from:** Docker Setup (next steps)
