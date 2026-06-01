# Handoff: Doc Overhaul Brief for Issue #928

**Date:** 2026-05-31
**Project:** hassette
**Directory:** /home/jessica/source/hassette/.claude/worktrees/928
**Branch:** worktree-928
**Tmux:** hassette-issue-928

## What We Were Working On

Issue #928 calls for rewriting all 76 documentation pages from scratch using an outline-first process. The existing docs grew organically and have inconsistent depth, voice, and coverage despite mature standards (voice-guide.md, doc-rules.md). This session ran the grill and challenge workflows to produce a thorough brief before any implementation begins. The brief captures all key decisions, structural prescriptions, and process safeguards needed to execute the rewrite across three sequential phases.

## Approach

1. Deep-dived issue #928 to understand scope (76 pages, 352 snippets, 10 nav sections).
2. Ran `/mine.grill` — multi-angle interrogation across product, design, engineering, scope, and adversarial lenses. Pinned down audience priority, rewrite depth, snippet strategy, delivery model, voice drift mitigation, and branch strategy through 8 interactive questions.
3. Ran `/mine.challenge` against the resulting brief. Three critics (Documentation Architect, End-User Reader, Senior Engineer) produced 12 findings. All 12 were resolved — 3 auto-applied, 9 user-directed with the recommended option chosen each time.

## Current State

### Done
- Brief written, challenged, and committed: `design/specs/070-doc-overhaul/brief.md`
- Pushed to `worktree-928` on origin
- All 12 challenge findings resolved and applied to the brief

### Not Started
- Phase 1: Site outline (page tree and nav structure)
- Phase 2: Per-page content outlines with snippet inventory
- Phase 3: Writing pages section-by-section

## Uncommitted Changes

None — all changes committed.

## Decisions Made

- **Truly blank slate** — every page starts empty, even pages already close to the voice standard. Exception carved out for troubleshooting/operational pages: mandatory pre-write knowledge inventory to preserve log signatures, timing values, and runbook commands.
- **Full structural freedom** — sections can be merged, split, renamed, or removed in Phase 1. Specific targets prescribed: delete "Advanced" section (rehome contents to core-concepts/states/ and troubleshooting), replace Web UI tab-by-tab with task-oriented structure, scope Architecture page to app-authors only (contributor content moves to internals.md).
- **Docs branch strategy** — section PRs merge to a long-lived docs branch, big bang PR to main when complete. Rebase checkpoint after each section PR to catch API drift.
- **Two exemplar pages** — one core concept, one getting-started/recipe. Selection is a Phase 1 deliverable with explicit criteria defined. Voice audit checklist (not just a subjective scan) also a Phase 1 deliverable.
- **Reader success criteria** — each section evaluated against concrete reader outcomes, not just voice consistency.
- **Snippet audit in Phase 2** — each outline declares needed examples; unclaimed snippets die. Stub-first convention during Phase 3 to keep CI green.

## Open Questions

- Which specific pages become the two exemplars (Phase 1 decides based on criteria in the brief)
- Whether to keep, condense, or drop the Migration section (8 AppDaemon pages)
- Pyright config scoping for snippet suppressions (pre-Phase 3 cleanup item)

## Key Files

- `design/specs/070-doc-overhaul/brief.md` — the challenged brief; starting point for `/mine.define`
- `.claude/rules/voice-guide.md` — 23 voice/style rules with before/after examples
- `.claude/rules/doc-rules.md` — page structure templates, snippet conventions, layering guidance
- `mkdocs.yml` — current nav structure (will change in Phase 1)

## Next Steps

1. Run `/mine.define design/specs/070-doc-overhaul` to turn the brief into a full spec with work packages
2. Execute Phase 1 (site outline) — the most consequential phase; deserves disproportionate scrutiny
3. Create the docs branch for incremental section PRs
