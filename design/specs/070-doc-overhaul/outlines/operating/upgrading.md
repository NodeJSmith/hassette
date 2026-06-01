# Operating Hassette — Upgrading

**Status:** Stub (3 lines), content extracting from troubleshooting.md
**Voice mode:** Procedural — "you" allowed, step-by-step
**Content source:** troubleshooting.md lines 111-128 + KI-12, KI-13

## Outline

### H2: Check Your Current Version
`hassette --version`, `uv pip show hassette` commands.

### H2: Upgrade to Latest
`uv add hassette@latest`. Docker: pull new image tag.

### H2: Reading the Changelog
Where to find it, how breaking changes are flagged.

### H2: Major Version Upgrades
Data directory path includes major version (`~/.local/share/hassette/v0/`). Future `v1/` starts fresh unless `data_dir`/`config_dir` set explicitly. Docker unaffected.

## Snippet Inventory

No code snippets — shell commands are inline.

## Cross-Links

- **Links to:** Operating overview, Changelog, Docker/Image Tags
- **Linked from:** Operating overview
