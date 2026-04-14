---
topic: "Documentation patterns from Python framework docs"
date: 2026-04-13
status: Draft
---

# Prior Art: Documentation Patterns from Python Framework Docs

## The Problem

Hassette's docs were recently rewritten and reviewed. The content is now accurate and well-structured, but the question is: could the docs be more effective at onboarding beginners and helping experienced users find what they need? Best-in-class Python framework docs (FastAPI, Pydantic, pytest) set a high bar — what patterns do they use that Hassette could adopt?

## How We Do It Today

Hassette uses Material for MkDocs with mkdocstrings for API reference generation. Code examples are external `.py` files in `snippets/` directories, included via `pymdownx.snippets` and type-checked with pyright — matching the FastAPI pattern. The nav is organized as: Getting Started → Core Concepts → Web UI → Testing → Advanced → Migration → Troubleshooting → API Reference. There is no explicit "How-to" or "Recipes" section. The current structure mixes tutorial-style and reference-style content within the same sections.

## Patterns Found

### Pattern 1: The Diataxis Four-Quadrant Organization

**Used by**: pytest (explicitly), Cloudflare, Gatsby, Vonage, Django (partially)
**How it works**: Documentation is split into four types: Tutorials (learning-oriented, linear), How-to Guides (task-oriented, goal-driven), Reference (information-oriented, austere), and Explanation (understanding-oriented, conceptual). Each type has different writing rules. The critical discipline is keeping types separate — a tutorial should not stop to explain theory; a how-to should not teach basics.

pytest's homepage directly labels these four quadrants. FastAPI achieves it structurally (Learn = tutorials, How-To Recipes = how-to, Reference = reference).

**Strengths**: Every piece of content has a clear home. Helps writers know what to write and how. Helps readers find content based on their current mode (learning vs. working).
**Weaknesses**: Can feel rigid for small projects. Requires discipline to maintain as docs grow.
**Example**: https://diataxis.fr/, https://docs.pytest.org/en/stable/

**Relevance to Hassette**: Hassette's Core Concepts section currently mixes tutorial-style explanations with reference-style method lists. The Getting Started section is tutorial-like but the Core Concepts pages oscillate. A "How-to" / "Recipes" section is entirely missing — users who want "how to debounce a state change" or "how to schedule a daily report" have no dedicated home for these.

### Pattern 2: Progressive Tutorial as a Linear Book

**Used by**: FastAPI, Django, Flask
**How it works**: The tutorial is a linear sequence where each chapter builds on the previous one. Prerequisites (language features, tooling) come before framework code. FastAPI starts with Python Types Intro → async/await → env vars → virtual environments — all before the first line of FastAPI code. The tutorial then progresses through ~35 pages building incrementally.

**Strengths**: Clear learning path. No "where should I read next?" confusion. Each page can assume prior knowledge.
**Weaknesses**: Significant authoring effort. Intermediate users may find it slow.
**Example**: https://fastapi.tiangolo.com/learn/

**Relevance to Hassette**: Hassette's Getting Started is 4 pages (Quickstart → Token → First Automation → Docker). The jump from First Automation to Core Concepts is steep — there's no progressive tutorial that walks through bus subscriptions, then filtering, then DI, then scheduling, each building on the last. Users go from "guided" to "reference" with no transition.

### Pattern 3: Task-Oriented How-To / Recipes Section

**Used by**: pytest, FastAPI, Django
**How it works**: How-to guides use titles that describe user goals, not system features. "How to debounce rapid state changes" not "Bus module reference." The list of how-to titles implicitly documents what the tool can do.

**Strengths**: Users find what they need by scanning titles. Encourages user-perspective authoring.
**Weaknesses**: Many small pages. Requires understanding user vocabulary.
**Example**: https://docs.pytest.org/en/stable/ (sidebar), FastAPI's How-To Recipes

**Relevance to Hassette**: Hassette has no recipes/how-to section. Common automation patterns (motion-triggered lights, presence detection, sunrise/sunset, debounced sensors, multi-room coordination) could each be a short, focused page. These would also serve as realistic examples that the Core Concepts pages currently lack.

### Pattern 4: Code Annotations (Material for MkDocs)

**Used by**: FastAPI, Pydantic, Material ecosystem
**How it works**: `content.code.annotate` allows numbered annotations inside code blocks that expand into explanatory tooltips. Users who understand the code skip them; beginners expand them. This keeps code clean while providing inline explanations.

**Strengths**: No visual clutter for experienced users. Rich context for beginners. Doesn't break code copy-paste.
**Weaknesses**: Annotation numbering can be fragile. Over-annotation is worse than none.
**Example**: FastAPI tutorial pages

**Relevance to Hassette**: Hassette's snippets currently rely on comments for explanation, which clutter the code. Code annotations would let the DI examples (which are the most confusing for beginners) explain each annotation parameter without inline comments.

### Pattern 5: Quick-Win MkDocs Features

**Used by**: FastAPI
**How it works**: Several Material for MkDocs theme features that Hassette doesn't currently enable significantly improve navigation and search UX.

Missing features:
- `content.code.annotate` — inline code explanations (see Pattern 4)
- `navigation.tabs` — top-level section tabs (Getting Started | Core Concepts | Reference)
- `navigation.path` — breadcrumbs showing current location
- `search.suggest` — search autocomplete
- `search.highlight` — highlight search terms on page
- `navigation.instant.prefetch` — prefetch links on hover for faster navigation

**Strengths**: Zero-effort UX improvements. Just config changes.
**Weaknesses**: `navigation.tabs` changes the visual layout significantly — may need nav restructuring.
**Example**: FastAPI's mkdocs.yml theme.features section

### Pattern 6: Scaffold-First Onboarding

**Used by**: Home Assistant, Django, Rails
**How it works**: Instead of asking users to create files manually, provide a command or template that generates a working project structure. HA has `script.scaffold integration`; Django has `django-admin startproject`.

**Strengths**: Eliminates "blank page paralysis." Users start from a known-working state.
**Weaknesses**: Requires building and maintaining the scaffold tooling.
**Example**: https://developers.home-assistant.io/docs/creating_component_index

**Relevance to Hassette**: The quickstart currently asks users to manually create directories and files. A `hassette init` command (or a template repo) that generates `config/hassette.toml`, `config/.env`, and `hassette_apps/main.py` with a working example app would reduce the onboarding friction significantly.

## Anti-Patterns

- **Explanation inside tutorials**: Diataxis warns against "writers who are anxious that their students should know things." Hassette's first-automation page has improved but still explains DI theory mid-tutorial. Link to explanation pages instead. (Source: https://diataxis.fr/tutorials/)
- **Feature-oriented how-to guides**: "How to use the Bus module" is not a how-to — it's reference. Real how-tos address user goals: "How to react to a light turning on." (Source: https://diataxis.fr/how-to-guides/)
- **Auto-generated reference as sole docs**: "Unfortunately too many developers think auto-generated reference is all the documentation required." Reference serves users who already know what they're looking for. (Source: https://diataxis.fr/reference/)

## Emerging Trends

- **Docs-as-code with CI validation**: Hassette already does this (snippets + pyright + ruff). Ahead of most comparable projects.
- **LLM-friendly docs**: FastAPI includes LLM prompts per language; Pydantic publishes `llms.txt`. Structured, self-contained docs serve both human and AI consumers.
- **`hassette init` / scaffold**: Generating working boilerplate before users write code is spreading. Reduces blank-page paralysis.

## Recommendation

**Highest-impact changes (effort vs. payoff):**

1. **Add a "Recipes" / "How-to" nav section** — 5-10 task-oriented pages like "Automate lights with a motion sensor," "Schedule a daily report," "Debounce rapid sensor changes," "Test an automation with the harness." These serve as both practical guides AND realistic examples that the Core Concepts pages currently lack. This is the single biggest gap compared to FastAPI/pytest.

2. **Enable quick-win MkDocs features** — `content.code.annotate`, `search.suggest`, `search.highlight`, `navigation.path`. These are config-only changes with immediate UX improvement.

3. **Add a `hassette init` scaffold command** — Generates project structure with a working example app. Replaces the manual file creation in the quickstart. This is a code change, not just docs.

4. **Consider `navigation.tabs`** — Top-level tabs (Getting Started | Core Concepts | How-To | Reference) would make the Diataxis structure visible in the UI. Requires some nav reorganization.

5. **Use code annotations for DI examples** — The dependency injection snippets are the most confusing part of the docs for beginners. Code annotations would let each `D.StateNew[T]` parameter be explained without cluttering the code.

**Not recommended right now**: Full Diataxis restructuring (too disruptive for the docs that just shipped), progressive tutorial book (high authoring effort for the current audience size).

## Sources

### Reference implementations
- https://fastapi.tiangolo.com/learn/ — FastAPI progressive tutorial structure
- https://fastapi.tiangolo.com/contributing/ — FastAPI docs-as-code architecture
- https://fastapi.tiangolo.com/alternatives/ — design inspirations page
- https://pydantic.dev/docs/validation/latest/ — Pydantic concept-first docs
- https://docs.pytest.org/en/stable/ — pytest Diataxis four-quadrant homepage
- https://docs.pytest.org/en/stable/getting-started.html — pytest minimal first example
- https://developers.home-assistant.io/ — HA developer docs architecture overview
- https://developers.home-assistant.io/docs/creating_component_index — HA scaffold-first tutorial

### Standards & methodology
- https://diataxis.fr/ — Diataxis documentation framework
- https://diataxis.fr/tutorials/ — tutorial anti-patterns
- https://diataxis.fr/how-to-guides/ — task-oriented how-to guidance
- https://diataxis.fr/reference/ — reference vs. other doc types

### Tooling
- https://mkdocstrings.github.io/ — API docs generation (already in use)
- https://squidfunk.github.io/mkdocs-material/ — Material for MkDocs features reference
