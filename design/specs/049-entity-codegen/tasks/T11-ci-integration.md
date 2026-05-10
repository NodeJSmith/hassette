---
task_id: "T11"
title: "Add CI integration, staleness warning, and docs version display"
status: "planned"
depends_on: ["T10"]
implements: ["FR#22", "FR#23", "AC#1"]
---

## Summary
Adds the GitHub Actions CI job that runs the generator in --check mode with Python 3.14, pinned HA version, and cached sparse clone. Also adds a staleness warning (non-blocking) when the pinned HA version is behind latest stable. Documents the HA version on the docs site.

## Prompt
**CI Job (`.github/workflows/lint.yml`):**

Add a new job `codegen-freshness` (separate from the existing lint/test jobs):
- runs-on: ubuntu-latest
- Install Python 3.14 via `actions/setup-python`
- Cache HA core checkout keyed by `codegen/ha-version.txt` content
- On cache miss: `git clone --depth 1 --branch $(cat codegen/ha-version.txt) https://github.com/home-assistant/core.git $HA_CACHE_PATH`
- Install codegen package: `cd codegen && uv sync`
- Run: `uv run hassette-codegen --ha-core-path $HA_CACHE_PATH --check`
- Path filter: trigger on changes to `src/hassette/models/**`, `src/hassette/const/**`, `codegen/**`, `.generated-manifest`

**Staleness warning (FR#22):**

Add a separate CI step (or lightweight script in codegen/):
- Read `codegen/ha-version.txt`
- Query GitHub releases API: `https://api.github.com/repos/home-assistant/core/releases/latest`
- Compare pinned version vs latest stable
- If behind: emit a warning annotation (`::warning::`) — non-blocking, doesn't fail the job
- If current or ahead: silent pass

**Docs version display (FR#23):**

Add the HA version to the docs site:
- In `docs/` content (likely `docs/index.md` or a compatibility page), add a note: "Hassette's entity models are generated from Home Assistant **{version}**."
- Optionally: read `codegen/ha-version.txt` at mkdocs build time via a macro/hook — or just hardcode it with a note to update alongside the version file

**pyright verification (AC#1):**

Add a CI step (can be in the same job or the existing lint job) that runs `pyright --verifytypes hassette` after the codegen check passes. This verifies generated output is type-complete.

## Focus
- The existing lint.yml runs Python 3.13 — the codegen job MUST be a separate job with Python 3.14
- GitHub Actions cache key: `ha-core-${{ hashFiles('codegen/ha-version.txt') }}` — deterministic, busts on version bump
- The sparse clone only needs `homeassistant/components/` (for extraction) — no need for `script/` since we're not importing hassfest
- `--depth 1 --branch TAG` is the fastest clone — TAG must be an exact release tag like `2026.5.1`
- The staleness check should use `gh api` or `curl` with the GitHub API — handle rate limits gracefully (just skip if API fails)
- `pyright --verifytypes` checks that the package's public API has complete type annotations — this validates generated code is properly typed

## Verify
- [ ] FR#22: CI emits a non-blocking warning when pinned HA version is behind latest stable
- [ ] FR#23: The docs site displays which HA release the typed models correspond to
- [ ] AC#1: Running pyright --verifytypes against generated output produces zero errors
