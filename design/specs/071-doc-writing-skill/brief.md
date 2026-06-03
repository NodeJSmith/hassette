# Brief: Generalize doc-overhaul into a scale-aware doc-writing skill

**Date:** 2026-06-03
**Status:** explored

## Idea

Replace the single-purpose `hassette.doc-overhaul` skill with a general-purpose doc-writing skill that runs the same proven process (JTBD outline, voice-calibrated writing, Opus review, mechanical quality gates) at any scale: one page, a section rewrite, or docs for a new feature. The full overhaul mode disappears since we won't do another full rewrite. The skill keeps the process opinionated but adapts its weight to the scope.

## Key Decisions Made

- **Hassette-scoped for now.** Not trying to make this portable to other projects. Hassette-specific content (source file paths, import conventions, module aliases, exemplar paths) stays in the reference files.
- **Always calibrate.** Read the voice calibration artifact every time, even for a single page. Voice consistency matters more than saving a few seconds of context loading.
- **Always outline first.** The JTBD outline step runs even for a single page. It's cheap and catches structural problems before writing starts.
- **Smart default with escape hatches.** Full pipeline (outline, write, review, verify) by default. "Just outline these pages" or "just review this page" invoke individual steps.
- **Nav placement depends on scale.** For 1-2 pages, the user specifies where they go. For a new section, the skill proposes placement.
- **One skill, not split.** The individual steps (outline, write, review) are robust standalone, but splitting into separate skills fragments the quality guarantees. One skill with mode detection keeps the process coherent.
- **Process is robust enough for partial invocation.** The JTBD outline, the voice-calibrated writer prompt, and the Opus reviewer each produce good output independently. The pipeline is the default, not the only mode.

## Open Questions

- **Skill name and triggers.** "Write docs for X" and "update the docs" both feel natural. Name candidates: `docs`, `doc-write`, `write-docs`. Needs to not collide with the `docs:` commit type or `mkdocs` commands in muscle memory.
- **What happens to the existing docs-context-example.md?** It has the PR #970 exemplar paths baked in. Should it become the live calibration artifact (updated when exemplars change), or stay as an example with a separate live version?
- **Mechanical quality gates at small scale.** The full sweep (snippet orphans, xref coverage, bare symbols, link checker) makes sense for 5+ pages. For a single page, running all six tools is overkill. Should the skill run a subset based on scope, or always run everything?
- **How does the skill discover what pages are needed?** For "write docs for the new cache feature," something needs to figure out which pages to create (concept page? recipe? API reference updates?). The design-completeness rule already lists triggers for when docs are needed. The skill could read that rule and propose a page list.

## Scope Boundaries

**In scope:**
- Rewrite SKILL.md to be scale-aware (detect scope from arguments, adjust process weight)
- Update writing-prompt-template.md to support incremental work (not just "write from blank")
- Keep all reference files (prior-art, retrospective, docs-context-example, writing-prompt-template)
- Rename skill from `hassette.doc-overhaul` to something that signals general doc work

**Explicitly out:**
- Making the skill portable to other projects (stays hassette-scoped)
- Changing the voice-guide.md or doc-rules.md
- Adding new mechanical quality gate scripts
- Changing the existing docs

**Deferred:**
- Extracting this to Claudefiles as a cross-project skill (only after it proves itself on hassette incremental work)

## Risks and Concerns

- **Dilution risk.** The overhaul skill worked because it was opinionated about a specific process. Generalizing could turn it into "a skill that does doc stuff" with too many modes. Mitigate by keeping the pipeline as the default and treating escape hatches as exceptions, not equal modes.
- **Untested at small scale.** The process was proven on a 76-page rewrite. A single-page invocation hasn't been tested. The JTBD outline step may feel like overhead for one page, even if it's objectively cheap. Worth trying before committing to the design.
- **Calibration artifact staleness.** The docs-context-example.md points to PR #970 exemplars. If those pages change significantly, the calibration drifts. Need a lightweight way to verify exemplar paths are still valid.

## Codebase Context

- Current skill: `.claude/skills/doc-overhaul/` (106-line SKILL.md + 4 reference files, 708 lines total)
- Voice rules: `.claude/rules/voice-guide.md` (22 rules with before/after examples)
- Doc rules: `.claude/rules/doc-rules.md` (page templates, snippet conventions, layering)
- Design completeness rule: `.claude/rules/design-completeness.md` (triggers for when docs are needed)
- Quality gate scripts: `tools/check_snippet_orphans.py`, `tools/check_xref_coverage.py`, `tools/check_bare_symbols.py`
- Hassette-specific references in writing-prompt-template.md: 17 occurrences (source file paths, import conventions)
