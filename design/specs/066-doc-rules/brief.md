# Brief: Documentation Quality Rules

**Date:** 2026-05-27
**Status:** explored

## Idea

Create a `.claude/rules/doc-rules.md` that codifies how Hassette documentation should be written — covering when docs are needed, what voice to use, how pages should be structured, and how examples should teach. The primary consumer is Claude (AI agent), so the rules need to be concrete enough to produce consistently good docs without human revision. The existing `writing-quality.md` handles what to *avoid* (AI slop patterns); this file defines what to *aim for*.

## Key Decisions Made

- **Audience for the rules file**: primarily Claude. The rules should produce docs that don't need tone/style rework.
- **Core problem to solve**: docs come out too formal/academic — passive voice, abstract framing, no personality. The structural stuff (page layout, nav) is secondary to getting the voice right.
- **Voice model**: Svelte-style — friendly, encouraging, slightly playful. Makes complex things feel approachable. Celebrates simplicity. Not a textbook.
- **Relationship to writing-quality.md**: complementary, not overlapping. writing-quality.md catches generic AI tells (em dashes, significance inflation). Doc rules define the positive target — what Hassette docs should *sound like*.
- **Skill-level strategy**: layer within pages, not separate tracks. Lead with the simple case, add depth as you scroll down. Collapsible sections or admonitions for advanced detail. One canonical page per concept.
- **Template rigidity**: soft template. Suggest a default page structure (what/when/example/variations/advanced) but make it a starting point, not a straitjacket. Voice and tone rules are the hard requirements.
- **Trigger scope**: the doc rules file owns BOTH "when to write docs" AND "how to write them." Trigger: anything a user can interact with directly or could encounter (including different exception types). This subsumes and expands the trigger from design-completeness.md.

## Open Questions

- **How to handle the overlap with design-completeness.md**: doc-rules will own the trigger for when docs are needed. Should design-completeness.md be updated to defer to doc-rules for the documentation section, or should both files coexist with their own triggers? Need to avoid contradictory guidance.
- **Example progression specifics**: the research showed examples should progress from minimal to production-realistic within a page. Need concrete examples of what "minimal" and "production-realistic" look like for Hassette (e.g., a 3-line bus handler vs a full app with config, error handling, and scheduling).
- **Admonition conventions**: the existing docs use warnings/notes strategically, but there's no rule for when to use which type. Should the rules prescribe admonition types (tip for shortcuts, warning for gotchas, note for context)?
- **Diataxis classification**: should the rules explicitly classify existing page types (getting-started = tutorial, recipes = how-to, core-concepts = explanation) or leave classification implicit?

## Scope Boundaries

**In scope:**
- Voice and tone guidance with concrete good/bad examples
- When documentation is required (trigger conditions)
- Soft page structure template for concept pages
- Example design principles (progression, completeness, testability)
- Layering strategy for mixed skill levels
- How to handle jargon and prerequisites

**Explicitly out of scope:**
- Rewriting existing docs to match the rules (separate effort)
- CI enforcement of prose style (no tooling, just guidance)
- Navigation/information architecture changes (the current hierarchy works)
- API reference generation rules (mkdocstrings config is already good)
- Changelog/release notes (covered by changelog-quality.md)

**Deferred:**
- Auditing the quickstart against the "4 steps, 5 minutes" benchmark
- Adding Diataxis labels to existing pages
- Snippet aging/retirement policy

## Risks and Concerns

- **Voice is hard to codify for AI.** "Friendly and encouraging" can tip into chatbot cheerfulness or condescension. The rules need concrete before/after examples, not just adjectives. The more examples of good Hassette voice, the better.
- **Soft templates might get ignored.** If the template is too soft, Claude will fall back to its default academic style. The voice rules need to be the loudest signal — positioned first, with the most examples.
- **Dual trigger risk.** If both design-completeness.md and doc-rules.md define when docs are needed, Claude could get contradictory signals. Clean delineation needed.
- **Rules file size.** Good voice guidance needs examples, and examples are verbose. The file could get long. May need to balance density against the instruction-quality.md principle that shorter, more focused rules get followed better.

## Codebase Context

- Rules live in `.claude/rules/` as prescriptive markdown. Existing examples: `design-completeness.md`, `changelog-quality.md`, `frontend-worktree.md`.
- 76 doc pages across 11 nav sections. Primarily authored by Jessica with occasional AI assistance.
- CI enforces `mkdocs build --strict` and `pyright --project docs` (type-checks snippets). No prose style enforcement.
- Snippets are external `.py` files included via `--8<--` syntax — already tested, already complete. The rules should reinforce this pattern, not introduce a new one.
- Prior art research saved at `design/research/2026-05-27-documentation-quality-rules/research.md`.
