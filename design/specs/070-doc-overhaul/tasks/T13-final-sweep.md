---
task_id: "T13"
title: "Final sweep, snippet cleanup, and docs branch merge"
status: "planned"
depends_on: ["T02", "T05", "T06", "T07", "T08", "T09", "T10", "T11", "T12"]
implements: ["FR#6", "FR#13", "FR#17", "AC#2", "AC#3", "AC#4", "AC#5", "AC#9", "AC#12", "AC#19"]
---

## Summary

The final quality gate before merging the docs branch to main. Runs all CI validation (mkdocs build, Pyright, muffet link checker, snippet orphan check), performs a cross-cutting voice spot-check, verifies DI canonicalization, confirms module cross-links and term definitions across all pages, cleans up orphan snippets, and creates the merge PR from docs branch to main.

## Prompt

Work on the `docs/overhaul` branch.

### 1. Full CI validation

Run all checks and fix any failures:

```bash
uv run mkdocs build --strict                    # AC#2
uv run pyright --project docs                   # AC#4
# Muffet link checker (from T02 CI job)         # AC#3
uv run python tools/check_snippet_orphans.py    # AC#5
```

### 2. Snippet orphan cleanup

Run the snippet orphan check from T02. For each orphan `.py` file:
- Confirm it's genuinely unreferenced (not a false positive from fragment includes)
- Delete it
- Verify `uv run pyright --project docs` still passes after deletion

### 3. DI canonicalization check (AC#9)

Grep all pages for dependency injection references:
```bash
grep -rn "dependency injection\|DI\|D\.\|dependencies\." docs/pages/ --include='*.md'
```

Verify that `core-concepts/bus/dependency-injection.md` is the only page with a full explanation. All other references should be one sentence + link. Fix any violations.

### 4. Module cross-link check (AC#12)

For each page, verify that the first use of `D.*`, `states.*`, `C.*`, `P.*`, or `A.*` links to the canonical page for that module. Grep for these patterns and spot-check.

### 5. Term definition check (AC#19)

Spot-check 5–6 pages across different sections. Verify that the first use of Bus, Scheduler, Api, Cache, App, StateManager, or Resource includes a functional definition.

### 6. Voice spot-check

Pick one page from each section (8 pages total). Run the voice audit checklist on each. Fix any failures. This catches voice drift across sessions.

### 7. Rebase and merge

Rebase `docs/overhaul` onto current `main`. Run CI one final time. Create the merge PR from `docs/overhaul` to `main`.

The PR description should:
- Summarize the rewrite scope (76 pages, blank-slate)
- List the structural changes (Advanced eliminated, Web UI consolidated, Operating section added, States expanded)
- Note the new CI jobs (muffet link checker, snippet orphan check)
- Reference issue #928

## Focus

**This task touches every page** indirectly (validation runs across all pages). Budget time for fixing issues that surface — link checker and snippet orphan check may find problems not caught during section-by-section writing.

**DI canonicalization** is the most likely cross-cutting violation. Writers for T06–T12 may have included DI explanations beyond one sentence + link. Grep is the reliable check.

**Muffet may find broken anchor fragments** that `--strict` missed. These are typically `#section-heading` references where the heading text changed during rewriting. Fix by updating the link or the heading.

**Snippet orphans** are expected — Phase 2 identified unclaimed snippets, but some may have been missed during writing. The orphan check script (T02) is the definitive tool.

**README.md** — check if the docs site URL or getting-started link changed. Update if needed (design doc Blast Radius section flagged this).

**Issue #540** — "final docs sweep before v1.0.0" is superseded by this issue. Close it in the PR description or separately.

## Verify

- [ ] FR#6: Spot-check of 5+ pages confirms first use of `D.*`, `states.*`, `C.*`, `P.*`, `A.*` links to canonical module page
- [ ] FR#13: Snippet orphan check returns 0 orphans after cleanup
- [ ] FR#17: Spot-check of 5+ pages confirms first use of Bus, Scheduler, Api, Cache, App, StateManager, or Resource includes functional definition
- [ ] AC#2: `uv run mkdocs build --strict` succeeds with zero warnings
- [ ] AC#3: Muffet link checker finds zero broken links including anchor fragments
- [ ] AC#4: `uv run pyright --project docs` passes with zero errors
- [ ] AC#5: `uv run python tools/check_snippet_orphans.py` exits 0
- [ ] AC#9: `core-concepts/bus/dependency-injection.md` is the only page with full DI explanation; all others are one sentence + link
- [ ] AC#12: Module cross-links verified on first use across spot-checked pages
- [ ] AC#19: Term definitions verified on first use across spot-checked pages
