---
name: hassette.doc-overhaul
description: "Use when the user says: \"doc overhaul\", \"rewrite the docs\", \"full documentation overhaul\". Blank-slate documentation rewrite using a three-phase outline-first process with subagent writer/reviewer pairs."
user-invocable: true
references:
  - references/writing-prompt-template.md
  - references/retrospective.md
---

# Documentation Overhaul

Blank-slate documentation rewrite using the process proven in PR #970 (76 pages, 267 snippets). The process optimizes for structural consistency and voice coherence by planning everything before writing anything.

## When to Use

A full overhaul, not incremental fixes. Use when:
- Voice/structure drift has accumulated across many pages
- The nav structure no longer matches how readers find things
- Patching individual pages won't fix the structural problems

## Arguments

$ARGUMENTS -- optional scope description (e.g., "rewrite the testing section" for a partial overhaul). If empty, assumes full site rewrite.

## Prerequisites

The project must have:
- `.claude/rules/voice-guide.md` -- voice rules with before/after examples
- `.claude/rules/doc-rules.md` -- page structure templates, snippet conventions
- `mkdocs.yml` with a `nav:` section
- A docs site built with mkdocs (`uv run mkdocs build --strict`)
- Snippet files under `docs/pages/*/snippets/` with `--8<--` includes

## The Three Phases

### Phase 1: Site Outline (load-bearing, get this right)

**Goal:** Restructure the nav, create stub files, produce calibration artifacts.

**Deliverables:**
1. Restructured `mkdocs.yml` nav with stub files for every page (title + placeholder). Stubs keep `mkdocs build --strict` green from the start.
2. Three exemplar page selections:
   - **Concept exemplar** -- hardest voice (system-as-subject, no "you"). Must introduce multiple related terms and send readers to sibling depth pages.
   - **Recipe/getting-started exemplar** -- friendlier register. Must demonstrate the prose "How It Works" pattern.
   - **Reference exemplar** -- terse tables, functional definitions, no narrative arc.
3. Voice audit checklist (5-10 binary pass/fail items from the most commonly violated voice-guide rules).
4. `docs-context.md` calibration artifact -- paths to exemplars, full voice checklist inline, top violation patterns. Written to `design/specs/NNN-doc-overhaul/docs-context.md` and read at the start of every writing session. See `references/docs-context-example.md` for the format used in PR #970.
5. Structural decisions documented (sections merged/split/renamed, canonical homes designated, audience scoping).

**Process:**
- Launch researcher subagent to audit current docs: page inventory, voice compliance sampling, structural issues, snippet counts.
- Present the proposed nav restructuring to the user via AskUserQuestion before creating stubs.
- Run `mkdocs build --strict` after creating all stubs to verify cross-links resolve.
- Write all deliverables to `design/specs/NNN-doc-overhaul/` (replace NNN with the next spec number per project convention).

### Phase 2: Per-Page Content Outlines

**Goal:** Blueprint every page before writing any of them.

**Deliverables per page** (written to `design/specs/NNN-doc-overhaul/outlines/<section>/<page-slug>.md`):
1. Section headings (H2/H3) with 1-2 sentence descriptions of content.
2. Snippet inventory: named list of code examples needed. For each: keep (with path), rewrite (with path + what changes), or new (with proposed path).
3. Cross-links: which pages this links to, which pages link here.

**Additional deliverables:**
- `snippet-mapping.md` -- claimed vs unclaimed vs new snippet summary.
- `knowledge-inventory.md` -- for troubleshooting/operational pages, extract every log signature, timing value, error message, and runbook command from current pages before they are overwritten. This is the safety net for operational knowledge that exists nowhere else.

**Process:**
- Use Explore subagents in parallel (one per section) to read current pages and extract content inventories.
- Cross-reference snippet files against outlines to identify orphans.
- Present outline summaries to user for review before Phase 3.

### Phase 3: Section-by-Section Writing

**Goal:** Write pages from blank using Phase 2 outlines as blueprints.

**Per section (one batch per nav section):**

1. **Write** -- For each page, fill the writer prompt template from `references/writing-prompt-template.md` with the page's outline, snippet inventory, voice rules block, and cross-links. Dispatch to a Sonnet writer subagent. Use `get-skill-tmpdir doc-overhaul` for the output directory.

2. **Review** -- Send each written page to an Opus reviewer subagent using the reviewer prompt from `references/writing-prompt-template.md`. Fill `{{page_type_checklist}}` with the matching page-type checklist from the same file. The reviewer checks voice compliance, symbol accuracy, and anti-patterns.

3. **Apply fixes** -- Apply reviewer findings in the main loop. Re-review if MUST FIX items were found.

4. **Voice audit** -- Run every item on the Phase 1 `docs-context.md` checklist against the written pages before marking the section complete.

5. **Verify** -- `mkdocs build --strict`, Pyright on snippets, snippet orphan check.

### Final Sweep

After all sections are written:

1. **Mechanical checks:**
   - `mkdocs build --strict` (0 warnings)
   - Pyright on all snippet files (0 errors)
   - Snippet orphan check (`tools/check_snippet_orphans.py`)
   - Link checker (muffet on built site)
   - Cross-reference coverage (`tools/check_xref_coverage.py`)
   - Bare symbol detection (`tools/check_bare_symbols.py --fix`)

2. **Voice spot-check:** Sample 8 pages (one per section type), check against voice audit checklist. If >1 finding per 8 pages, do a broader sweep.

3. **Screenshot audit:** Verify all referenced images exist; wire unused screenshots into pages where they'd help; delete true orphans.

4. **Followups file review:** Check `followups.md` for items that were deferred during writing. Address or file as issues.
