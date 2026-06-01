---
task_id: "T11"
title: "Write Recipes section"
status: "planned"
depends_on: ["T04"]
implements: ["FR#1", "FR#4", "AC#1", "AC#7"]
---

## Summary

Writes all 7 recipe pages from blank. Each recipe is a self-contained example: problem statement, full runnable app, "How It Works" prose walkthrough, verification step, and variations. The "Verify it's working" step (FR#4) is the key addition — every recipe must name a concrete command or UI action that produces observable output proving the automation fired.

## Prompt

Work on the `docs/overhaul` branch. Before writing, read:
- `design/specs/070-doc-overhaul/docs-context.md` (calibration artifact)
- `design/specs/070-doc-overhaul/outlines/recipes/` (Phase 2 outlines — each contains H2/H3 headings with descriptions, named snippet inventory with keep/rewrite/new status, and cross-links)
- The recipe exemplar page from T03 (voice reference for "How It Works" prose)
- `.claude/rules/voice-guide.md` and `.claude/rules/doc-rules.md`

### Pages to write (7):

- `recipes/index.md` — Recipe overview, how to use recipes, links to individual recipes
- `recipes/motion-lights.md` — Turn lights on with motion, off after delay
- `recipes/debounce-sensor-changes.md` — Wait for sensor stability before reacting
- `recipes/sensor-threshold.md` — React when a sensor crosses a threshold
- `recipes/daily-notification.md` — Send a notification at a specific time
- `recipes/service-call-reaction.md` — React to HA service calls
- `recipes/vacation-mode-toggle.md` — Toggle a set of automations with a single switch

### Recipe template (from doc-rules.md):

1. **Problem statement** — one paragraph, concrete example
2. **The Code** — full runnable app with config
3. **How it works** — prose walkthrough, one decision at a time (voice-guide rule #21). **Flowing prose paragraphs, NOT bullet lists with bolded lead-ins.** This is the most commonly violated pattern.
4. **Verify it's working** (FR#4) — a concrete command (`hassette log --app <key>`, `hassette listener --app <key>`) or web UI action (Handlers tab → check invocation count) the reader runs to confirm the automation fires. Show expected output.
5. **Variations** — alternative approaches or tweaks
6. **See also** — links to concept pages for features used, related recipes

### Voice:

Recipes use "you" in procedure sections and variations (voice-guide rule #21 exception). But "How It Works" sections use system-as-subject throughout — explain what the code does, not what "you" did. This is the subtle distinction: the reader acts in procedural steps, but the code is the subject when explaining behavior.

### "Verify it's working" (FR#4):

Every recipe MUST include this section. Examples:
- "Run `hassette log --app motion_lights --since 5m` and look for `handler fired: on_motion_change`"
- "Open the web UI Handlers tab, filter by `motion_lights`, and check that the invocation count increased"
- "Trigger the motion sensor and verify the light turns on within 2 seconds"

The verification must be something the reader can actually do, not a theoretical description.

## Focus

**Current recipes are close to the voice standard** — identified in the design doc as one of the closest sections. The risk is regression. Read current recipes before rewriting to absorb what works.

**Recipe snippets:** 8 files. Each recipe typically has one full app file. The Phase 2 outline (T04) maps these.

**"How It Works" voice trap:** The most common violation in current docs is bullet lists with bolded lead-ins in "How It Works" sections. Voice-guide.md has explicit before/after examples showing the correct pattern. Read them before writing.

**Real entity names** — use `light.kitchen`, `sensor.outdoor_temperature`, `binary_sensor.front_door` — not `entity.my_entity` or `sensor.test_sensor`.

## Verify

- [ ] FR#1: All pages pass every item on the voice audit checklist (in `docs-context.md`)
- [ ] FR#4: Every recipe includes a "Verify it's working" section with a concrete command or UI action that produces observable output
- [ ] AC#1: Voice audit checklist applied and all items pass
- [ ] AC#7: Each recipe's verification step names a specific command (`hassette log`, `hassette listener`) or UI action (Handlers tab) with expected output
