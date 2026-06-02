# Docker — Image Tags

**Status:** Rewrite from blank
**Voice mode:** Getting-started — "you" allowed, brief, decision-oriented
**Page type:** Reference (minimal)
**Reader's job:** Pick the right tag for their compose file
**One sentence:** "What do I put after the colon in `ghcr.io/...hassette:`?"

## What was cut

The original outline had tag format specs, a Python version table, and an
update procedure section. The reader needs a recommendation, not a specification.
Tag format details and version matrix belong in a reference page if they're
needed at all.

## Outline

### H2: Which Tag to Use
Two recommendations, that's it:

- **Production:** `v0.X.Y-py3.13` — pinned version, predictable
- **Development:** `latest-py3.13` — tracks the latest stable release

Show a compose snippet for each. One sentence explaining the difference.

### H2: Updating
`docker compose pull && docker compose up -d`. Two lines.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `tag-pinned-compose.yml` | Keep | Production recommendation |
| `tag-latest-compose.yml` | Keep | Dev recommendation |
| `docker-pull-update.sh` | Keep | Update command |
| `tag-format-versioned.txt` | Drop | Specification detail, not needed |

## Cross-Links

- **Links to:** Docker Setup
- **Linked from:** Docker Setup (next steps)
