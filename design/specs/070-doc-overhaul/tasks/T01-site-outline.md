---
task_id: "T01"
title: "Create docs branch, site outline, and calibration artifacts"
status: "done"
depends_on: []
implements: ["FR#5", "FR#7", "FR#8", "FR#9", "FR#10", "FR#16", "FR#18", "AC#8", "AC#10", "AC#11", "AC#13", "AC#18", "AC#20"]
---

## Summary

The foundational task. Creates the long-lived docs branch, restructures the `mkdocs.yml` nav from scratch, generates stub files for every page in the new tree, and produces all Phase 1 calibration artifacts (exemplar selections, voice audit checklist, docs-context.md). Every subsequent task depends on this one. No page content is written — only structure and tooling.

## Prompt

Work in the `design/specs/070-doc-overhaul/` feature directory on the worktree at `/home/jessica/source/hassette/.claude/worktrees/928`.

### 1. Create the docs branch

Create a new branch `docs/overhaul` from the current HEAD. All subsequent work targets this branch.

### 2. Restructure `mkdocs.yml` nav

Rewrite lines 32–126 of `mkdocs.yml` (the `nav:` section). The new nav must implement these structural changes:

- **Eliminate the "Advanced" section entirely.** Rehome its content:
  - `custom-states.md`, `state-registry.md`, `type-registry.md` → `core-concepts/states/` as depth pages
  - `log-level-tuning.md` → new "Operating Hassette" section
  - `managing-helpers.md` → `core-concepts/api/managing-helpers.md` (move the file too)
  - `advanced/index.md` → delete (content absorbed into rehomed pages)
- **Restructure Web UI** from tab-mirroring to task-oriented. Maximum 6 pages. Candidate tasks: debugging a failing handler, reading logs, managing apps (start/stop/reload/health). Consolidate the current 12 pages (6 top-level + 6 app-detail) into ≤6 task-oriented pages. Each page must represent a discrete user task — justify the page's existence.
- **Add "Operating Hassette" section** containing: Log Level Tuning (from Advanced), Upgrading Hassette (extracted from current Troubleshooting). Troubleshooting remains pure symptom-lookup.
- **Designate DI canonical home** at `core-concepts/bus/dependency-injection.md`. This is already the path — just confirm it in the nav and note that all other DI references compress to one sentence + link.
- **Structure States depth pages** under `core-concepts/states/`: overview (existing `index.md`), plus at minimum "Subscribing to State Changes" and "DomainStates Reference" as new depth pages. Custom States, State Registry, and Type Registry move here from Advanced.
- **Add evaluator page** to Getting Started (e.g., "Is Hassette Right for You?" or "Hassette vs. Alternatives").
- **Fix Managing Helpers** — move from `pages/advanced/managing-helpers.md` to `pages/core-concepts/api/managing-helpers.md` so the filesystem path matches the nav position.
- **Decide Migration page count** — review the 8 current migration pages. Keep all 8 or condense to fewer. The section stays (drop is off the table). Justify the decision.
- **Review PUBLIC_MODULES** — read `tools/gen_ref_pages.py` lines 17–46. Check if the module list is stale (modules renamed, removed, or missing). Note any changes needed but do not modify the generator.

### 3. Create stub files

For every page in the new nav tree, create a stub `.md` file containing:
```markdown
# <Page Title>

*This page is being rewritten as part of the documentation overhaul.*
```

This satisfies `mkdocs build --strict` for cross-links. Verify by running `uv run mkdocs build --strict` after creating all stubs.

### 4. Select three exemplar candidates

Choose three pages to serve as voice anchors, one for each mode:

1. **Concept exemplar** — must (a) introduce multiple related terms, (b) send readers to sibling depth pages, (c) have a clear new-reader audience. Strong candidate: Bus overview.
2. **Getting-started or recipe exemplar** — must demonstrate the prose "How It Works" pattern from voice-guide.md. Strong candidate: First Automation or Motion Lights.
3. **Reference exemplar** — must demonstrate terse/tabular voice distinct from concept pages. Strong candidate: DI annotations page or CLI command reference.

Document the selection and criteria in `design/specs/070-doc-overhaul/tasks/exemplar-selections.md`.

### 5. Create voice audit checklist

Write 5–10 concrete, binary pass/fail items drawn from the most commonly violated voice-guide.md rules. Likely items:
- No bullet lists with bolded lead-ins in "How It Works" sections
- System-as-subject in concept pages (no "you")
- No transition sentences opening paragraphs
- Verification steps in recipes name concrete commands
- Terms defined functionally on first use

Add a reference-mode addendum (3–4 items): tables before prose in reference sections, no narrative arc in annotation tables, terse functional definitions in table cells, no admonitions in reference tables.

### 6. Create docs-context.md

Write `design/specs/070-doc-overhaul/docs-context.md` — the single calibration artifact read at the start of each writing session. Contents:
- Paths to all three exemplar pages
- The full voice audit checklist inline (not referenced — copied so the executor has it without reading another file)
- The 3 most common voice violations found in the current docs (identify these by sampling 5–6 current pages)

## Focus

**Current nav structure:** `mkdocs.yml` lines 32–126. Nine major sections: Home, Getting Started (4+4 docker), Core Concepts (8 subsections), Web UI (6+6 app-detail), CLI (3), Testing (4), Recipes (6), Advanced (5), Migration (8), plus Troubleshooting and auto-generated pages.

**Web UI current state:** 12 pages totaling ~1085 lines. `app-detail/handlers.md` is the longest at 202 lines. The top-level pages (apps, handlers, logs, config, layout) mirror tab names; app-detail pages mirror sub-tabs. Task-oriented consolidation means asking "what is the user trying to DO?" not "which tab are they looking at?"

**Advanced pages to rehome:** `custom-states.md` (→ states), `state-registry.md` (→ states), `type-registry.md` (→ states), `log-level-tuning.md` (→ Operating), `managing-helpers.md` (→ api), `index.md` (→ delete).

**Snippet counts by section:** advanced: 60, core-concepts: 120, getting-started: 8, migration: 27, recipes: 8, testing: 34, web-ui: 1. The 60 advanced snippets move with their pages to states/.

**Excluded from page count:** `docs/pages/core-concepts/configuration/snippets/file_discovery.md` is a `.md` file in a snippets dir, excluded by `exclude_docs`.

**Voice-guide.md** has 22 rules (9 "We Always", 6 "We Never", 7 "When X, Do Y"). Read it fully before creating the checklist.

## Verify

- [ ] FR#5: `core-concepts/bus/dependency-injection.md` appears in the nav as the DI canonical page
- [ ] FR#7: Web UI section in `mkdocs.yml` contains ≤6 entries, each with a task-oriented title
- [ ] FR#8: No "Advanced" section exists in `mkdocs.yml` nav
- [ ] FR#9: `core-concepts/states/` nav subsection has overview + at least "Subscribing to State Changes" and "DomainStates Reference" depth pages, plus Custom States, State Registry, Type Registry
- [ ] FR#10: An "Operating Hassette" section exists in the nav with Log Level Tuning and Upgrading content
- [ ] FR#16: `managing-helpers.md` filesystem path is `pages/core-concepts/api/managing-helpers.md`
- [ ] FR#18: Getting Started section includes a dedicated evaluator page
- [ ] AC#8: `grep -c "Advanced" mkdocs.yml` returns 0 in the nav section
- [ ] AC#10: Web UI section in nav has ≤6 pages with task-oriented titles
- [ ] AC#11: States subsection in `mkdocs.yml` has overview, at least two depth pages (state change subscriptions, DomainStates reference), plus Custom States, State Registry, and Type Registry as extension pages
- [ ] AC#13: "Operating Hassette" section exists in nav
- [ ] AC#18: Managing Helpers file path matches nav position
- [ ] AC#20: Evaluator page exists in Getting Started nav
