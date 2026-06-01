---
task_id: "T03"
title: "Write and review three exemplar pages"
status: "planned"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#3", "FR#6", "FR#14", "FR#17", "AC#1", "AC#12", "AC#16", "AC#19"]
---

## Summary

Writes the three exemplar pages from scratch — concept, getting-started/recipe, and reference. These pages anchor voice and quality for the entire rewrite. Each exemplar is written, voice-audited against the checklist from T01, and polished until it passes. No bulk writing begins until all three exemplars are approved. This task establishes the patterns that every subsequent writing task follows.

## Prompt

Work on the `docs/overhaul` branch. Read `design/specs/070-doc-overhaul/docs-context.md` (the calibration artifact from T01) before starting. It contains the exemplar selections, voice audit checklist, and common violation patterns.

### For each exemplar page:

1. **Read the current page content** for reference — extract any technical facts, code patterns, or entity names worth preserving. Do not copy prose.
2. **Read the relevant doc-rules.md template** for the page type (concept, recipe, getting-started, or API reference).
3. **Write the page from blank** following the template structure and voice-guide.md rules.
4. **Create all snippet files** needed by the page. Create stubs first (to satisfy `check_paths`), then fill with real code. Every code example must come from a snippet file via `--8<--` include.
5. **Run the voice audit checklist** item by item. Fix any failures.
6. **Run `uv run mkdocs build --strict`** to verify the page builds cleanly.
7. **Run `uv run pyright --project docs`** to verify snippets type-check.

### Concept exemplar

The hardest voice mode — system-as-subject, no "you." Follow the concept page template from doc-rules.md: opening line → basic example → how it works → common patterns → depth → next steps.

Key voice rules to enforce:
- Rule #1: Open with the construct as subject (not "it," "this," or "you can use")
- Rule #2: 10–18 words per explanatory sentence
- Rule #10: No "you" — system is the subject
- Rule #15: No imperative mood
- Rule #16: name → define → show → constrain

### Getting-started or recipe exemplar

Friendlier register — "you" is allowed. Code appears first, explanation after (getting-started) or full runnable app followed by "How It Works" prose (recipe).

Key voice rules:
- Rule #3: Main behavior first, caveats after
- Rule #17: Show code first, then explain (getting-started)
- Rule #21: Walk through one decision at a time in "How It Works" (recipe)
- "How It Works" must use flowing prose paragraphs, NOT bullet lists with bolded lead-ins

### Reference exemplar

Terse functional definitions. Tables before prose. No narrative arc. Distinct from concept voice.

Key checklist items (reference-mode addendum):
- Tables before prose in reference sections
- No narrative arc in annotation tables
- Terse functional definitions in table cells
- No admonitions in reference tables

### Cross-cutting requirements for all three:

- **First use of `D.*`, `states.*`, `C.*`, `P.*`, or `A.*`** must link to the canonical page for that module (FR#6)
- **First use of Bus, Scheduler, Api, Cache, App, StateManager, or Resource** must include a functional definition (FR#17)
- **Every code example** from a snippet file (FR#14)

## Focus

**Voice-guide.md** has 22 rules across three sections: "We Always" (1–9), "We Never" (10–15), "When X, Do Y" (16–22). The concept exemplar is the hardest because rules 10 and 15 (no "you," no imperative) conflict with the instinct to address the reader. Read the before/after examples in voice-guide.md — they demonstrate the exact transformation.

**doc-rules.md templates:** Concept pages have 6 parts, recipe pages 6 parts, getting-started pages 4 parts. Read the template for each exemplar's page type.

**Snippet infrastructure:** `pymdownx.snippets` with `check_paths: true` and base_path: `docs`. Include paths are relative to `docs/`, e.g., `pages/core-concepts/bus/snippets/file.py`. Section markers: `# --8<-- [start:name]` / `# --8<-- [end:name]`.

**Common voice violations** (from docs-context.md — created in T01): the 3 most common violations will be listed there. Watch for them in your writing.

## Verify

- [ ] FR#1: All three exemplar pages pass every item on the voice audit checklist
- [ ] FR#2: Concept exemplar uses system-as-subject voice throughout — no "you" outside getting-started/recipe
- [ ] FR#3: Getting-started/recipe exemplar uses direct "you" address with code-first ordering
- [ ] FR#6: Every first use of `D.*`, `states.*`, `C.*`, `P.*`, `A.*` links to the canonical page
- [ ] FR#14: Every code example comes from a snippet file via `--8<--` include — no inline code blocks
- [ ] FR#17: Every first use of Bus, Scheduler, Api, Cache, App, StateManager, or Resource has a functional definition
- [ ] AC#1: Voice audit checklist applied and all items pass for each exemplar
- [ ] AC#12: Module cross-links present on first use
- [ ] AC#16: No inline Hassette code examples — all from snippet files
- [ ] AC#19: Hassette term definitions present on first use
