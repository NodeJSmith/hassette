---
name: doc-overhaul
description: "Full documentation rewrite using outline-first process. Three phases: site outline, per-page content outlines, section-by-section writing with subagent writer/reviewer pairs."
user-invocable: true
---

# Documentation Overhaul

Blank-slate documentation rewrite using the process proven in PR #970 (76 pages, 267 snippets). The process optimizes for structural consistency and voice coherence by planning everything before writing anything.

## When to Use

A full overhaul, not incremental fixes. Use when:
- Voice/structure drift has accumulated across many pages
- The nav structure no longer matches how readers find things
- Patching individual pages won't fix the structural problems

## Arguments

$ARGUMENTS — optional scope description (e.g., "rewrite the testing section" for a partial overhaul). If empty, assumes full site rewrite.

## Prerequisites

The project must have:
- `.claude/rules/voice-guide.md` — voice rules with before/after examples
- `.claude/rules/doc-rules.md` — page structure templates, snippet conventions
- `mkdocs.yml` with a `nav:` section
- A docs site built with mkdocs (`uv run mkdocs build --strict`)
- Snippet files under `docs/pages/*/snippets/` with `--8<--` includes

## The Three Phases

### Phase 1: Site Outline (load-bearing — get this right)

**Goal:** Restructure the nav, create stub files, produce calibration artifacts.

**Deliverables:**
1. Restructured `mkdocs.yml` nav with stub files for every page (title + placeholder). Stubs keep `mkdocs build --strict` green from the start.
2. Three exemplar page selections:
   - **Concept exemplar** — hardest voice (system-as-subject, no "you"). Must introduce multiple related terms and send readers to sibling depth pages.
   - **Recipe/getting-started exemplar** — friendlier register. Must demonstrate the prose "How It Works" pattern.
   - **Reference exemplar** — terse tables, functional definitions, no narrative arc.
3. Voice audit checklist (5-10 binary pass/fail items from the most commonly violated voice-guide rules).
4. `docs-context.md` calibration artifact — paths to exemplars, full voice checklist inline, top violation patterns. Read at the start of every writing session.
5. Structural decisions documented (sections merged/split/renamed, canonical homes designated, audience scoping).

**Process:**
- Launch researcher subagent to audit current docs: page inventory, voice compliance sampling, structural issues, snippet counts.
- Present the proposed nav restructuring to the user via AskUserQuestion before creating stubs.
- Run `mkdocs build --strict` after creating all stubs to verify cross-links resolve.
- Write all deliverables to `design/specs/<NNN>-doc-overhaul/`.

### Phase 2: Per-Page Content Outlines

**Goal:** Blueprint every page before writing any of them.

**Deliverables per page** (written to `design/specs/<NNN>-doc-overhaul/outlines/<section>/<page-slug>.md`):
1. Section headings (H2/H3) with 1-2 sentence descriptions of content.
2. Snippet inventory: named list of code examples needed. For each: keep (with path), rewrite (with path + what changes), or new (with proposed path).
3. Cross-links: which pages this links to, which pages link here.

**Additional deliverables:**
- `snippet-mapping.md` — claimed vs unclaimed vs new snippet summary.
- `knowledge-inventory.md` — for troubleshooting/operational pages, extract every log signature, timing value, error message, and runbook command from current pages before they're overwritten. This is the safety net for operational knowledge that exists nowhere else.

**Process:**
- Use Explore subagents in parallel (one per section) to read current pages and extract content inventories.
- Cross-reference snippet files against outlines to identify orphans.
- Present outline summaries to user for review before Phase 3.

### Phase 3: Section-by-Section Writing

**Goal:** Write pages from blank using Phase 2 outlines as blueprints.

**Per section (~8 section batches for a full site):**

1. **Write** — For each page in the section, use the writing-prompt-template (see below) to brief a Sonnet subagent. The subagent writes the page and its snippet files to a temp directory.

2. **Review** — Send each written page to an Opus reviewer subagent with the reviewer prompt (see below). The reviewer checks voice compliance, symbol accuracy, and anti-patterns.

3. **Apply fixes** — Apply reviewer findings in the main loop. Re-review if MUST FIX items were found.

4. **Voice audit** — Run every item on the docs-context.md checklist against the written pages before marking the section complete.

5. **Verify** — `mkdocs build --strict`, Pyright on snippets, snippet orphan check.

### Final Sweep (T13)

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

4. **Followups file review:** Check `followups.md` for items that were deferred during writing — address or file as issues.

## Writing-Prompt Template

The template for briefing writer subagents. Fill `{{variables}}` from the page's outline.

### Writer Prompt

```
You are writing a documentation page for Hassette, an async Python framework
for Home Assistant automations. Write the "{{page_title}}" page.

## Output location

Write the page to {{output_dir}}/{{filename}} and all snippet files to
{{output_dir}}/snippets/.

## Page outline

Follow this outline exactly:

{{outline}}

## Snippet files to create

All code examples must be in snippet files, included via
`--8<-- "pages/{{section}}/snippets/filename.py"`. Create these files in
{{output_dir}}/snippets/:

{{snippet_inventory}}

## Voice rules (CRITICAL)

This is a **{{page_type}}** page.

{{voice_rules_block}}

### Anti-patterns to avoid

- No "serves as", "acts as", "functions as" when you mean "is"
- No "pivotal", "crucial", "fundamental", "robust"
- No dangling "-ing" phrases
- No synonym cycling (pick one term per concept and stick with it)
- No filler hedging ("It is important to note that", "In order to")
- No "leverage", "utilize", "facilitate" — use "use", "help", "show"
- No em dashes — use periods or commas
- No transition sentences opening paragraphs
- No motivational preamble before code
- No `---` horizontal rules between sections

### Cross-links to use

{{cross_links}}

## Symbol verification (CRITICAL)

Before referencing any method, parameter, class, or type in the documentation,
verify it exists in the codebase. Use Serena MCP tools or grep. A page that
references a non-existent symbol is worse than one that omits it.

Top-level imports are: `from hassette import App, AppConfig, D, states, P, C, A`
Do NOT use deep import paths.

## Key technical facts

{{technical_facts}}

Write the complete page now. Include the `--8<--` snippet includes in the
markdown. Write every snippet file to {{output_dir}}/snippets/.
```

### Reviewer Prompt

```
You are reviewing a documentation page for Hassette. The page is a
{{page_type}} page ("{{page_title}}"). Find voice violations, technical
inaccuracies, and suggest concrete improvements.

Read the page at {{page_path}}.

## Voice Audit Checklist (apply every item)

### General (all page types)
1. No transition sentences opening paragraphs.
2. Terms defined functionally on first use. Say what it DOES, not what it IS.
3. Explanatory sentences are 10-18 words. Inline code doesn't count.
4. Main behavior stated first, caveats after.
5. Every limitation paired with a path forward.
6. Module aliases linked on first use.

{{page_type_checklist}}

### Symbol accuracy
For every method, parameter, or class the page references, verify it exists.
Flag any symbol that doesn't exist. Check parameter names and types.

### Anti-patterns to flag
- "serves as", "acts as", "functions as"
- "pivotal", "crucial", "fundamental", "robust"
- Dangling "-ing" phrases, synonym cycling, filler hedging
- Em dashes, transition sentences, motivational preamble
- Sentences over 18 words (code identifiers don't count)
- Category definitions instead of functional definitions

## Output format

For each finding:
- **Location**: line number(s)
- **Issue**: what's wrong
- **Suggested fix**: concrete replacement text

Group by: MUST FIX, SHOULD FIX, CONSIDER.
End with a one-paragraph overall assessment.
```

## Voice Rules Blocks (for {{voice_rules_block}})

### Getting-started pages

1. Use "you" and "your" throughout.
2. CODE FIRST, THEN EXPLAIN. Code block immediately after the H2 heading. No introductory sentences before code.
3. Short sentences. 10-18 words.
4. Present tense. Anglo-Saxon verbs.
5. Introduce terms with functional definitions on first use ("does X" not "is a Y").
6. Link module aliases inline at first use.
7. Show concrete CLI output.

### Concept pages

1. System-as-subject throughout. No "you" or "your".
2. No imperative mood. Use declarative: "X provides", "Y accepts".
3. Code first for the opening example.
4. Short sentences. 10-18 words.
5. Present tense. Anglo-Saxon verbs.
6. Concept introductions follow name -> define -> show -> constrain.
7. Link module aliases inline at first use.

### Recipe pages

1. Problem statement uses "you" and "your".
2. "How It Works" uses system-as-subject. No "you" in this section.
3. "How It Works" uses flowing prose paragraphs, NOT bullet lists with bolded lead-ins.
4. "Verify it's working" names a concrete command or UI action.
5. Short sentences. 10-18 words.

### Reference pages

1. Tables before prose in reference sections.
2. Terse functional definitions in table cells.
3. No admonitions in reference tables.

## What Made This Process Work

Lessons from the PR #970 execution:

1. **Phase 1 is load-bearing.** The site outline determines everything downstream. Spending disproportionate time here pays off across all writing sessions.

2. **Exemplars anchor voice.** Three reviewed pages set the voice before bulk writing begins. Without them, drift accumulates across sessions.

3. **`docs-context.md` prevents session amnesia.** A single calibration file read at session start keeps voice consistent across compactions and session boundaries.

4. **Per-page outlines prevent scope drift.** Writers with an outline produce pages that fit the site structure. Writers without outlines produce standalone pages that don't compose.

5. **Stubs from day one.** Creating stub files for every page before writing any of them means `mkdocs build --strict` stays green throughout. No broken cross-link periods.

6. **Knowledge inventory for operational pages.** Log signatures, timing values, and error messages exist only in docs. Blank-slate rewrites lose them without an explicit extraction step.

7. **Writer + reviewer subagent pairs.** The writer subagent follows the outline and voice rules. A separate reviewer subagent catches violations the writer missed. Separation of concerns matters.

8. **Mechanical checks script the quality gate.** mkdocs strict, Pyright, snippet orphans, link checker, xref coverage, bare symbols. Each is a CI-ready script, not a subjective scan.

9. **Symbol verification is non-negotiable.** Pages that reference non-existent methods or parameters are worse than pages that omit them. Verify every symbol against the actual source.
