# Home (index.md)

**Status:** Exists (92 lines), solid landing page, voice polish needed
**Voice mode:** Marketing/getting-started hybrid — engaging, "you" allowed

## Outline

### H2: What is Hassette?
One-paragraph pitch. FastAPI analogy. "Who it's for" targeting.

**Update needed:** "Is Hassette Right for You?" link currently points to `hassette-vs-ha-yaml.md` — should also link to the new `evaluator.md` page.

### H2: Why Hassette?
Bulleted feature highlights: code, async, type-safe config, DI, test harness, web UI.

### H2: See It in Action
Code screenshots/examples: autocomplete, event handling, web UI.

### H2: What You Can Build
Brief examples of automation types.

### H2: Quick Start
Three-step teaser linking to Quickstart.

### H2: Already Using AppDaemon?
Link to Migration section.

### H2: Next Steps
Links to Quickstart, Evaluator, Core Concepts, Recipes.

## Snippet Inventory

The home page is the most-visited page — stale code here is the worst place for it. Every code example must come from a tested snippet file, not inline blocks.

| Snippet | Status | Notes |
|---|---|---|
| `getting-started/snippets/install.sh` | Keep (already `--8<--` included) | Quick start install command |
| New: `home_event_handling.py` | New | If the video section is supplemented or replaced with a code example, it must be a snippet |
| New: `home_quick_app.py` | New | If a "see it in action" code block is added alongside/instead of videos |

**Rule:** Any code block on this page uses `--8<--` includes. No inline code fences for app examples. Pyright CI catches drift automatically when snippets are external files.

## Cross-Links

- **Links to:** Evaluator, Quickstart, Migration overview, Core Concepts/Architecture, Recipes
- **Linked from:** (entry point — linked from everywhere implicitly)
