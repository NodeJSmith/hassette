# Quickstart

**Status:** Rewrite from blank
**Voice mode:** Getting-started — "you" allowed, code-first, numbered steps

## Outline

### H2: Prerequisites
Python 3.11+, uv, running HA instance. Brief — links to Docker Setup for containerized alternative.

### H2: Steps 1–7 (numbered)
Keep current numbered-step structure. Each step produces visible progress.
1. Create a project and install Hassette
2. Create a project layout
3. Create a Home Assistant token (links to ha_token.md)
4. Create `config/.env`
5. Create `config/hassette.toml`
6. Create your first app
7. Run Hassette

Step 6 keeps a minimal app (no DI yet — that's first-automation's job). Step 7 shows expected output.

### H2: Next Steps
→ First Automation (DI, bus, scheduler), → Docker Setup (production)

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `install.sh` | Keep | uv add hassette |
| `project_layout.sh` | Keep | directory structure |
| `env_file.sh` | Keep | .env creation |
| `hassette.toml` | Keep | minimal config |
| `first_app.py` | Rewrite | Check voice — may need DI note or just keep minimal |
| `run.sh` | Keep | hassette run |
| `run_output.txt` | Rewrite | Update if startup output has changed |
| `run_explicit.sh` | Keep | explicit module run |

## Cross-Links

- **Links to:** HA Token, First Automation, Docker Setup
- **Linked from:** Evaluator, Home page
