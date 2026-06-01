# Configuration — Applications

**Status:** Exists (68 lines), solid content, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: App Registration
How apps are registered in hassette.toml `[apps]` section.

### H2: Single Instance
Default single-instance configuration.

### H2: App Configuration Parameters
Two distinct layers: `AppManifest` fields (under `[hassette.apps.<key>]`: `enabled`, `filename`/`file_name`, `class_name`/`class`/`module`/`module_name`) vs `AppConfig` fields (under `[hassette.apps.<key>.config]`: `instance_name`, `log_level`, `app_key`, plus user-defined fields). These live at different TOML paths — don't conflate them in a single table.

### H2: Multiple Instances
Running the same app class multiple times with different configs.

### H2: Typed Configuration
Link to Apps/Configuration for AppConfig details.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| Relevant TOML examples | Review | May be inline rather than snippet files |

## Cross-Links

- **Links to:** Apps/Configuration, Configuration overview
- **Linked from:** Configuration overview, Apps overview
