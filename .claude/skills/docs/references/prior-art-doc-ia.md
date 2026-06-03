---
topic: "documentation-information-architecture"
date: 2026-06-02
status: Draft
---

# Prior Art: Documentation Information Architecture

## The Problem

When designing the structure of developer docs, teams naturally mirror their code's module hierarchy: one page per component, headings that match class names, navigation that follows the import graph. This feels complete to the authors but produces docs that are hard to navigate for readers who arrive with a task ("how do I schedule a job?"), not a module name ("what does `hassette.scheduler.triggers` contain?").

The question is: what frameworks exist for designing doc structure around reader goals instead of code structure? And specifically, how should a doc-architect agent think about redesigning outlines from scratch?

## How We Do It Today

Hassette's doc structure is reader-journey-first at the *nav level* — the section ordering (Getting Started -> Core Concepts -> Web UI -> CLI -> Recipes -> Testing -> Migration -> Troubleshooting) follows a natural progression. Page templates exist for different types (concept, recipe, getting-started, reference). But at the *page level*, 28 of 56 outlines are structural copies of existing pages — the code-mirror anti-pattern crept in during outline creation even though the high-level architecture avoids it.

## Patterns Found

### Pattern 1: Diataxis — Four Documentation Types

**Used by**: Django, NumPy, Cloudflare, Sequin, Canonical/Ubuntu

**How it works**: All documentation falls on two axes — theory vs. practice, and learning vs. working — producing four types: tutorials (learning by doing), how-to guides (working by doing), reference (working by knowing), and explanation (learning by knowing). Each type has distinct quality criteria. Tutorials must be completable by a beginner following literally. How-to guides assume competence and address a real-world goal. Reference is austere and complete. Explanation is the only place for opinion, context, and "why."

The framework's strongest contribution is *diagnostic*: when a page feels wrong, it's usually mixing types. A tutorial that pauses to explain architecture theory loses momentum. A reference page with step-by-step instructions confuses readers looking for a quick fact.

**Strengths**: Simple, widely adopted, diagnostic power for identifying type-mixing. Provides clear "what goes where" rules.

**Weaknesses**: Doesn't cover all doc types (troubleshooting, migration guides, changelogs). Doesn't address page-level structure or cross-page navigation. Teams sometimes force-fit content into quadrants.

**Example**: https://diataxis.fr/

### Pattern 2: Goal-Oriented Navigation (Stripe Model)

**Used by**: Stripe, Twilio, Plaid

**How it works**: Top-level nav reflects what developers want to accomplish ("Accept a payment"), not API surface. Each goal-oriented section contains its own quickstart, explanation, and API reference. Code samples are contextualized (shown with surrounding application code) and personalized.

**Strengths**: Extremely effective for API products where developers arrive with a task. Reduces time-to-first-integration.

**Weaknesses**: Expensive to maintain — same API endpoint appears in multiple guides. Better for API products than frameworks. Requires a documentation team or strong engineering culture around docs.

**Example**: https://docs.stripe.com/payments

### Pattern 3: Persona + Jobs to Be Done

**Used by**: GitBook methodology, Adobe, enterprise doc teams

**How it works**: Define 2-4 reader personas, then identify their Jobs to Be Done — not who they are, but what they need right now. Map each job to a documentation path. The same person uses different parts of the docs depending on their current job (evaluating vs. integrating vs. debugging at 2am).

**Strengths**: Reveals structural gaps that topic-based organization misses. Produces docs that feel written for the reader's specific situation.

**Weaknesses**: Requires actual user research for accurate personas. Teams that guess personas based on internal assumptions reproduce the codebase-mirror anti-pattern with extra steps.

**Example**: https://gitbook.com/docs/guides/docs-workflow-optimization/documentation-personas

### Pattern 4: Progressive Disclosure with Tiered Complexity

**Used by**: Svelte, Vue, React

**How it works**: Documentation in concentric rings of complexity. Outermost ring (getting started) assumes nothing and teaches the minimum viable subset. Next ring (core concepts) covers the 80% case. Inner rings (advanced, internals) cover edge cases and framework internals. The key decision is what goes in the outermost ring — the best implementations identify one "aha moment" and optimize the outer ring to reach it fast.

**Strengths**: Matches natural learning progression. Readers self-select their depth. Works well for frameworks.

**Weaknesses**: Requires judgment about the "80% case." Teams often include too much in the getting-started tier.

**Example**: https://svelte.dev/docs

### Pattern 5: Documentation Journeys (Narrative Paths)

**Used by**: Adobe Experience Manager

**How it works**: Curated narrative paths through existing documentation — not new pages but an overlay. A sequence of links to existing pages stitched together with transitional prose. Solves "I don't know what I don't know" without restructuring existing content.

**Strengths**: Doesn't require restructuring existing docs. Adds guided paths on top of reference material.

**Weaknesses**: Expensive to maintain. Links break silently when underlying pages change. Better for large enterprise products than small dev tools.

**Example**: https://experienceleague.adobe.com/en/docs/experience-manager-cloud-service/content/overview/documentation-journeys

## Anti-Patterns

- **Codebase-mirror structure**: Organizing docs to match the source code module hierarchy. Internal teams fall into this because they think about the product in terms of its code structure. Card sorting with external users is the primary remedy. *(Cited: Fern IA guide, Smashing Magazine card sorting guide)*

- **Explanation-first ordering**: Leading with "how it works" before the reader has touched the product. Engineers find architecture interesting; readers find it tedious. "Starting with explanatory content felt like a chore to readers and was like asking them to study for a test." *(Cited: Sequin blog, Diataxis framework)*

- **Type-mixing within pages**: A single page that starts as a tutorial, detours into explanation, includes reference tables, and ends with how-to steps. The reader can't predict what they'll find. Diataxis identifies this as the most common cause of confusing docs. *(Cited: Diataxis, Tom Johnson)*

- **Deep nesting**: More than two levels of nav depth. "Only create a maximum two levels of subpages — any more and things can become confusing." *(Cited: GitBook structure guide)*

## Emerging Trends

**AI as documentation consumer**: 70% of documentation teams now factor AI into IA decisions (GitBook State of Docs 2026). The structural practices that help AI (clear headings, single-topic pages, explicit scope markers) are the same ones that help human readers.

**Documentation as product**: Stripe's model — doc quality affects promotions, custom tooling, writing classes for engineers — is spreading. Structure optimized for reader outcomes, not author convenience.

## Relevance to Us

Hassette's existing nav already follows Progressive Disclosure (Pattern 4) — the section ordering is reader-journey-first. The voice guide already draws from Svelte. These are strengths.

The gap is at the *outline/page level*. The outlines were created by reading existing pages and transcribing their heading structure — the codebase-mirror anti-pattern at the page level, even though the nav avoids it at the section level. The result: 28 of 56 outlines are structural copies.

The most actionable patterns for redesigning outlines:

1. **Diataxis as diagnostic lens** — for each page, ask: "is this a tutorial, how-to, reference, or explanation?" If the answer is "all of them," the page needs splitting. This is already partially reflected in the page templates (concept pages, recipe pages, getting-started pages), but the outlines don't enforce it.

2. **JTBD per page** — before writing an outline, answer: "What job is the reader doing when they land on this page? What do they need to know to complete that job?" The outline should cover exactly that, nothing more. A reader on the Bus filtering page has a different job than a reader on the Bus overview page.

3. **Progressive disclosure within pages** — simplest case first, advanced in collapsible sections or linked pages. The existing outlines often present features in API order (method by method) rather than complexity order.

4. **Anti-codebase-mirror check** — for each outline, ask: "Would a user group these concepts this way, or only someone who has read the source code?" If the outline's H2s map 1:1 to class methods, it's a reference page pretending to be a concept page.

## Recommendation

**Adopt Diataxis as a diagnostic lens + JTBD per page** as the framework for the doc-architect agent. Not rigid Diataxis quadrants (Hassette already has its own page types that work), but the diagnostic question: "What type is this page? Is it mixing types?" combined with "What job is the reader doing here?"

The practical workflow for redesigning an outline:
1. Name the page type (concept / recipe / getting-started / reference / troubleshooting / migration)
2. State the reader's job in one sentence ("Understand how the bus filters events" or "Set up a motion-triggered light")
3. List what the reader needs to know to complete that job — and nothing else
4. Order by complexity (simplest first), not by API surface
5. Check: would a user organize this page this way, or only a developer who has read the source?

This is lightweight enough for a subagent to execute per-page, and the diagnostic questions are concrete enough to produce different outlines from the copy-paste approach.

Card sorting (Pattern 7 from web research) would be ideal for validating the new structure, but requires access to real users. For now, the JTBD + Diataxis diagnostic is the best available proxy.

## Sources

### Frameworks & standards
- https://diataxis.fr/ — Diataxis framework (four documentation types)
- https://buildwithfern.com/post/information-architecture-best-practices-documentation — Fern's IA guide (architecture tiers)

### Reference implementations
- https://docs.stripe.com/payments — Stripe goal-oriented docs
- https://svelte.dev/docs — Svelte progressive disclosure
- https://experienceleague.adobe.com/en/docs/experience-manager-cloud-service/content/overview/documentation-journeys — Adobe documentation journeys

### Blog posts & writeups
- https://idratherbewriting.com/blog/what-is-diataxis-documentation-framework — Tom Johnson's Diataxis review
- https://blog.sequinstream.com/we-fixed-our-documentation-with-the-diataxis-framework/ — Sequin's Diataxis case study
- https://www.moesif.com/blog/best-practices/api-product-management/the-stripe-developer-experience-and-docs-teardown/ — Moesif Stripe docs teardown
- https://apidog.com/blog/stripe-docs/ — Apidog Stripe docs analysis
- https://dev.to/erikaheidi/information-architecture-and-content-planning-for-documentation-websites-2cg6 — IA planning for doc sites
- https://docsbydesign.com/2026/02/15/what-makes-documentation-ai-ready-structure/ — AI-ready documentation structure

### Methodology & guides
- https://gitbook.com/docs/guides/docs-best-practices/documentation-structure-tips — GitBook structural constraints
- https://gitbook.com/docs/guides/docs-workflow-optimization/documentation-personas — GitBook persona + JTBD methodology
- https://github.blog/developer-skills/documentation-done-right-a-developers-guide/ — GitHub docs guide
- https://www.nngroup.com/articles/card-sorting-definition/ — NNGroup card sorting reference
- https://www.smashingmagazine.com/2014/10/improving-information-architecture-card-sorting-beginners-guide/ — Card sorting tutorial

### Industry reports
- https://www.gitbook.com/blog/state-of-docs-2026 — GitBook State of Docs 2026
