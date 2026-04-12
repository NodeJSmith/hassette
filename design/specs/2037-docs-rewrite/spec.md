---
feature_number: "2037"
feature_slug: "docs-rewrite"
status: "approved"
created: "2026-04-11T00:00:00Z"
---

# Spec: Hassette Documentation Rewrite

## Problem Statement

The Hassette documentation was written by the framework author without formal technical writing experience. The result is a set of pages with inconsistent quality — some sections are thin, others are overly dense or poorly structured, a comparison page packs too much content onto a single page, and a testing page shows signs of unconstrained agent-generated bloat. Navigation structure, page sizing, and content depth have never been evaluated by someone who knows how to write technical documentation. Some content may also be stale relative to the current codebase. The docs need a comprehensive, ground-up review and rewrite before Hassette is shared publicly.

## Goals

- A new user with Python experience can find the docs, understand what Hassette is, and have a working automation running within 30 minutes.
- Every publicly documented feature reflects the current state of the codebase — no stale instructions, no missing capabilities.
- The docs are polished enough to link from a public forum post (Reddit, GitHub, Discord) without embarrassment.
- The navigation structure is evaluated and restructured where needed, with page sizing and depth calibrated to the content.
- The Material theme configuration and any custom CSS are verified to support the content formats being used (tabs, comparison tables, side-by-side code blocks).
- The API reference (auto-generated via mkdocstrings) is evaluated for completeness — the configuration, page structure, and underlying docstring quality are assessed and gaps flagged.

## Non-Goals

- Nothing is explicitly off-limits. Full nav restructure, page merges/splits, new pages, removal of outdated pages, docstring improvements, and theme configuration changes are all permitted if warranted.
- The rewrite does not extend to the Hassette source code itself — only documentation artifacts (Markdown, snippets, mkdocs config, CSS). Docstring improvements needed to support the API reference are the one exception.

## User Scenarios

### New user: Python developer encountering Hassette for the first time

- **Goal:** Understand what Hassette is, decide if it's worth trying, and get something working quickly.
- **Context:** Found Hassette via a link (Reddit, GitHub README) and has no prior context.

#### First contact and decision

1. **Lands on the docs home page**
   - Sees: What Hassette is, who it's for, what it can do — without reading multiple pages.
   - Decides: Is this worth my time? Do I understand what problem it solves?

2. **Reads Getting Started**
   - Sees: Clear setup instructions for their situation (local dev or Docker).
   - Then: Has a running Hassette instance and a simple working automation.

#### Deeper learning

3. **Navigates to a Core Concepts page**
   - Sees: A focused explanation of one concept — not a wall of text.
   - Decides: Do I understand how this part works?
   - Then: Can proceed with confidence or follow a cross-reference.

---

### AppDaemon user: Evaluating whether to migrate

- **Goal:** Understand how Hassette compares to AppDaemon and what migration would look like.
- **Context:** Already uses AppDaemon and knows it well; looking for something better.

#### Migration assessment

1. **Finds the comparison or migration page**
   - Sees: A direct, honest comparison of Hassette vs AppDaemon — including where AppDaemon is still better.
   - Decides: Is the migration effort worth it?

2. **Reads how familiar concepts map**
   - Sees: Side-by-side code examples showing how AppDaemon patterns translate to Hassette equivalents.
   - Then: Can estimate how much rewriting their existing apps would require.

---

### Author: Preparing docs before going public

- **Goal:** Know that the docs are accurate, complete, and well-structured before linking them publicly.
- **Context:** Writing is done; needs external-quality review and rewrite.

#### Quality gate

1. **Nav audit is reviewed and approved**
   - Sees: A structured proposal for revised navigation, page structure, and theme/CSS recommendations.
   - Decides: Which structural changes to accept before content work begins.

2. **Each section is rewritten**
   - Sees: Updated pages with verified accuracy (agent read the source) and flagged uncertainties.
   - Decides: Whether flagged uncertainties need correction or are acceptable.

## Functional Requirements

1. A nav/structure audit document is produced before any content is rewritten. It covers: current nav structure evaluation, recommended restructuring (with rationale), page splitting or merging recommendations, Material theme configuration gaps, CSS needs for comparison-heavy pages, and a snippet dependency map (a table of {snippet file → pages that include it}, produced by scanning all `--8<--` directives across the doc corpus).

2. The audit specifically evaluates the AppDaemon comparison page (`pages/appdaemon-comparison.md`) and the Hassette vs. YAML Automations page (`pages/getting-started/hassette-vs-ha-yaml.md`) and recommends how to restructure or split each. These are distinct pages with different concerns: the AppDaemon comparison page is potentially too long and split-worthy; the Hassette-vs-YAML page may be misplaced in Getting Started rather than needing a structural split.

3. The audit evaluates the mkdocstrings API reference configuration and produces a gap list of modules or classes with insufficient docstrings. A public class or function is considered documented if it has at least a one-line summary and all parameters with non-obvious types are annotated. A dedicated content WP fills highest-priority docstring gaps for the public API surface (App, Bus, Scheduler, Api, StateManager, test_utils public layer). The audit also verifies whether the registry and converter classes should remain public, and clarifies the internal/external boundary in test_utils so only the public layer is documented.

4. Content rewrites proceed only after the nav audit is approved. The nav audit WP outputs a structured artifact containing: (a) the proposed new nav tree as a before/after `mkdocs.yml` nav block diff, (b) per-page recommendations (restructure/split/merge/keep), and (c) theme/CSS recommendations. The caliper orchestrator pauses after the nav audit WP completes and requires an explicit author approval signal — a committed comment in the audit document or an explicit chat signal — before scheduling content WPs. The approval records which structural changes are accepted.

5. Each content rewrite WP reads the relevant source code files alongside the doc page to verify accuracy. Inaccuracies are corrected. Anything the agent cannot confidently verify is explicitly flagged using a `!!! warning "Needs human review"` admonition block (visually prominent in the Material theme and greppable). Each content WP includes a "Flags" section in its completion report — a bulleted list of every flag added, with page name and a one-line description of the uncertainty.

6. The testing page is restructured so that it leads with the Quick Start harness pattern and core assertion API. Advanced content (event factories, time control, concurrency locking details) is either moved to clearly-marked subpages or placed in a dedicated "Advanced" section that a beginner can skip. The page order must not require beginners to read advanced content to understand the basic testing model.

7. Each rewritten page is appropriate for both target audiences: Python developers new to Home Assistant, and AppDaemon users considering migration. HA-specific concepts are explained; Python knowledge is assumed.

8. Page length and depth are calibrated to content — thin pages are expanded, overly long pages are split or trimmed.

9. All code examples in the docs exist as runnable `.py` files in the relevant `snippets/` directory, embedded via `--8<--` with section markers (`# --8<-- [start:section-name]` / `# --8<-- [end:section-name]`) so only the relevant portion appears in the rendered page. Snippet files must contain all necessary imports and be valid, parseable Python. This makes every example independently auditable and enables CI verification (e.g., `python -m py_compile` or pytest on all snippet files). Any inline code blocks not already in snippet files must be converted during the rewrite.

10. The nav in `mkdocs.yml` is updated to reflect any structural changes approved in the audit.

## Edge Cases

- A doc page references functionality that exists in the source code but is undocumented or incomplete — the rewrite should flag this as a documentation gap, not silently omit it.
- A doc page describes functionality that no longer exists in the source — the page should be corrected or removed, not left misleading.
- The AppDaemon comparison page may be best split into multiple pages — the audit should recommend the split point rather than force everything onto one page.
- Some snippet files may be embedded via `--8<--` includes. These are shared between pages; the snippet dependency map produced in the nav audit WP must be referenced by any content WP that touches a file in a `snippets/` directory. The WP completion report must list all other pages affected by the changed snippet.
- Docstring improvements to support the API reference are in scope but must not change public API behavior.

## Dependencies and Assumptions

- The source code in `src/hassette/` is the source of truth for accuracy. Doc pages that conflict with source are wrong.
- MkDocs Material theme is the rendering target. Any CSS or theme recommendations must be compatible with Material.
- The nav audit WP runs and is approved before WP planning (`/mine.draft-plan`) begins. WP grouping and page-level granularity are determined from the approved nav structure, not specified in advance.
- The caliper workflow orchestrates execution: after nav audit approval, content WPs are planned against the approved nav and executed in section-level groupings.
- The technical writer agent (`engineering-technical-writer`) is the executor for all content WPs.
- The `engineering-technical-writer` agent has access to the full repository to read source files.

## Acceptance Criteria

- [ ] A nav audit document exists, has been approved with an explicit author signal, and content WPs are planned from the approved structure.
- [ ] Every page in the approved nav structure has been rewritten or reviewed and confirmed accurate.
- [ ] No page contains content that contradicts the current source code without a `!!! warning "Needs human review"` admonition.
- [ ] The testing page leads with the Quick Start harness pattern; advanced content is separated so beginners can skip it.
- [ ] The AppDaemon comparison content is restructured into a dedicated multi-page Migration Guide section.
- [ ] The mkdocstrings API reference has been evaluated; docstring gaps for the public API surface are closed; the registry/converter class public status and test_utils internal/external boundary are verified.
- [ ] A walkthrough of the full Getting Started path has been completed (by the technical writer or author), confirming no step requires off-page knowledge beyond Python basics.
- [ ] All `--8<--` snippet includes resolve correctly in the final build.
- [ ] `mkdocs build` passes after each content WP merges, not only at project completion. A failing build after a WP merge blocks subsequent WPs until fixed.
- [ ] `mkdocs build` completes without errors or warnings after all changes.
- [ ] Any CSS defects identified in the nav audit are corrected before the rewrite is considered complete — either by updating the stylesheet with correct Material theme selectors, registering it via `extra_css:` in `mkdocs.yml`, or removing it if no longer needed.

## Open Questions

- Is there a preferred length or page count target for the Getting Started flow (e.g., should Docker setup remain split across four pages or be consolidated)? The nav audit WP should evaluate this and present a recommendation.
- **FR#7 interpretation (TENSION):** Does "appropriate for both target audiences" mean (a) each page cross-references AppDaemon equivalents inline, or (b) each page uses only knowledge that both audiences share (Python, no assumed HA expertise)? If (b), the requirement is already met by the HA-concepts-explained, Python-assumed baseline. The nav audit WP should clarify which interpretation is intended and whether any additional cross-referencing is needed.

## Resolved Questions

- *AppDaemon comparison structure:* Multi-page Migration Guide section (preferred direction; nav audit confirms/refines).
- *Intentionally undocumented features:* None — document the full public surface. The audit will verify the registry/converter class public status and the test_utils internal/external boundary before content WPs touch those areas.
