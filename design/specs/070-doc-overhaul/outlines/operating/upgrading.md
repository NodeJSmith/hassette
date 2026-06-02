# Operating Hassette — Upgrading

**Page type:** Operating (procedural)
**Reader's job:** Upgrade Hassette to a newer version without breaking their running automations.
**Voice mode:** Procedural — "you" allowed, step-by-step

## What was cut (and where it goes)

- Nothing cut. This is a new page assembled from KI-12 and KI-13. The outline is already action-first — the reader wants to upgrade, not read about versioning philosophy.

## Outline

### H2: Check Your Current Version
Two commands: `hassette --version` (CLI) and `uv pip show hassette` (project environment). The reader needs to know where they are before deciding whether to upgrade.

### H2: Upgrade
Split by install method:
- **pip / uv**: `uv add hassette@latest`
- **Docker**: pull the new image tag, restart the container

One-liner each. No explanation needed.

### H2: Reading the Changelog
Where to find it (`CHANGELOG.md` in the repo, GitHub Releases). How breaking changes are flagged: `BREAKING CHANGE:` footer in the changelog entry, `!` in the commit type. What to look for before upgrading.

### H2: Major Version Upgrades
**Content from KI-13.** Bare-metal installs: `data_dir` includes the major version (`~/.local/share/hassette/v0/`). A future `v1/` would start with a fresh database. Set `data_dir` / `config_dir` explicitly to preserve data across major versions. Docker is unaffected — `/data` and `/config` are version-independent mount points.

## Snippet Inventory

No code snippets. Shell commands are inline.

## Cross-Links

- **Links to:** Operating overview, Changelog, Docker/Image Tags
- **Linked from:** Operating overview
