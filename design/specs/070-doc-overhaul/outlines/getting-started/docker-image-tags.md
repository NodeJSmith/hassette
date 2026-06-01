# Docker — Image Tags

**Status:** Exists (151 lines), reference-style, voice polish needed
**Voice mode:** Getting-started with reference feel — tables for scanning, "you" for recommendations

## Outline

### H2: Tag Format
#### H3: Recommended — Pin Both Version and Python
Primary recommendation with example.
#### H3: Track Latest Stable Release
When acceptable, risks.
#### H3: Testing Open Pull Requests
PR preview tags, when useful.
#### H3: Bleeding-Edge Main Branch
`main-py3.XX` tags, stability caveats.

### H2: Tags NOT Published
What doesn't exist and why (no `latest` without Python version, no alpine, no slim).

### H2: Supported Python Versions
Table of currently supported versions.

### H2: Choosing a Tag
#### H3: For Production
#### H3: For Development
#### H3: For Testing Pre-release Features

### H2: Updating Images
#### H3: Pull Latest
#### H3: Check Current Version

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `tag-format-latest.txt` | Keep | Tag examples |
| `tag-format-main.txt` | Keep | |
| `tag-format-pr.txt` | Keep | |
| `tag-format-versioned.txt` | Keep | |
| `tag-latest-compose.yml` | Keep | Compose examples |
| `tag-pinned-compose.yml` | Keep | |
| `tag-prerelease-compose.yml` | Keep | |
| `tag-prerelease-explicit.txt` | Keep | |
| `docker-pull-update.sh` | Keep | Update command |
| `docker-version-check.sh` | Keep | Version check |

## Cross-Links

- **Links to:** Docker Setup, Dependencies
- **Linked from:** Docker Setup (next steps)
