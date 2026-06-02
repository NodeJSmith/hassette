# Web UI — Inspect Configuration and Code

**Status:** Stub (3 lines), needs full JTBD design from scratch
**Voice mode:** Procedural — "you" allowed, task-focused
**Page type:** Procedural (task-oriented)
**Reader's job:** Verify what configuration values Hassette is actually using at runtime, and read app source code in the browser without SSH access.

## What was cut

The old outline was organized by UI location (global config, app config, app
code). Reorganized around the two questions readers actually ask: "what config
is Hassette running with?" and "what does the app code look like right now?"

## Outline

### H2: Check Running Configuration
Why: you changed a config value and want to confirm Hassette picked it up, or
you need to verify what another user deployed.

#### H3: Global Configuration
The Configuration page shows all `hassette.toml` values grouped by section
(general, web_api, logging, etc.). Values are formatted for readability —
booleans, paths, lists are displayed with their types.

#### H3: Per-App Configuration
App detail > Config tab shows the resolved config for that app instance. This
is the Pydantic-validated result — it shows defaults that were applied, env
var overrides that took effect, and type-converted values.

Useful for debugging "I set this in the env but it's not taking effect" —
if the value doesn't appear here, the env var name is wrong or the field
name doesn't match.

### H2: Read App Source Code
App detail > Code tab shows the Python source of the app as deployed. Syntax
highlighted, read-only.

Use case: verifying what version of the code is running on a remote instance
without SSH access. Particularly useful in Docker deployments where the
container's app directory may differ from the development copy.

## Snippet Inventory

No code snippets — UI documentation.

## Cross-Links

- **Links to:** Web UI overview, Configuration (the config system), Apps/Configuration (AppConfig fields)
- **Linked from:** Web UI overview
