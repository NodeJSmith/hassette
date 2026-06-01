---
task_id: "T04"
title: "Create per-page content outlines for all pages"
status: "planned"
depends_on: ["T01", "T03"]
implements: ["FR#15", "AC#17"]
---

## Summary

Phase 2 of the rewrite. Creates detailed content outlines for every page in the new tree: section headings with 1–2 sentence descriptions, named snippet inventories, and unclaimed snippet mapping. For troubleshooting and operational pages, extracts a knowledge inventory (log signatures, timing values, runbook commands) from the current pages before they're overwritten. The outlines serve as the blueprint for Phase 3 writing tasks.

## Prompt

Work on the `docs/overhaul` branch. Read the finalized `mkdocs.yml` nav from T01 to know the full page tree.

### For each page in the tree:

Create an outline file at `design/specs/070-doc-overhaul/outlines/<section>/<page-slug>.md` containing:

1. **Section headings** — the H2/H3 structure the final page will have. Each heading gets a 1–2 sentence description of what content belongs there.
2. **Snippet inventory** — named list of code examples the page needs. Format: `snippet-name.py — what it demonstrates`. Distinguish between:
   - Existing snippets to keep (with current path)
   - Existing snippets to rewrite (with current path and what changes)
   - New snippets to create (with proposed path)
3. **Cross-links** — which other pages this page links to, and which pages link to it.

### Unclaimed snippet mapping

After outlining all pages, produce a summary at `design/specs/070-doc-overhaul/outlines/snippet-mapping.md`:

- **Claimed:** snippet files assigned to at least one page outline
- **Unclaimed:** snippet files referenced by no outline (candidates for deletion in Phase 3)
- **New:** snippet files that need to be created

Current snippet counts: advanced (60), core-concepts (120), getting-started (8), migration (27), recipes (8), testing (34), web-ui (1) = 258 total.

### Knowledge inventory for operational pages

For these pages, read the current content thoroughly and extract every piece of operational knowledge before it's overwritten:

- **`troubleshooting.md`** — log signatures, error messages, timing values, resolution steps
- **`advanced/log-level-tuning.md`** → moving to Operating Hassette
- Any upgrade/migration runbook content in the current docs

Write the inventory to `design/specs/070-doc-overhaul/outlines/knowledge-inventory.md`. Format: one entry per knowledge item with the source page and line range. This is the safety net for FR#15 — if something from the current docs doesn't appear in the inventory, it risks being lost.

## Focus

**Page count by section (from T01 nav):**
- Getting Started: 8 pages (4 main + 4 docker)
- Core Concepts: ~25 pages across 8+ subsections
- Web UI: ≤6 pages (consolidated)
- CLI: 4 pages
- Testing: 4 pages
- Recipes: 7 pages
- Migration: ≤8 pages
- Troubleshooting: 1 page
- Operating Hassette: 2–3 pages (new)
- Home: 1 page

**Knowledge loss risk:** The troubleshooting page contains log signatures, timing values (e.g., reconnection delays, timeout thresholds), and step-by-step resolution procedures that exist nowhere else in the codebase. These are the hardest items to reconstruct if lost. Extract them first.

**Snippet mapping complexity:** The 60 advanced snippets need remapping — custom-states, state-registry, and type-registry snippets move to core-concepts/states/snippets/. Log-level-tuning snippets move to the Operating Hassette section. Managing-helpers snippets move to core-concepts/api/snippets/.

**Exemplar pages (from T03)** are the voice reference. The outlines don't need to demonstrate voice — they're structural blueprints. But they should note where voice mode switches (e.g., "How It Works uses system-as-subject per voice-guide rule #21").

## Verify

- [ ] FR#15: Knowledge inventory exists at `design/specs/070-doc-overhaul/outlines/knowledge-inventory.md` and covers every named failure mode, log signature, timing value, and runbook command from the current troubleshooting and operational pages
- [ ] AC#17: Diff the knowledge inventory against the current troubleshooting page — every item in the current page has a corresponding entry in the inventory
