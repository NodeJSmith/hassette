# Brief: Documentation Overhaul

**Date:** 2026-05-31
**Status:** explored
**Issue:** #928

## Idea

Rewrite all 76 documentation pages from scratch using an outline-first process. The current docs grew organically and have inconsistent depth, voice, and coverage despite well-defined standards (voice-guide.md, doc-rules.md). Rather than patching individual pages, this tears everything down and rebuilds with a planned structure — every page starts empty, even pages that were already close to the standard.

## Key Decisions Made

- **Audience priority:** All three personas (evaluators, new users, active developers) are equally important. No section gets deprioritized.
- **Truly blank slate:** Every page starts from an empty file. Existing pages are reference material, not starting points. No copy-paste-and-edit. **Exception:** Troubleshooting and operational runbook pages get a mandatory pre-write knowledge inventory pass — the author reads the existing page, extracts every named failure mode, log signature, timing value, and runbook command into a working note, then starts the blank page. Blank-slate applies to structure and prose; operational knowledge must be carried forward.
- **Full structural freedom in Phase 1:** Sections can be merged, split, renamed, or removed. The current 10-section nav is not sacred — Phase 1 should question everything.
- **Snippet audit happens in Phase 2:** Each page outline declares what code examples it needs. Snippets not claimed by any outline get dropped. No carrying forward 352 files by default.
- **Two exemplar pages before bulk writing:** One core concept page (hardest voice — system-as-subject, no "you") and one getting-started or recipe page (friendlier register). These anchor voice for everything that follows. **Exemplar selection is a Phase 1 deliverable** — criteria: the concept exemplar must (a) introduce multiple related terms, (b) send readers to sibling depth pages, and (c) have a clear new-reader audience. The recipe/getting-started exemplar must demonstrate the prose "How It Works" pattern from voice-guide.md (no bullet-with-bolded-lead-in). Any candidate that violates voice-guide.md requires remediation before use as exemplar.
- **Voice audit after each section PR:** Catch drift before it compounds across sections. **Operationalization:** Create a `docs-context.md` in the spec directory listing exemplar page paths — each writing session reads this at startup to calibrate. Produce a concrete voice audit checklist (5–10 items drawn from the most commonly violated voice-guide rules — e.g., no bullet lists in "How It Works," system-as-subject in concept pages, no bolded lead-ins, verification steps in recipes) as a Phase 1 deliverable. The checklist is the pass/fail gate, not a subjective scan.
- **Docs branch strategy:** Section PRs merge to a long-lived `docs` branch. One big PR from `docs` to `main` when everything is complete. Users see an atomic swap, but review happens incrementally. **Rebase checkpoint:** After each section PR merges to `docs`, rebase `docs` onto current `main` and run CI. Eight section PRs = eight opportunities to catch API drift before the final merge.
- **Delivery:** ~8 PRs to the docs branch (one per section), plus the planning phases as non-PR artifacts.

## Reader Outcomes Per Section

Each section PR is evaluated against these reader outcomes, not just voice consistency:

- **Getting Started:** A new user can install Hassette, connect to Home Assistant, deploy a working app, and verify it connected — all without external help.
- **Core Concepts:** A reader can explain what Bus, Scheduler, Api, and StateManager do and when to use each, without looking it up.
- **Recipes:** A reader can adapt the example code to their own entities and verify the automation fired (every recipe includes a "Verify it's working" step pointing to `hassette log --app <key>` or the web UI Handlers tab).
- **CLI:** A reader can find and run any CLI command for their task.
- **Testing:** A reader can write and run a test for their app using the harness.
- **Web UI:** A reader can use the web UI to debug a failing handler or check app status.
- **Migration:** An AppDaemon user can map their existing automation to the Hassette equivalent.

## Open Questions

- **Which specific pages for the exemplars?** Bus overview is a strong candidate for the concept exemplar. First Automation or a recipe like Motion Lights for the second. Needs a decision before Phase 3 starts.
- **What happens to the Migration section?** AppDaemon migration docs (8 pages) may be declining in relevance. Phase 1 should decide whether to keep, condense, or drop.
- **Web UI section structure:** Currently mirrors the UI tab-by-tab (6 pages for app-detail alone), which is fragile — every UI change forces a doc change. **Target:** Task-oriented structure organized by what users are trying to do ("debug a failing handler," "check app status," "read logs"), not by UI elements. A single "Monitoring and Debugging with the Web UI" page could replace the six app-detail pages. Phase 1 should confirm or refine this direction.
- **The "Advanced" grab-bag:** **Target:** Delete "Advanced" as a section. Move Custom States, State Registry, and Type Registry into `core-concepts/states/` as depth pages (matching the pattern of bus sibling pages for handlers, filtering, DI). Move Log Level Tuning into Troubleshooting or a new "Operating Hassette" section. Fix the Managing Helpers nav/filesystem mismatch (currently in `pages/advanced/` but rendered under Core Concepts > API). Phase 1 confirms or refines these destinations.
- **Architecture / Internals split:** **Target:** Architecture page scopes to the app-author audience only — the "four handles" model (Bus, Scheduler, Api, StateManager). Dependency graphs, wave ordering, cycle detection, and the 14 internal service names move to `internals.md`. Keep `internals.md` whole as the contributor/maintainer reference, cross-linked from concept pages. Phase 1 confirms.
- **API reference (auto-generated):** The hand-written pages are the focus, but should Phase 1 also review which modules are in `PUBLIC_MODULES` in `gen_ref_pages.py`?
- **Issue #540 (final docs sweep):** Superseded by this issue per the issue body. Should be closed when this work begins.
- **DI canonical home:** Dependency injection is currently explained in three places at contradictory depth (getting-started, apps overview callout, bus/dependency-injection.md) and the Core Concepts index labels it "Advanced" while getting-started treats it as foundational. Phase 1 should designate `core-concepts/bus/dependency-injection.md` as the single canonical page; all other locations compress to one sentence with a link. When any page uses `D.*`, `states.*`, `C.*`, `P.*`, or `A.*` for the first time, it links to the canonical page.

## Scope Boundaries

**In scope:**
- All hand-written pages in `docs/pages/` (76 pages)
- All snippet files in `docs/pages/*/snippets/` (352 files — audit and replace)
- `mkdocs.yml` nav structure
- New snippet files as needed
- Two exemplar pages before bulk writing

**Explicitly out:**
- API reference auto-generation (`tools/docs/gen_ref_pages.py`) — review in Phase 1 but don't rewrite the generator
- Docstrings in source code — those are a separate concern from the docs site
- Design documents in `design/` — not part of the docs site
- `tokens.css`, design system, or frontend changes — docs content only

**Pre-Phase 3 cleanup:**
- Scope Pyright suppressions in `docs/pyrightconfig.json` — audit whether `reportOperatorIssue` and `reportAssignmentType` can move from global suppressions to per-file exclusions (the pattern already exists in the config). New snippet files should not inherit broad suppressions by default.

**Deferred:**
- Any new documentation pages for features that don't exist yet
- Docs CI improvements beyond what's needed to validate the rewrite

## Risks and Concerns

- **Scale:** 76 blank-slate pages is a month-plus effort. Fatigue and voice drift are real risks, especially across multiple Claude sessions. The two-exemplar + voice-audit-per-section strategy mitigates but doesn't eliminate this.
- **Snippet maintenance burden:** Even with the Phase 2 audit, the rewrite will likely produce a similar number of snippet files. The testing convention (Pyright CI) keeps them honest, but each snippet is a maintenance surface.
- **Cross-link breakage during writing:** Pages reference each other heavily. Writing section-by-section means early sections will have broken links to unwritten pages. The docs branch absorbs this — links only need to work when the big PR merges to main. **Mitigation:** Add a post-build HTML link checker (e.g., `muffet` or `htmltest` targeting the built `site/` directory) as a docs CI job to catch broken anchor fragments (`#section-name`) that `mkdocs build --strict` and lychee both miss. Run on every section PR.
- **Snippet sequencing:** `pymdownx.snippets` has `check_paths: true` — any `--8<--` reference to a non-existent file fails the build. Pages and snippets must be created together. **Mitigation:** For each page, create snippet files as minimal stubs before adding `--8<--` references in the markdown. Stubs satisfy `check_paths` and Pyright; content fills in as the page matures.
- **Regression risk:** Some current pages are genuinely good. Starting from blank means the rewrite could produce pages that are worse in spots, especially for sections like recipes that were already close. The exemplar + voice audit process is the guard against this, but it requires discipline.
- **Phase 1 is load-bearing:** If the site outline is wrong, every subsequent phase builds on a bad foundation. Phase 1 deserves disproportionate time and scrutiny.

## Codebase Context

- **Voice standards:** `voice-guide.md` (23 style rules with before/after examples) and `doc-rules.md` (page structure templates, example conventions, snippet rules, layering guidance) are mature and detailed. The standards are not the problem — adherence is.
- **Snippet convention:** External `.py` files with `--8<--` includes, CI type-checked via Pyright. This convention should carry forward unchanged.
- **Prior audit (#911):** Completed and closed. Found that recipes and getting-started were closest to the voice standard; core-concepts and advanced were the furthest. This informs priority but doesn't constrain the rewrite.
- **Superseded issue (#540):** A lighter-weight "final docs sweep before v1.0.0" that this issue replaces with a more thorough approach.
- **mkdocs plugins:** search, glightbox, panzoom, gen-files, literate-nav, autorefs, mkdocstrings. These stay — the rewrite is content, not tooling.
- **CSS checker scripts** in `tools/` enforce style hygiene but don't touch docs. No interaction.
