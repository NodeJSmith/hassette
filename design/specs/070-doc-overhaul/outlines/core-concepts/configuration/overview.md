# Configuration — Overview

**Status:** Exists (46 lines), brief intro, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Configuration Sources
Priority order (highest wins): init kwargs → env vars (`HASSETTE__` prefix, `__` nested delimiter) → dotenv (.env) → file secrets → hassette.toml. TOML is the base; env vars override it.

### H2: Search Paths
TOML: `/config/hassette.toml`, `hassette.toml`, `./config/hassette.toml`. `.env`: `/config/.env`, `.env`, `./config/.env`. Docker `/config/` path is first.

### H2: Configuration Sections
Brief list of what's configurable, linking to sub-pages.

### H2: Credentials
Token and SSL configuration — links to Auth page.

## Snippet Inventory

No dedicated snippets — links to sub-pages for examples.

## Cross-Links

- **Links to:** Auth, Global Settings, Applications, Apps/Configuration
- **Linked from:** Architecture, Getting Started (Quickstart, Docker Setup)
