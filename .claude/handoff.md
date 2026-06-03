# Handoff: Documentation overhaul T09-T12

**Date:** 2026-06-02
**Project:** hassette
**Directory:** /home/jessica/source/hassette/.claude/worktrees/928
**Branch:** worktree-928
**Tmux:** hassette-doc-t10-t12

## What We Were Working On

Full documentation site rewrite for the Hassette project (spec `design/specs/070-doc-overhaul/`). The overhaul has 13 tasks (T01-T13). This session picked up at T09 (Web UI) and completed T09, T10 (CLI + Testing), T11 (Recipes), and T12 (Migration + Troubleshooting + Operating). A draft PR #970 was opened so readthedocs can build a preview. T13 (final sweep, snippet cleanup, merge) is the only remaining task.

## Approach

Established pipeline from earlier sessions: read per-page outlines from `design/specs/070-doc-overhaul/outlines/`, dispatch Sonnet writer subagents in parallel (one per page), then Opus reviewer subagents that verify voice rules, fix issues directly, and verify all symbol references against source code. Commit and push each section as a batch. The voice guide at `.claude/rules/voice-guide.md` and the writing prompt template at `design/specs/070-doc-overhaul/writing-prompt-template.md` drive consistency.

Key constraint: the VPS has 15GB RAM and prior sessions crashed from memory pressure when mkdocs dev server ran alongside many parallel agents. This session skipped mkdocs entirely and capped parallel agents at 6-7 Sonnet writers or 4-5 Opus reviewers at a time.

## Current State

### Done
- T01-T08: completed in prior sessions (getting-started, core-concepts, infrastructure)
- T09: Web UI (5 pages) — committed as `b1c1988e`
- T10: CLI (4 pages) + Testing (5 pages) — committed as `c638a6ad` and `6effc366`
- T11: Recipes (6 pages rewritten, motion-lights exemplar unchanged) — committed as `82038842`
- T12: Migration (8 pages including checklist) — committed as `a4363fef`
- T12: Troubleshooting (1 page) + Operating (3 pages) — committed as `dcbe19f0`
- Draft PR #970 opened for readthedocs preview

### Not Started
- T13: Final sweep, snippet cleanup, and docs branch merge

## Uncommitted Changes

None — all changes committed.

## Decisions Made

- **Checklist.md kept as voice polish, not full rewrite** — the outline explicitly said "remains as a step-by-step per-app checklist." Reviewer found and fixed a correctness bug (missing `await` on scheduler calls).
- **motion-lights.md kept as-is** — it was the exemplar page from T03, already matches the voice guide perfectly.
- **Operating snippets copied from advanced/** — log-level tuning TOML snippets were at `docs/pages/advanced/snippets/log-level-tuning/` and copied to `docs/pages/operating/snippets/`. The originals were not deleted (that's T13 cleanup work).
- **Operating reviewer created 2 new snippet files** — `ws_reconnect_events.py` and `timeout_overrides.py` were extracted from inline code blocks for Pyright checking. These are new files not in the outlines.
- **Upgrading page: genericized personal paths** — reviewer caught `/home/jessica/...` in a TOML example and changed it to `/home/youruser/...` for public docs.

## Open Questions

- `followups.md` has items for T13: screenshot inventory for web-ui pages, orphaned old pages to delete, broken cross-link decisions, CLI command verification
- The operating snippets were copied (not moved) from advanced/ — T13 should clean up the originals if they're no longer referenced
- The readthedocs build from PR #970 may surface broken links or missing images that need fixing in T13

## Key Files

- `design/specs/070-doc-overhaul/followups.md` — tracking file for T13 follow-up items
- `design/specs/070-doc-overhaul/writing-prompt-template.md` — reusable prompts for writer/reviewer subagents
- `design/specs/070-doc-overhaul/docs-context.md` — voice calibration artifact with checklist and violations
- `.claude/rules/voice-guide.md` — voice rules for all doc pages
- `.claude/rules/doc-rules.md` — page structure rules, snippet conventions, admonition policy
- `design/specs/070-doc-overhaul/outlines/` — per-page outlines used as specs for writers
- `design/specs/070-doc-overhaul/tasks/T13-final-sweep.md` — T13 task definition

## Next Steps

1. Review the readthedocs preview from PR #970 for rendering issues, broken links, missing images
2. Start T13: run the muffet link checker and snippet orphan check from T02's CI tooling
3. Delete orphaned old pages listed in `followups.md` (old tab-mirroring web-ui pages, etc.)
4. Inventory and refresh web-ui screenshots referenced by the new pages
5. Verify cross-links between sections (migration links to concept pages, recipes link to concept pages)
6. Clean up duplicated snippets (operating/snippets originals still in advanced/snippets)
7. Final voice sweep across all pages (spot-check for drift)
8. Mark T13 complete, merge the docs branch
