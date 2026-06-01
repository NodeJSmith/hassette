---
task_id: "T09"
title: "Write Web UI section"
status: "planned"
depends_on: ["T04"]
implements: ["FR#1", "FR#7", "AC#1", "AC#10"]
---

## Summary

Writes the Web UI section from blank, consolidating the current 12 tab-mirroring pages into ≤6 task-oriented pages. The restructuring is the key change: instead of "Apps page," "Handlers page," "Logs page" (which describe UI elements), pages are organized by what the user is trying to do: "Debug a failing handler," "Read and filter logs," "Manage apps." Each page must justify its existence as a discrete user task.

## Prompt

Work on the `docs/overhaul` branch. Before writing, read:
- `design/specs/070-doc-overhaul/docs-context.md` (calibration artifact)
- `design/specs/070-doc-overhaul/outlines/web-ui/` (Phase 2 outlines — each contains H2/H3 headings with descriptions, named snippet inventory with keep/rewrite/new status, and cross-links)
- `.claude/rules/voice-guide.md` and `.claude/rules/doc-rules.md`

### Pages to write (≤6):

The exact page list was finalized in T01. Candidate task pages from the design doc:
- **Debugging a failing handler** — using the handlers view, invocation history, and logs to identify why a handler isn't working
- **Reading logs** — log filtering, log levels, finding specific events
- **Managing apps** — start, stop, reload, health checks via the web UI

The T01 nav may have refined this list. Follow the T01 decisions.

### Voice:

Web UI docs bridge concept and tutorial modes. The reader has a working Hassette instance and needs to accomplish a specific task. Use system-as-subject for explaining what the UI shows, but "you" is acceptable in procedural steps ("click the Handlers tab," "filter by app key").

### Consolidation approach:

The current 12 pages are:
- Top-level: index, apps, handlers, logs, config, layout (6 pages, ~503 lines)
- App detail: index, overview, handlers, code, config, logs (6 pages, ~583 lines)

Consolidation means merging related content by user task. The "handlers" content from both top-level and app-detail may merge into one "Debug a failing handler" page. The "logs" content from both levels may merge into one "Read and filter logs" page.

Delete the old page files after writing the new ones. The stubs from T01 already exist at the new paths.

### Screenshots and UI references:

The current web-ui pages reference specific UI elements. When rewriting, describe the UI elements the reader will interact with but don't assume a specific layout version. Focus on what the reader sees and does, not pixel-level descriptions.

## Focus

**Current Web UI has only 1 snippet** (`web-ui/snippets/`). The section is mostly prose and screenshots. New pages may need snippets for CLI commands used alongside the UI (e.g., `hassette log --app <key>`).

**App-detail pages have the most content** (583 lines total, handlers alone is 202 lines). The consolidation must preserve the useful operational knowledge while reorganizing by task.

**The "layout" page** (`web-ui/layout.md`, 99 lines) describes sidebar navigation and responsive behavior. This content may fold into the overview page or be dropped if it doesn't serve a user task.

## Verify

- [ ] FR#1: All pages pass every item on the voice audit checklist (in `docs-context.md`)
- [ ] FR#7: Web UI section contains ≤6 pages, each organized by user task (not UI element). Each page is justified as a discrete user task.
- [ ] AC#1: Voice audit checklist applied and all items pass
- [ ] AC#10: Web UI section in `mkdocs.yml` has ≤6 entries with task-oriented titles (not tab names like "Apps," "Handlers," "Logs")
