# Docker Setup

**Status:** Exists (173 lines), structure solid, voice polish needed
**Voice mode:** Getting-started — "you" allowed, step-by-step

## Outline

### H2: Prerequisites
Docker, Docker Compose, running HA instance. Brief.

### H2: Quick Start
Numbered steps: create directory, docker-compose.yml, .env, hassette.toml, first app, `docker compose up`. Each step produces visible progress.

### H2: Directory Structure
Show the resulting project layout after Quick Start.

### H2: Configuration
#### H3: Home Assistant Token
Link to ha_token.md, show where it goes in .env.
#### H3: Environment Variables Reference
Table of HASSETTE__* env vars.

### H2: Production Deployment
#### H3: Hot Reloading in Production
hassette.toml `allow_reload_in_prod` setting, volume mount requirements.
#### H3: Graceful Shutdown
Docker stop signal handling.

### H2: Viewing Logs
#### H3: Docker Compose Logs
`docker compose logs -f hassette` command.
#### H3: Web UI
Link to Web UI overview.

### H2: Next Steps
→ Dependencies, → Image Tags, → First Automation

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `docker-compose.yml` | Keep | Main compose file |
| `env-file.sh` | Keep | .env creation |
| `hassette.toml` | Keep | Minimal config |
| `my_app.py` | Keep | Example app |
| `dir-structure.txt` | Keep | Layout diagram |
| `docker-compose-up.sh` | Keep | Start command |
| `docker-compose-logs.sh` | Keep | Log viewing |
| `docker-compose-logs-hassette.sh` | Keep | Filtered logs |
| `prod-reload.toml` | Keep | Hot reload config |
| `mkdir-project.sh` | Keep | Directory creation |
| `uv-cache-volume.yml` | Keep | Cache volume mount |
| `uv-lock.sh` | Keep | Lock file generation |

## Cross-Links

- **Links to:** HA Token, Dependencies, Image Tags, Docker Troubleshooting, Web UI, First Automation
- **Linked from:** Quickstart (alternative path), Evaluator
