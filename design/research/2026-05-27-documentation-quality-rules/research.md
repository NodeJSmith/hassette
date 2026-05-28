---
topic: "documentation-quality-rules"
date: 2026-05-27
status: Draft
---

# Prior Art: Writing Excellent Developer Framework Documentation

## The Problem

Developer documentation is often the first and most lasting impression of a framework. Bad docs kill adoption regardless of code quality. But "write better docs" isn't actionable — teams need concrete patterns for how to structure, write, and maintain documentation that works for readers at every skill level.

The specific challenge for Hassette: it's a Python framework for Home Assistant automations, targeting users ranging from "just got into HA and wants to automate lights" to "experienced Python developer building complex multi-app systems." The docs need to serve both without boring the expert or losing the beginner.

## How We Do It Today

Hassette's docs are already strong in several areas:

- **Tested code examples** via pymdownx snippets — external `.py` files included in docs and type-checked by CI (Pyright). This prevents drift.
- **Clear hierarchy** — getting-started -> core-concepts -> recipes -> advanced, with a migration section for AppDaemon users.
- **Comparison-driven teaching** — side-by-side AppDaemon vs Hassette tabs for migration concepts.
- **Real, complete code** — snippets have full imports, type hints, and config classes. Copy-paste-ready.
- **Auto-generated API reference** — mkdocstrings with a curated PUBLIC_MODULES allowlist.
- **Strategic admonitions** — warnings/notes at gotcha points, not decorative.

What's missing: no written rules for doc prose style, no checklist for what a complete feature doc includes, no guidance on example progression within a page, no explicit page structure template.

## Patterns Found

### Pattern 1: The Diataxis Quadrants (Tutorials / How-tos / Reference / Explanation)

**Used by**: Django, Canonical/Ubuntu, Gatsby, Sequin, NumPy, Cloudflare

**How it works**: Documentation is organized into four distinct types based on two axes: whether the user is studying or working (cognition vs. action), and whether they are learning or applying (acquisition vs. application).

- **Tutorials** are learning-oriented. They take the reader by the hand through steps to complete a project. The tutorial's job is to give confidence, not completeness. They should always work (tested, maintained) and result in something meaningful.
- **How-to guides** are task-oriented. They address specific goals ("How do I schedule a recurring task?"). They assume the reader knows the basics and skip explanation. Like cookbook recipes.
- **Reference** is information-oriented. API signatures, configuration options, class hierarchies. Accurate, complete, structured for lookup not reading. Auto-generation keeps it in sync.
- **Explanation** is understanding-oriented. Why things work the way they do, design decisions, trade-offs. Helps users build mental models. Architecture discussions and conceptual overviews live here.

The key insight: each type has different quality criteria. A tutorial that stops to explain every concept fails as a tutorial. A reference with tutorial walkthroughs becomes hard to scan. Mixing types produces docs mediocre at everything.

**Strengths**: Gives authors a clear decision framework for where content belongs. Makes gaps visible ("we have reference but no tutorials"). Navigable because each section serves one purpose.

**Weaknesses**: Can feel rigid for small projects. Requires discipline to keep types separate. Doesn't prescribe navigation structure within each quadrant.

**Example**: Django documentation at https://docs.djangoproject.com/en/6.0/ explicitly labels its four sections.

### Pattern 2: Progressive Disclosure and Layered Complexity

**Used by**: Vue.js, Tailwind CSS, FastAPI, Svelte

**How it works**: Beginners see the simplest version first, with complexity revealed incrementally. This operates at multiple levels:

- **Navigation level**: Sidebar progresses from "Getting Started" to "Essentials" to "Advanced." Users choose their depth.
- **Page level**: Each page starts simple and adds complexity. FastAPI introduces one concept per page, building on previous pages.
- **Example level**: Code examples start minimal (3-5 lines showing the core idea) and grow to production-realistic (with error handling, edge cases, configuration). Minimal teaches the concept; complete shows real usage.
- **API level**: Vue.js lets users toggle between Options API (simpler) and Composition API (more powerful) throughout the docs. Both paths are first-class.

Users should never have to understand the entire system before they can do something useful. Each layer is self-contained and functional.

**Strengths**: Serves beginners and experts with the same documentation. Reduces cognitive load. Users self-select depth.

**Weaknesses**: Maintaining parallel paths doubles documentation surface. Can hide important caveats in "advanced" sections. Requires careful IA to avoid users missing critical steps.

**Example**: Vue.js at https://vuejs.org/guide/introduction.html with its API preference toggle. FastAPI tutorial at https://fastapi.tiangolo.com/tutorial/

### Pattern 3: Concept-First Structure with Runnable Examples

**Used by**: Tailwind CSS, Pydantic, FastAPI

**How it works**: Each page introduces a concept, explains why it exists and when you'd use it, then shows a working code example. The concept is the organizing unit, not the API surface. Pydantic's docs organize around "Models", "Fields", "Validators", not around the class hierarchy.

Each concept page follows a consistent internal structure:
1. What is this? (1-2 sentences)
2. When would you use it? (motivation)
3. Basic example (minimal, runnable)
4. Common variations (with examples)
5. Edge cases and advanced usage
6. API reference for this concept's types/functions

Examples are progressive within each page: simplest possible usage first, then increasing complexity. Every example is complete enough to copy-paste and run.

**Strengths**: Maps to how developers think ("I need to validate input" not "I need the `validator` decorator"). Self-contained pages. Progressive examples serve both skimmers and deep-divers.

**Weaknesses**: Can lead to redundancy. Harder to use as pure API reference. Requires careful cross-linking.

**Example**: Pydantic concepts at https://docs.pydantic.dev/latest/concepts/models/

### Pattern 4: Tested Documentation Examples

**Used by**: Pydantic, Rust (rustdoc), Python (doctest), Elixir

**How it works**: Code examples in docs are extracted and executed as part of the test suite. In Python, via pytest's --doctest-modules (docstring examples) or --doctest-glob (examples in .md files). When a code example breaks, a test fails, and CI catches it before the broken example reaches users.

The discipline: if an example appears in documentation, it must be a test. If it can't be tested (requires external services), it must be explicitly marked as untested.

**Strengths**: Eliminates documentation drift for code examples. Forces examples to be complete and self-contained (which makes them better for learning). Catches breaking changes that would silently break docs.

**Weaknesses**: Adds test infrastructure complexity. Some examples are hard to test. Can make writing docs feel like writing tests, increasing friction for contributors.

**Example**: Pydantic's contributing guide at https://docs.pydantic.dev/latest/contributing/

### Pattern 5: The Quickstart Contract (Sub-5-Minute First Success)

**Used by**: Stripe, Vercel, Firebase, Supabase

**How it works**: The quickstart is a contract: follow these steps, have something working in under 5 minutes. This means ruthlessly cutting scope. The quickstart doesn't explain architecture, doesn't cover all options, doesn't handle edge cases. It shows the shortest path from zero to a working result.

Key constraints:
- Maximum 4 steps (completion drops from 40% to 21% at 5+ steps)
- Each step produces visible progress
- The result is meaningful (a working app, not "hello world")
- Prerequisites are stated explicitly and minimally

The quickstart is not the tutorial. The tutorial teaches concepts; the quickstart delivers a dopamine hit. Its job is to get users past the "should I invest time?" decision.

**Strengths**: Directly addresses the #1 reason developers abandon tools (lengthy setup). Creates emotional investment early. Provides a working baseline for tutorials to build on.

**Weaknesses**: Ruthless scoping is hard. Can mislead if simplicity doesn't reflect real-world complexity. Requires ongoing maintenance.

**Example**: Stripe quickstart at https://docs.stripe.com/get-started

### Pattern 6: Documentation-as-Product (The Stripe Model)

**Used by**: Stripe, Twilio, Plaid

**How it works**: Documentation is treated as a product with its own team, metrics, user research, and iteration cycles. At Stripe, documentation quality is part of engineering performance reviews. Engineers take writing classes. Docs auto-inject user's test API keys into code samples. Three-column layout (navigation, explanation, live code) is designed as UX, not a text dump.

Docs have a product owner, usage analytics, and a feedback loop. Pages are iterated based on data. The deeper principle: developers evaluate risk, not just features. Confusing docs feel risky. Clear docs reduce perceived integration risk.

**Strengths**: Best-in-class results. Creates a culture where writing is valued. Measurable outcomes.

**Weaknesses**: Requires significant investment. May be overkill for smaller projects. Three-column layout works for API reference but is less natural for tutorials.

**Example**: Stripe docs at https://docs.stripe.com

### Pattern 7: Code-Generated Documentation and Spec-Driven Sync

**Used by**: FastAPI, Stripe, Pydantic (mkdocstrings)

**How it works**: API reference is generated from source code. FastAPI generates OpenAPI specs from Python type annotations and renders interactive docs via Swagger UI. The pipeline is: source code -> spec -> rendered docs. Because docs are generated from code, they cannot drift.

This works best for reference. Tutorials, how-tos, and explanation still need humans. The win is eliminating the most tedious and drift-prone part so humans focus on parts that need judgment.

**Strengths**: Eliminates drift for API reference. Reduces maintenance burden. Interactive docs serve as documentation and testing tool.

**Weaknesses**: Generated docs can be sterile without human context. Only works for reference. Quality depends on docstring quality.

**Example**: mkdocstrings at https://mkdocstrings.github.io/

## Anti-Patterns

- **Architecture-First**: Engineers lead with "How It Works" because it's what they wrote most recently. Users need "How to Use It" first. Explanation is for users who already use the product and want to deepen understanding, not for new users evaluating adoption. (Source: Sequin blog)

- **D.O.C.S.** (Drift, Omission, Confusion, Stagnation): Drift is stale examples that break integrations. Omission is missing critical info that blocks developers entirely. Confusion is naming inconsistencies. Stagnation is never improving after launch. Fix priority: Omission > Drift > Confusion > Stagnation. (Source: DigitalAPI)

- **Reference-Only Documentation**: Many projects have only API reference and no tutorials, how-tos, or explanation. Reference answers "what does this function do?" but not "which function should I use?" or "how do these pieces fit together?" (Source: Diataxis, Fern)

- **The 5+ Step Quickstart**: Product tours with more than 4 steps drop from 40% completion to 21%. The impulse to be thorough in the quickstart directly undermines its purpose. (Source: developer onboarding benchmarks)

## Emerging Trends

- **AI-consumable docs (llms.txt)**: Developer tools publishing machine-readable documentation summaries alongside human docs. Documentation increasingly serves two audiences: humans and AI models.

- **Spec-driven everything**: The spec becomes the single source of truth; SDKs, docs, code examples, and types are all generated from it. Inverts the traditional "write code then document" workflow.

- **Proactive error documentation**: Error messages that link to relevant docs and suggest fixes, rather than static troubleshooting pages. Stripe's "Integration Insights" analyzes API request errors in real-time.

## Relevance to Us

Hassette already implements several of these patterns well:

- **Pattern 4 (Tested Examples)**: Already doing this via pymdownx snippets + Pyright CI. Stronger than most — the snippet approach is better than inline doctests because examples are full, importable Python files.
- **Pattern 7 (Code-Generated Reference)**: Already using mkdocstrings with a curated allowlist. The foundation is solid.
- **Pattern 5 (Quickstart)**: The getting-started flow exists but could be audited against the "4 steps, 5 minutes" constraint.

The biggest gaps are:

1. **No explicit Diataxis classification** (Pattern 1): The existing nav (getting-started / core-concepts / recipes / advanced) maps roughly to tutorials / explanation / how-tos / explanation, but the mapping isn't explicit or consistent. Some "core-concepts" pages mix explanation with how-to content.

2. **No page structure template** (Pattern 3): Concept pages don't follow a consistent internal structure. Some lead with "what," some with "why," some with code. A template (what / when / basic example / variations / edge cases / reference) would make every page predictable.

3. **No progressive example design** (Pattern 2): Examples tend to be either minimal or complete, but rarely show the progression within a single page. The "start simple, add complexity" pattern within each concept page is missing.

4. **No prose style guide**: Tone is generally good (direct, practical) but undocumented. No rules for voice, person, jargon handling, or how to address mixed skill levels.

5. **Migration-centric framing**: The docs currently assume AppDaemon migration as the primary entry point. A rules file should address how to write for users with no AppDaemon background — pure beginners who just want to automate their home.

## Recommendation

Build a doc rules file around three pillars, drawing from the strongest patterns:

1. **Page structure template** (from Patterns 1 + 3): Define what every concept page must contain and in what order. Classify pages by Diataxis type so authors know what they're writing.

2. **Example progression protocol** (from Patterns 2 + 4): Rules for how examples should progress within a page (minimal -> realistic -> production), plus the existing tested-snippet discipline.

3. **Prose style rules** (from the Google Developer Documentation Style Guide + our existing writing-quality.md): Voice, person, jargon handling, approachability for mixed skill levels.

The Stripe "docs-as-product" model (Pattern 6) is aspirational but requires investment that's probably premature for Hassette's current stage. The Diataxis quadrant classification (Pattern 1) and concept-first structure (Pattern 3) are the highest-leverage changes — they give authors a framework for deciding what to write and where it goes.

## Sources

### Reference implementations
- https://docs.djangoproject.com/en/6.0/ — Django docs, canonical Diataxis implementation
- https://fastapi.tiangolo.com/ — FastAPI, one-concept-per-page tutorial + auto-generated API docs
- https://vuejs.org/guide/introduction.html — Vue.js, API toggle for progressive disclosure
- https://svelte.dev/tutorial — Svelte, interactive REPL-based tutorial
- https://docs.pydantic.dev/latest/concepts/models/ — Pydantic, concept-first with tested examples
- https://docs.stripe.com — Stripe, three-column layout and docs-as-product

### Blog posts & writeups
- https://blog.sequinstream.com/we-fixed-our-documentation-with-the-diataxis-framework/ — Sequin's Diataxis adoption case study
- https://apidog.com/blog/stripe-docs/ — Analysis of why Stripe docs work
- https://raw.studio/blog/how-stripe-uses-4-developer-first-ux-principles-to-drive-massive-adoption/ — Stripe DX principles
- https://kenneth.io/post/insights-from-building-stripes-developer-platform-and-api-developer-experience-part-1 — Stripe platform insights
- https://medium.com/@houseofarby/why-stripes-api-docs-convert-3-better-than-yours-f6d502aceb7c — Stripe conversion analysis
- https://www.digitalapi.ai/blogs/api-documentation-common-mistakes — D.O.C.S. anti-pattern framework
- https://gist.github.com/zsup/9434452 — Documentation-driven development methodology
- https://medium.com/@lucy_kull/the-power-of-inclusive-documentation-empowering-developers-of-all-backgrounds-c5e97351f9e — Inclusive documentation
- https://www.youngcopy.com/insights/how-fast-is-your-api-onboarding-benchmark-your-first-call-time-in-five-minutes — Onboarding benchmarks
- https://buildwithfern.com/post/information-architecture-best-practices-documentation — IA for docs
- https://buildwithfern.com/post/best-llms-txt-implementation-platforms-ai-discoverable-apis — AI-consumable docs trend

### Documentation & standards
- https://diataxis.fr/ — Diataxis framework
- https://documentation.ai/blog/diataxis-framework — Diataxis explainer
- https://developers.google.com/style — Google Developer Documentation Style Guide
- https://developers.google.com/style/code-samples — Google code sample guidelines
- https://developers.google.com/style/inclusive-documentation — Google inclusive docs guide
- https://developers.google.com/style/accessibility — Google accessible docs guide
- https://docs.pytest.org/en/stable/how-to/doctest.html — pytest doctest integration
- https://www.writethedocs.org/guide/writing/beginners-guide-to-docs/ — Write the Docs community guide
- https://arxiv.org/pdf/2409.00514 — Academic paper on example-driven development
- https://www.doctave.com/blog/documentation-versioning-best-practices — Versioning best practices
