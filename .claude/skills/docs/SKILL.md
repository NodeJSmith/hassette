---
name: docs
description: "Use when the user says: \"write docs for X\", \"update the docs\", \"add docs for this feature\", \"rewrite the testing docs\", \"outline these pages\", \"review this doc page\". Scale-aware doc writing with JTBD outlines, voice calibration, and writer/reviewer subagent pairs."
user-invocable: true
references:
  - references/docs-context-example.md
  - references/writing-prompt-template.md
  - references/retrospective.md
  - references/prior-art-doc-ia.md
---

# Docs

Write, rewrite, or review documentation pages at any scale. Runs the same process whether the scope is one page or an entire section: JTBD outline per page, voice-calibrated Sonnet writer, Opus reviewer, mechanical quality gates.

The process was proven on the PR #970 overhaul (76 pages, 267 snippets). See `references/retrospective.md` for what made it work and `references/prior-art-doc-ia.md` for the Diataxis/JTBD research behind it.

## Arguments

$ARGUMENTS -- what to write or update. Examples:
- `write docs for the new cache feature`
- `rewrite the testing section`
- `add a recipe for presence detection`
- `outline the scheduler pages` (outline only, skip writing)
- `review docs/pages/core-concepts/bus/index.md` (review only, skip writing)

If empty, ask what needs documenting.

## Pre-flight: Calibrate Voice (always runs)

Read these files at the start of every invocation, regardless of mode or scope:

1. `.claude/rules/voice-guide.md` -- the 22 voice rules
2. `.claude/rules/doc-rules.md` -- page templates, snippet conventions
3. `references/docs-context-example.md` -- voice calibration artifact with exemplar paths, pass/fail checklist, and top violation patterns
4. The exemplar page(s) matching the page type(s) being worked on:
   - Concept: `docs/pages/core-concepts/bus/index.md`
   - Recipe: `docs/pages/recipes/motion-lights.md`
   - Reference: `docs/pages/core-concepts/bus/dependency-injection.md`

For mixed batches, read all three exemplars.

## Phase 1: Scope

### Detect mode from arguments

Parse the arguments and announce the detected mode to the user before proceeding:

> Detected mode: **<mode>** (<reason>). Running phases: <list>.

| Trigger | Mode | Phases |
|---|---|---|
| "outline" in args, no "write"/"update" | **Outline only** | Phase 2 |
| "review" in args, no "write"/"update" | **Review only** | Phase 3 (review step only) |
| Everything else | **Full pipeline** | Phases 2, 3, 4 |

If the args are ambiguous (e.g., "outline and then write"), default to full pipeline and say so.

### Determine page list

**If the user named specific pages:** use those.

**If the user named a feature or topic:** read `.claude/rules/design-completeness.md` to determine what pages are needed. Explore the codebase to understand the feature's scope. Propose a page list with:

- Page type for each (concept, recipe, getting-started, reference, migration, troubleshooting, operating, web-ui, cli)
- Nav placement in `mkdocs.yml`
- Whether existing pages need updates alongside new ones

Present the page list via AskUserQuestion for confirmation before proceeding, regardless of page count.

## Phase 2: Outline

For each page, produce a JTBD outline before writing. The outline prevents the codebase-mirror anti-pattern (see `references/prior-art-doc-ia.md`).

### Per-page outline process

Answer these five questions (from the Diataxis + JTBD framework):

1. **Page type:** concept / recipe / getting-started / reference / troubleshooting / migration / operating / web-ui / cli
2. **Reader's job:** one sentence. What is the reader trying to do when they land here?
3. **What the reader needs:** list only what is required to complete that job. Nothing else.
4. **Complexity ordering:** simplest case first, advanced in collapsible sections or linked pages.
5. **Anti-mirror check:** would a user organize this page this way, or only someone who has read the source?

### Outline format

```markdown
# <Page Title>

**Page type:** <type>
**Reader's job:** <one sentence>

## H2: <section heading>
<1-2 sentence description of content>

## H2: <section heading>
<1-2 sentence description>

## Snippet inventory
- `snippet_name.py` -- what it demonstrates (new / keep / rewrite)

## Cross-links
- Links to: <pages this links to>
- Linked from: <pages that link here>
```

For rewrites, note what changes from the existing page and why.

### Knowledge inventory (rewrites of operational pages only)

When rewriting troubleshooting, operating, or migration pages, extract every log signature, timing value, error message, and runbook command before overwriting. These exist nowhere else in the codebase. Write the inventory to a scratch file and cross-reference it against the new outline.

### Present outlines for approval

Show outlines to the user. For 1-2 pages, present inline. For 3+, summarize with one-line descriptions and offer to show any outline in detail.

If in **outline only** mode, stop here.

## Phase 3: Write and Review

### Write

For each page, use the writer prompt from `references/writing-prompt-template.md`.

1. Fill `{{variables}}` from the outline, snippet inventory, and page type.
2. For `{{technical_facts}}`: read the relevant source files listed in the writer prompt's "Key source files" section. Extract method signatures, parameter names, and behavioral notes. Pass these as the value.
3. Dispatch to a **Sonnet** writer subagent. Use `get-skill-tmpdir docs` for the output directory.
4. Read the output. Verify snippet files were created and `--8<--` includes match.
5. Copy pages and snippets to their final locations in `docs/pages/` (overwrite for rewrites; create for new pages).

For batches of 3+ pages in the same section, dispatch writer subagents in parallel.

**Nav and stub management:**
- **New pages:** add to `mkdocs.yml` nav. Create stub files first if other pages cross-link to them, so `mkdocs build --strict` stays green.
- **Rewrites:** overwrite in place.
- **New snippet files:** create alongside the page (`check_paths: true` requires simultaneous existence).

### Review

Send each written page to an **Opus** reviewer subagent using the reviewer prompt from `references/writing-prompt-template.md`. Fill `{{page_type_checklist}}` with the matching page-type checklist from the same file.

**Fix loop:**
1. Apply MUST FIX items. Re-review if any were found.
2. Apply SHOULD FIX items where they improve the page.
3. Note CONSIDER items but don't act unless clearly better.
4. Max 2 review iterations per page.

If in **review only** mode: run the Opus reviewer on the specified page(s), present findings to the user, and stop. Review-only mode does not run Phase 4 verification. Run `uv run mkdocs build --strict` manually if build issues are suspected.

## Phase 4: Verify

Run mechanical checks scaled to the scope of work.

### Always run

- `uv run mkdocs build --strict` (0 warnings)
- Pyright on new/modified snippet files

### For 3+ pages, also run

- Snippet orphan check: `uv run python tools/docs/check_snippet_orphans.py`
- Bare symbol check: `uv run python tools/docs/check_bare_symbols.py`

### For 5+ pages, also run

- Cross-reference coverage: `uv run python tools/docs/check_xref_coverage.py`
- Link checker: build site then run muffet

### Voice spot-check (5+ pages)

Sample 2-3 pages and check against the page-type checklists in `references/writing-prompt-template.md`. If >1 finding per sampled page, sweep the rest.

### Commit

After verification passes, commit all doc changes together. Use `docs:` commit type for user-facing documentation. Use `chore:` for internal-only changes.
