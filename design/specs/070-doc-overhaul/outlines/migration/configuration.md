# Migration — Configuration

**Page type:** Migration (feature comparison)
**Reader's job:** Convert their AppDaemon YAML configuration files to Hassette's `hassette.toml` and typed `AppConfig` models.
**Voice mode:** Comparison — "you" allowed

## What was cut (and where it goes)

- **Benefits of Typed Configuration** section removed. The benefits are self-evident from the code examples (IDE autocomplete, validation at startup, defaults with constraints). Listing them as a sales pitch after the reader has already committed to migrating adds nothing.
- **Migration Steps** section merged into the per-app section. The existing page showed the same YAML-to-TOML conversion twice — once in the Global/Per-App sections and again in Migration Steps. One pass is enough.

## Outline

### H2: Global Configuration
Lead with the side-by-side conversion. The reader has `appdaemon.yaml` open and wants the TOML equivalent.

Side-by-side tabs:
- AppDaemon `appdaemon.yaml` snippet (HA URL, token, plugins)
- Hassette `hassette.toml` snippet (connection settings)

Note: the HA token comes from the `HASSETTE__TOKEN` environment variable or `.env`, not from `hassette.toml`.

### H2: Per-App Configuration
The bigger conceptual change: raw dicts become typed models.

Side-by-side tabs:
- AppDaemon `apps.yaml` snippet (module, class, args dict)
- Hassette `hassette.toml` + `AppConfig` class snippet

Show the before/after for config access: `self.args["args"]["entity"]` becomes `self.app_config.entity`. What the reader gains: missing fields raise an error at startup, IDE autocomplete works, Pydantic validators catch invalid values.

Admonition: `[[double brackets]]` — TOML array-of-tables syntax means multiple instances of the same app class with different configs.

### H2: Multi-Instance Apps
Brief: same app class, multiple rooms. AppDaemon repeats the `apps.yaml` block; Hassette repeats the `[[apps.my_app.config]]` block. One TOML snippet showing two instances. Link to App Configuration for the full reference.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `config_appdaemon_yaml.yaml` | Keep | AppDaemon global config |
| `config_migration_toml.toml` | Keep | Hassette global config |
| `config_apps_yaml.yaml` | Keep | AppDaemon per-app config |
| `config_appdaemon_access.py` | Keep | AppDaemon config access pattern |
| `config_hassette_toml.toml` | Keep | Hassette per-app config |
| `config_hassette_appconfig.py` | Keep | AppConfig class definition |

## Cross-Links

- **Links to:** App Configuration, Configuration overview, Global Settings, Applications
- **Linked from:** Migration overview, Migration checklist
