---
task_id: "T02"
title: "Add muffet link checker and snippet orphan check to CI"
status: "done"
depends_on: ["T01"]
implements: ["FR#13", "AC#3", "AC#5"]
---

## Summary

Adds two new CI validation jobs to catch documentation defects early: a post-build HTML link checker (muffet) targeting broken anchor fragments, and a snippet orphan check that finds unreferenced `.py` files under `docs/pages/*/snippets/`. Both run on every PR to the docs branch. These tools are prerequisites for the final sweep (T13) and provide ongoing protection after the rewrite.

## Prompt

Work on the `docs/overhaul` branch in the worktree at `/home/jessica/source/hassette/.claude/worktrees/928`.

### 1. Muffet link checker

Add a CI job that:
1. Runs `uv run mkdocs build --strict` to produce the `site/` directory
2. Starts a local HTTP server serving `site/`
3. Runs [muffet](https://github.com/raviqqe/muffet) against `http://localhost:<port>` to check all internal links including anchor fragments
4. Fails the job if any broken links are found

Place this in `.github/workflows/docs.yml` as a new job (or extend the existing build job). The existing lychee check in `lint.yml` checks markdown source files — muffet checks the built HTML and catches broken anchor fragments that lychee and `--strict` miss.

Configuration notes:
- Exclude external URLs (muffet should only check internal links)
- Set a reasonable timeout and concurrency
- The existing lychee config (`lychee.toml`) excludes badges, star-history, localhost — muffet doesn't need these since it only checks the local build

### 2. Snippet orphan check

Write a script `tools/check_snippet_orphans.py` that:
1. Finds all `.py` files under `docs/pages/*/snippets/`
2. Finds all `--8<--` include references in `.md` files under `docs/pages/`
3. Reports any `.py` file not referenced by at least one include
4. Exits with code 1 if orphans are found, 0 otherwise

Add this as a CI step in `.github/workflows/docs.yml` (alongside or after the build job). It should run on every PR that touches `docs/`.

### 3. Verify both tools locally

Run both tools against the current docs to establish a baseline:
- Muffet: build the site, serve it, run muffet. Note any existing broken links.
- Orphan check: run the script. The current 258 snippets may have orphans — note them but don't fix them (that's Phase 2/T04 work).

## Focus

**Existing CI structure:** `.github/workflows/docs.yml` has two jobs — `build` (mkdocs build --strict) and `docs-check` (API reference drift + Pyright on snippets). The link checker job needs the built `site/` directory, so it must run after the build step.

**Existing link checking:** `lint.yml` runs lychee on markdown source files (README, CONTRIBUTING, docs/**/*.md) with config in `lychee.toml`. Lychee excludes badges, shields.io, localhost, star-history, docs/reference/ (auto-generated), and compare URLs. Muffet is complementary — it checks built HTML, not markdown source.

**Snippet structure:** 258 `.py` files across 6 section directories: advanced (60), core-concepts (120), getting-started (8), migration (27), recipes (8), testing (34), web-ui (1). The orphan check should handle both full-file includes and fragment includes (section markers).

**Include syntax:** Full file: `--8<-- "pages/core-concepts/bus/snippets/file.py"`. Fragment: `--8<-- "pages/core-concepts/bus/snippets/file.py:marker"`. The orphan check must match the file path portion regardless of fragment suffix.

## Verify

- [ ] FR#13: The snippet orphan check script exists at `tools/check_snippet_orphans.py` and correctly identifies unreferenced snippet files
- [ ] AC#3: A muffet-based link checker CI job exists in `.github/workflows/docs.yml` that runs against the built `site/` directory and checks anchor fragments
- [ ] AC#5: The snippet orphan check runs in CI on docs PRs and fails if any orphan `.py` files exist under `docs/pages/*/snippets/`
