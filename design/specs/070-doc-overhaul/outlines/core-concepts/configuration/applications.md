# Application Configuration

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Register an app in `hassette.toml` and pass configuration values to it, including running multiple instances of the same app.

## What was cut (and where it goes)

- **"Typed Configuration" section** — kept as a one-sentence link. The Python side of `AppConfig` belongs on the Apps/Configuration page. This page covers the TOML side only.
- **"App Configuration Parameters" as a separate section from "App Registration"** — merged. The distinction between `AppManifest` fields and `AppConfig` fields is important but does not need two top-level sections. Show registration first (the reader's first task), then configuration (the second task), with a clear callout that they live at different TOML paths.

## Outline

### (Opening)
Apps are registered in `hassette.toml` under `[hassette.apps.<key>]`. Each block tells Hassette which Python file and class to load and passes configuration values to the app.

This page covers the TOML side of app configuration. For defining typed `AppConfig` models in Python, see Apps/Configuration.

### H2: Registering an App
Required fields: `filename` (or `file_name`) and `class_name` (or `class`/`module`/`module_name`). Optional: `enabled`, `display_name`. Show a single-instance TOML example.

Brief note: prefer `filename` and `class_name` in new configs; alternatives exist for compatibility.

### H2: Passing Configuration
`config` field supplies values to the app's `AppConfig` model.

Two TOML forms:
- Inline: `config = { key = "value" }`
- Table: `[hassette.apps.<key>.config]`

Callout: manifest fields (`filename`, `class_name`, `enabled`) live under `[hassette.apps.<key>]`. App config fields live under `[hassette.apps.<key>.config]`. Different TOML paths — do not conflate them.

Environment variable overrides: `HASSETTE__APPS__<APP_NAME>__CONFIG__<KEY>` pattern.

### H2: Multiple Instances
Running the same app class with different configurations using `[[hassette.apps.<key>.config]]` (TOML array of tables). Each block produces a separate app instance. Show a concrete example (same app, two rooms).

### H2: Typed Configuration
One-sentence link: the values supplied here are validated at startup against an `AppConfig` subclass defined in Python. Link to Apps/Configuration for how to define the model.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `single_instance.toml` | Keep | H2: Registering an App |
| `multiple_instances.toml` | Keep | H2: Multiple Instances |

## Cross-Links

- **Links to:** Apps/Configuration (Python `AppConfig` model), Configuration overview
- **Linked from:** Configuration overview, Apps overview
