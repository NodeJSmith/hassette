# Home (index.md)

**Status:** Exists (92 lines), needs JTBD redesign — good content but buries the hook
**Voice mode:** Marketing/getting-started hybrid — engaging, "you" allowed
**Page type:** Landing page
**Reader's job:** Decide in 10 seconds whether Hassette is worth their time, then find the right entry point for their situation.

## What was cut

The existing page works but the opening is two paragraphs before the reader
sees what Hassette actually does. The "Why Hassette?" bullet list repeats
what was already said. The "What you can build" list is generic enough to
describe any framework.

Changes:
- Hook tightened: one sentence that says what it is, one that says what makes
  it different. No paragraph-length pitch.
- "Why Hassette?" collapsed into the hook — the bullet list was restating the
  opening. The distinct value props (DI for events, test harness, type-safe
  config) belong in the opening sentence, not a separate section.
- "What you can build" replaced with a concrete code example. A code block
  does more in 10 seconds than a bullet list of abstractions.
- "See it in action" videos stay — they're the strongest content on the page.
- "Already using AppDaemon?" tightened to three concrete bullets (already good)
  and kept.
- "Next steps" streamlined — remove "Is Hassette right for you?" from the
  top-level list (it's linked in the opening) and add Recipes.

## Outline

### Logo + tagline
One-line tagline under the logo. Current tagline works: "An async-first Python
framework for writing Home Assistant automations as code — with type safety,
dependency injection, and a built-in test harness."

### H2: What is Hassette?
Two sentences max:
1. What it is: write HA automations as Python classes instead of YAML.
2. What makes it different: FastAPI-style DI for event handlers, Pydantic
   config, built-in test harness.

"Who it's for" line with link to "Is Hassette Right for You?"

### H2: See It in Action
Videos (autocomplete, event handling) + web UI screenshot. These are the
strongest proof — keep them prominent. Consider adding a minimal code example
alongside or between the videos for readers who prefer reading code to
watching video.

### H2: Quick Start
Three-line install command via `--8<--` include. One sentence linking to the
Quickstart guide with time estimate ("running app in about 30 minutes").

### H2: Already Using AppDaemon?
Three concrete improvements (Pydantic config, test harness, DI). Link to
Migration Guide. Keep as-is — this section is well-written.

### H2: Next Steps
Streamlined link list:
- Quickstart (local setup)
- Docker Deployment (production)
- Core Concepts (architecture)
- Recipes (copy-paste automations)
- Migration Guide (from AppDaemon)

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `getting-started/snippets/install.sh` | Keep | Quick start install command |

Any code block added to "See It in Action" must be a `--8<--` included snippet
file, not inline. Pyright CI catches drift automatically.

## Cross-Links

- **Links to:** Is Hassette Right for You?, Quickstart, Docker Deployment, Core Concepts/Architecture, Recipes, Migration Guide, Web UI
- **Linked from:** (entry point — all pages implicitly)
