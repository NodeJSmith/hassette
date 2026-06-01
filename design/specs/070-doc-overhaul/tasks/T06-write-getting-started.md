---
task_id: "T06"
title: "Write Getting Started section"
status: "planned"
depends_on: ["T04"]
implements: ["FR#3", "FR#18", "AC#6", "AC#20"]
---

## Summary

Writes all Getting Started pages from blank: the evaluator-facing page, quickstart/installation, first automation, HA token guide, hassette-vs-ha-yaml comparison, and the 4 Docker pages. This is the user's first contact with Hassette docs — it must be approachable, concrete, and lead to a working setup. Uses "you" address and code-first ordering per the getting-started template.

## Prompt

Work on the `docs/overhaul` branch. Before writing, read:
- `design/specs/070-doc-overhaul/docs-context.md` (calibration artifact — exemplar paths, voice checklist)
- `design/specs/070-doc-overhaul/outlines/getting-started/` (Phase 2 outlines for each page)
- The getting-started exemplar page from T03 (voice reference)
- `.claude/rules/voice-guide.md` and `.claude/rules/doc-rules.md`

### Pages to write (9 total):

1. **Evaluator page** (new) — "Is Hassette Right for You?" or similar. What Hassette is, who it's for, how it compares to AppDaemon, HA YAML automations, and pyscript. Honest about tradeoffs. This is FR#18.
2. **index.md** — Quickstart overview. What you'll build, prerequisites, link to first automation.
3. **first-automation.md** — Complete walkthrough from empty file to working app. Code-first: show the code, then explain each part.
4. **ha_token.md** — How to get a long-lived access token from Home Assistant.
5. **hassette-vs-ha-yaml.md** — Side-by-side comparison for users coming from HA YAML automations.
6. **docker/index.md** — Docker deployment overview.
7. **docker/dependencies.md** — Managing Python dependencies in Docker.
8. **docker/image-tags.md** — Available image tags and which to use.
9. **docker/troubleshooting.md** — Docker-specific issues and fixes.

### Voice for this section:

- **Use "you" and "your"** — this is getting-started content (voice-guide rule #17)
- **Code first, then explain** — show the snippet, then walk through it
- **Short steps** — maximum 4–5 major steps per page, sub-steps are fine
- **Concrete verification** — each major step should produce visible progress. The first automation MUST include running `hassette status` and seeing `websocket_connected: True`, and running `hassette app` and seeing the app listed (AC#6).

### For each page:

1. Read the Phase 2 outline for section headings and snippet inventory
2. Read the current page content for technical facts to preserve (do not copy prose)
3. Write from blank following the getting-started template (what you'll build → prerequisites → steps → next steps)
4. Create snippet files (stubs first, then fill) — all code examples from snippets
5. Run voice audit checklist
6. Run `uv run mkdocs build --strict` and `uv run pyright --project docs`

## Focus

**Current getting-started pages** are already close to the voice standard (identified in the design doc as closest to target voice). The risk is regression — writing worse prose than what exists. Read the current pages for quality reference but don't copy.

**Evaluator page is new** — no existing content. Reference the design doc User Scenarios section for the Evaluator actor's task flow: lands on home page or getting started → decides whether to invest time → follows quickstart or leaves.

**AC#6 is specific:** the reader must run `hassette status` and see `websocket_connected: True`, and run `hassette app` and see their app listed as running. Build these verification steps into the first-automation page.

**Docker pages** are a sub-section with their own flow. Users following the Docker path may skip the non-Docker quickstart. Ensure the Docker index provides a complete path.

## Verify

- [ ] FR#3: All getting-started pages use direct "you" address with code-first ordering
- [ ] FR#18: A dedicated evaluator page exists covering what Hassette is, who it's for, and how it compares to alternatives
- [ ] AC#6: First automation page includes `hassette status` showing `websocket_connected: True` and `hassette app` showing the app listed
- [ ] AC#20: Evaluator page exists in Getting Started nav
