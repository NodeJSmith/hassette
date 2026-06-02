---
task_id: "T12"
title: "Write Migration, Troubleshooting, and Operating Hassette"
status: "planned"
depends_on: ["T04"]
implements: ["FR#1", "FR#10", "FR#15", "AC#1", "AC#13", "AC#17"]
---

## Summary

Writes three sections from blank: Migration (7 pages for AppDaemon users — checklist removed), Troubleshooting (1 page, pure symptom-lookup), and the new Operating Hassette section (3 pages — overview now includes WebSocket/timeout tuning content absorbed from Configuration). Troubleshooting and Operating are the highest-risk pages for knowledge loss — they contain log signatures, timing values, and runbook commands that exist nowhere else. The knowledge inventory from T04 is the safety net.

## Prompt

Work on the `docs/overhaul` branch. Before writing, read:
- `design/specs/070-doc-overhaul/docs-context.md` (calibration artifact)
- `design/specs/070-doc-overhaul/outlines/migration/`, `outlines/troubleshooting/`, `outlines/operating/` (Phase 2 outlines — each contains H2/H3 headings with descriptions, named snippet inventory with keep/rewrite/new status, and cross-links)
- `design/specs/070-doc-overhaul/outlines/knowledge-inventory.md` (CRITICAL — extracted operational knowledge from T04)
- `.claude/rules/voice-guide.md` and `.claude/rules/doc-rules.md`

### Migration pages (7):

- `migration/index.md` — Migration overview (absorbs Common Pitfalls from removed checklist)
- `migration/concepts.md` — AppDaemon vs Hassette concepts
- `migration/bus.md` — Event handling migration
- `migration/scheduler.md` — Scheduling migration
- `migration/api.md` — API migration
- `migration/configuration.md` — Config migration
- `migration/testing.md` — Testing migration
- ~~`migration/checklist.md`~~ — **Removed.** Thin summary of sub-pages with no unique content. Common Pitfalls section moved to overview.

Migration pages follow a comparison-driven structure: old way (AppDaemon) vs new way (Hassette). Use tabs for side-by-side comparison where it helps. Voice: direct "you" is acceptable since readers are performing migration steps.

### Troubleshooting (1 page):

- `troubleshooting.md` — Pure symptom-lookup. Problem/solution format: symptom, cause, fix. No how-to content (that goes in Operating Hassette).

**CRITICAL: Use the knowledge inventory from T04.** Every named failure mode, log signature, timing value, and resolution step from the current troubleshooting page must appear in the rewritten version. The knowledge inventory is the checklist — diff the final page against it to verify nothing was lost.

### Operating Hassette (3 pages, new section):

- `operating/index.md` — Operational overview. Contains runtime behavior (WebSocket reconnection from KI-01, handler exceptions from KI-02, DB degraded mode) AND tuning guidance for WebSocket resilience and timeout behavior (absorbed from Configuration — these topics belong with the behavior they tune, not in a separate config page).
- `operating/log-levels.md` — Log level tuning (from advanced/log-level-tuning.md)
- `operating/upgrading.md` — Upgrading Hassette (extracted from current troubleshooting)

Operating pages are how-to content for running Hassette in production. Distinct from Troubleshooting (which is reactive symptom-lookup). Voice: procedural "you" is acceptable for step-by-step instructions. Troubleshooting keeps only symptom → fix entries (can't connect, apps not loading, handler never runs, scheduler not firing, cache not persisting, custom state not registering, web UI not accessible).

### Snippet handling:

Migration has 27 snippets showing AppDaemon code alongside Hassette equivalents. These are valuable for side-by-side comparison — keep and update. Troubleshooting and Operating may need new snippets for configuration examples and CLI commands.

## Focus

**Knowledge loss risk is lower than originally estimated.** The troubleshooting page was written by automated doc rewrites, not from production debugging discoveries. The specific values (retry counts, backoff timings) come from RestartSpec implementation code and are reconstructible. Still extract them in the T04 knowledge inventory, but the risk is misplacement (putting operational content in troubleshooting), not loss.

**Migration snippets** import `appdaemon` which isn't installed in the project — the Pyright config excludes `pages/migration/snippets` for this reason. This exclusion must remain.

**Log-level-tuning** moves from Advanced to Operating Hassette. Its snippets (from the 60 advanced snippets) move too. The Phase 2 outline has the specific files.

**Upgrading content** is being extracted from troubleshooting into its own page. This is a structural split — the content exists today but is mixed in with symptom-lookup entries.

## Verify

- [ ] FR#1: All pages pass every item on the voice audit checklist (in `docs-context.md`)
- [ ] FR#10: "Operating Hassette" section exists with Log Level Tuning and Upgrading content; Troubleshooting contains only symptom-lookup entries
- [ ] FR#15: Every named failure mode, log signature, timing value, and runbook command from the knowledge inventory appears in the rewritten troubleshooting and operational pages
- [ ] AC#1: Voice audit checklist applied and all items pass
- [ ] AC#13: "Operating Hassette" section exists in `mkdocs.yml` with the required content
- [ ] AC#17: Diff the knowledge inventory against the final troubleshooting page — every item is preserved
