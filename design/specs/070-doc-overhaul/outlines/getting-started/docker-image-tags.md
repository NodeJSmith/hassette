# Docker — Image Tags

**Status:** Exists (151 lines), needs trimming for getting-started audience
**Voice mode:** Getting-started — "you" allowed, brief, decision-oriented

## Outline

### H2: Tag Format
Brief explanation of the naming convention. One recommended tag example.

### H2: Recommended Tags
#### H3: Production — pin version + Python (e.g., `v0.35.0-py3.13`)
#### H3: Development — track latest stable (e.g., `latest-py3.13`)

### H2: Supported Python Versions
Short table: 3.11, 3.12, 3.13, 3.14. Note upper bound (<3.15).

### H2: Updating Images
`docker compose pull` + restart.

Removed from this page (too detailed for getting-started):
- PR preview tags and bleeding-edge main branch tags
- "Tags NOT Published" section
- "Choosing a Tag" decision matrix (production/development/pre-release)
- Separate "Check Current Version" section

If needed later, these could live in an Operating or Reference page.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `tag-pinned-compose.yml` | Keep | Primary recommendation |
| `tag-latest-compose.yml` | Keep | Development alternative |
| `docker-pull-update.sh` | Keep | Update command |
| `tag-format-versioned.txt` | Review | May fold into prose |
| Others | Drop or defer | PR/main/prerelease tags not needed here |

## Cross-Links

- **Links to:** Docker Setup, Dependencies
- **Linked from:** Docker Setup (next steps)
