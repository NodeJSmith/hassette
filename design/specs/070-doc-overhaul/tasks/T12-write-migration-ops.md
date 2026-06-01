---
task_id: "T12"
title: "Write Migration, Troubleshooting, and Operating Hassette"
status: "planned"
depends_on: ["T04"]
implements: ["FR#10", "FR#15", "AC#13", "AC#17"]
---

## Summary

Writes three sections from blank: Migration (≤8 pages for AppDaemon users), Troubleshooting (1 page, pure symptom-lookup), and the new Operating Hassette section (2–3 pages for log tuning and upgrading). Troubleshooting and Operating are the highest-risk pages for knowledge loss — they contain log signatures, timing values, and runbook commands that exist nowhere else. The knowledge inventory from T04 is the safety net.

## Prompt

Work on the `docs/overhaul` branch. Before writing, read:
- `design/specs/070-doc-overhaul/docs-context.md` (calibration artifact)
- `design/specs/070-doc-overhaul/outlines/migration/`, `outlines/troubleshooting/`, `outlines/operating/` (Phase 2 outlines — each contains H2/H3 headings with descriptions, named snippet inventory with keep/rewrite/new status, and cross-links)
- `design/specs/070-doc-overhaul/outlines/knowledge-inventory.md` (CRITICAL — extracted operational knowledge from T04)
- `.claude/rules/voice-guide.md` and `.claude/rules/doc-rules.md`

### Migration pages (≤8):

The page count was decided in T01. Current pages:
- `migration/index.md` — Migration overview
- `migration/concepts.md` — AppDaemon vs Hassette concepts
- `migration/bus.md` — Event handling migration
- `migration/scheduler.md` — Scheduling migration
- `migration/api.md` — API migration
- `migration/configuration.md` — Config migration
- `migration/testing.md` — Testing migration
- `migration/checklist.md` — Migration checklist

If T01 condensed to fewer pages, follow that decision. The section stays — Hassette has no existing users who've completed the migration, so this content is still a primary inflow path.

Migration pages follow a comparison-driven structure: old way (AppDaemon) vs new way (Hassette). Use tabs for side-by-side comparison where it helps. Voice: direct "you" is acceptable since readers are performing migration steps.

### Troubleshooting (1 page):

- `troubleshooting.md` — Pure symptom-lookup. Problem/solution format: symptom, cause, fix. No how-to content (that goes in Operating Hassette).

**CRITICAL: Use the knowledge inventory from T04.** Every named failure mode, log signature, timing value, and resolution step from the current troubleshooting page must appear in the rewritten version. The knowledge inventory is the checklist — diff the final page against it to verify nothing was lost.

### Operating Hassette (2–3 pages, new section):

- `operating/index.md` — Operational overview
- `operating/log-levels.md` — Log level tuning (from advanced/log-level-tuning.md)
- `operating/upgrading.md` — Upgrading Hassette (extracted from current troubleshooting)

Operating pages are how-to content for running Hassette in production. Distinct from Troubleshooting (which is reactive symptom-lookup). Voice: procedural "you" is acceptable for step-by-step instructions.

### Snippet handling:

Migration has 27 snippets showing AppDaemon code alongside Hassette equivalents. These are valuable for side-by-side comparison — keep and update. Troubleshooting and Operating may need new snippets for configuration examples and CLI commands.

## Focus

**Knowledge loss is the primary risk.** The current troubleshooting page contains:
- Specific log signatures (e.g., exact error messages for WebSocket disconnection)
- Timing values (e.g., reconnection delay thresholds, timeout periods)
- Step-by-step runbook commands (e.g., checking service status, clearing state)

None of these exist anywhere else in the codebase. The knowledge inventory from T04 is the authoritative list. Verify every item is preserved.

**Migration snippets** import `appdaemon` which isn't installed in the project — the Pyright config excludes `pages/migration/snippets` for this reason. This exclusion must remain.

**Log-level-tuning** moves from Advanced to Operating Hassette. Its snippets (from the 60 advanced snippets) move too. The Phase 2 outline has the specific files.

**Upgrading content** is being extracted from troubleshooting into its own page. This is a structural split — the content exists today but is mixed in with symptom-lookup entries.

## Verify

- [ ] FR#10: "Operating Hassette" section exists with Log Level Tuning and Upgrading content; Troubleshooting contains only symptom-lookup entries
- [ ] FR#15: Every named failure mode, log signature, timing value, and runbook command from the knowledge inventory appears in the rewritten troubleshooting and operational pages
- [ ] AC#13: "Operating Hassette" section exists in `mkdocs.yml` with the required content
- [ ] AC#17: Diff the knowledge inventory against the final troubleshooting page — every item is preserved
