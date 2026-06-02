# Docker Setup

**Status:** Rewrite from blank
**Voice mode:** Getting-started — "you" allowed, step-by-step
**Page type:** Tutorial
**Reader's job:** Get Hassette running in a Docker container
**Aha moment:** `docker compose up` prints "Connected to Home Assistant"

## What was cut (and where it goes)

The original outline included Production Deployment (hot reload, graceful shutdown),
an env var reference table, and directory structure details. These are operations and
reference content — they belong in Operating or Configuration pages, not a tutorial.

The reader landing here has one job: get a container running and see it connect. Everything
else is a distraction from that job.

## Outline

### H2: Prerequisites
One-liner: Docker, Docker Compose, running HA, a token. Link to ha_token.md.

### H2: Quick Start
Four steps (not six — the original had unnecessary ceremony):

1. **Create the project** — `mkdir` the directory, create `apps/`, `config/`, `data/`
2. **Create `docker-compose.yml`** — minimal compose file with the four mounts
3. **Create `config/.env`** — token + base_url
4. **Start it** — `docker compose up -d`, check logs, see "Connected to Home Assistant"

That's it. The reader has a running container.

### H2: Write Your First App
Brief: create `apps/my_app.py` with the same minimal app from the local quickstart.
Restart the container, see the greeting in logs. Then link to First Automation
for the real stuff.

### H2: Next Steps
- First Automation — subscribe to events, control devices
- Managing Dependencies — add Python packages
- Image Tags — pick a production-ready tag
- Troubleshooting — if something went wrong

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `mkdir-project.sh` | Keep | Directory creation |
| `docker-compose.yml` | Keep | Minimal compose file |
| `env-file.sh` | Keep | .env with token + url |
| `my_app.py` | Keep | Minimal app |
| `docker-compose-up.sh` | Keep | Start command |
| `docker-compose-logs-hassette.sh` | Keep | Check logs |
| `hassette.toml` | Drop | Not needed for minimal setup if base_url is in .env |
| `dir-structure.txt` | Drop | Unnecessary — the steps show the structure |
| `docker-compose-logs.sh` | Drop | Redundant with hassette-filtered version |
| `prod-reload.toml` | Move to Operating | Production config, not getting-started |
| `uv-cache-volume.yml` | Move to Dependencies | Optimization, not getting-started |
| `uv-lock.sh` | Move to Dependencies | |

## Cross-Links

- **Links to:** HA Token, First Automation, Dependencies, Image Tags, Troubleshooting
- **Linked from:** Quickstart (alternative path), Evaluator
