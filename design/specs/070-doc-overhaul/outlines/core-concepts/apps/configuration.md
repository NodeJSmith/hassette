# Apps — Configuration

**Status:** Exists (34 lines), very short, may need expansion
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Defining Config Models
AppConfig subclass with Pydantic SettingsConfigDict. How env_prefix maps to hassette.toml.

### H2: Base Fields
Fields inherited from AppConfig (instance_name, etc.).

### H2: Secrets & Environment Variables
Loading secrets from env vars via Pydantic.

## Snippet Inventory

Snippets from `apps/snippets/` that show config patterns — review and assign.

## Cross-Links

- **Links to:** Configuration/Applications (hassette.toml side), Apps overview
- **Linked from:** Apps overview, First Automation (step 2)
