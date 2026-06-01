# Migration — Configuration

**Status:** Exists (127 lines), comparison-driven, voice polish needed
**Voice mode:** Comparison — "you" allowed

## Outline

### H2: Overview
YAML-based (AppDaemon) → TOML + Pydantic (Hassette).

### H2: Global Configuration
#### H3: AppDaemon (`appdaemon.yaml`)
#### H3: Hassette (`hassette.toml`)

### H2: Per-App Configuration
#### H3: AppDaemon (`apps.yaml`)
#### H3: Hassette (`hassette.toml` + `AppConfig`)

### H2: Migration Steps
Step-by-step config conversion.

### H2: Benefits of Typed Configuration
Why the change is worth the effort.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| ~4 migration/config snippets | Keep | YAML vs TOML examples |

## Cross-Links

- **Links to:** Configuration overview, Apps/Configuration
- **Linked from:** Migration overview
