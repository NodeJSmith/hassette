# Doc Persona Review

Evaluate documentation pages from the perspective of beginner personas. Each persona does a cognitive walkthrough, flagging where a real reader with that background would get confused, lost, or stuck.

Based on cognitive walkthrough methodology (Wharton/Lewis) and the UW 2025 synthetic heuristic evaluation study showing LLM evaluators catch 73-77% of usability issues vs 57-63% for human experts.

## Arguments

The page or section to review. Examples:
- `getting-started/first-automation`
- `recipes/motion-lights`
- `core-concepts/bus` (reviews all pages in the section)
- `migration` (reviews all migration pages)

If empty, ask what to review.

## Phase 1: Select Pages and Personas

### Resolve pages

If the argument is a section, expand to all `.md` files in that directory (excluding `snippets/`). If it's a single page, use that page.

### Pick personas

Select which personas to run based on page type:

| Page type | Personas |
|-----------|----------|
| `getting-started/*` | Alex (fresh Python dev) |
| `migration/*` | Sam (AppDaemon migrator) |
| `core-concepts/*` | Jordan (experienced dev) |
| `recipes/*` | Alex + Sam + Jordan (all three) |
| `testing/*` | Jordan (experienced dev) |
| `cli/*`, `operating/*`, `web-ui/*` | Alex + Jordan |

Do NOT read `references/personas.md`, `voice-guide.md`, or `doc-rules.md` yourself. The assembler script handles all of that.

## Phase 2: Extract and Assemble

Two scripts handle all file preparation. Run them, don't read their output.

### Step 1: Get a tmp directory

```bash
get-skill-tmpdir doc-persona-review
```

This prints a path like `/tmp/claude-doc-persona-review-a8Kx3Q`. Use it as `$TMPDIR` below.

### Step 2: Build docs and extract pages

```bash
uv run mkdocs build --strict
uv run tools/docs/extract_doc_page.py --section <section> --output-dir $TMPDIR/pages
# or for a single page:
uv run tools/docs/extract_doc_page.py <page> --output-dir $TMPDIR/pages
```

This writes one `.txt` file per page to `$TMPDIR/pages/`. The output lists the files created. Note the filenames — you'll need them for the next step.

### Step 3: Assemble briefing files

For each (page, persona) pair, run the assembler:

```bash
uv run tools/docs/assemble_persona_briefing.py <Persona> $TMPDIR/pages/<page-slug>.txt $TMPDIR/briefings
```

This writes a complete briefing file to `$TMPDIR/briefings/<persona>--<page-slug>.md` containing the task instructions, persona definition, voice guide, doc rules, and page content. The assembler pulls all reference files from their known repo paths.

Run one command per (page, persona) pair. For efficiency, chain them:

```bash
uv run tools/docs/assemble_persona_briefing.py Jordan $TMPDIR/pages/core-concepts--bus--index.txt $TMPDIR/briefings && \
uv run tools/docs/assemble_persona_briefing.py Jordan $TMPDIR/pages/core-concepts--bus--handlers.txt $TMPDIR/briefings && \
uv run tools/docs/assemble_persona_briefing.py Jordan $TMPDIR/pages/core-concepts--bus--filtering.txt $TMPDIR/briefings
```

## Phase 3: Dispatch Persona Walkthroughs

For each briefing file, dispatch a **Sonnet** subagent with this prompt:

```
Read the file at {briefing_path} and follow the instructions inside. Return the JSON result exactly as specified.
```

Use `schema` on the agent call to enforce the JSON structure:

```json
{
  "type": "object",
  "properties": {
    "persona": {"type": "string"},
    "page": {"type": "string"},
    "overall_verdict": {"type": "string", "pattern": "^(followable|followable-with-effort|stuck-at-step-\\d+|lost)$"},
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "line": {"type": "integer"},
          "section": {"type": "string"},
          "type": {"type": "string", "enum": ["undefined-term", "missing-prerequisite", "unclear-next-step", "no-verification", "assumed-knowledge", "unmotivated-content", "missing-import", "jargon"]},
          "quote": {"type": "string"},
          "confusion": {"type": "string"},
          "suggestion": {"type": "string"}
        },
        "required": ["line", "section", "type", "quote", "confusion", "suggestion"]
      }
    },
    "stopped_at": {"type": ["string", "null"]},
    "summary": {"type": "string"}
  },
  "required": ["persona", "page", "overall_verdict", "findings", "stopped_at", "summary"]
}
```

### Parallelism

- Single page with 1 persona: one subagent.
- Single page with 3 personas: three subagents in parallel.
- Multi-page section: batch by page, all personas for each page in parallel. Cap at 5 concurrent subagents.

## Phase 4: Collate and Present

### Per-page summary

For each page, merge findings across personas. Group by section heading. When multiple personas flag the same line/section, note the overlap (higher confidence).

### Severity classification

| Verdict | Meaning |
|---------|---------|
| **lost** | Persona would abandon the page. At least one blocking undefined term or missing prerequisite with no path forward. |
| **stuck-at-step-N** | Persona would stall at a specific step. Could recover with external help (Google, asking someone). |
| **followable-with-effort** | Persona could finish but would need to re-read sections, guess at meanings, or make assumptions. |
| **followable** | Persona could follow the page start to finish without confusion. |

### Output format

Present findings to the user grouped by page, then by section within each page. Lead with the worst verdicts. For each finding, show:

```
## page-name.md — verdict (persona)

### Section: <heading>

- **[type]** L{line}: "{quote}"
  {persona_name}: {confusion}
  Suggestion: {suggestion}
```

### Summary table

End with a summary table:

| Page | Alex | Sam | Jordan |
|------|------|-----|--------|
| first-automation.md | followable-with-effort | — | — |
| motion-lights.md | stuck-at-step-3 | followable | followable |

(`—` means that persona was not run on that page.)

## Design Decisions

**Why Sonnet for personas?** Haiku finds roughly the same issues but with weaker reasoning and less precise suggestions. Sonnet produces findings that can be trusted without human verification of each one. The 2x cost difference is worth it since the output directly drives editing decisions. Tested on `first-automation.md`: both models returned the same verdict (followable-with-effort) and overlapping findings, but Sonnet caught unexpanded jargon ("DI parameters"), missing starting-state context, and produced actionable suggestions ("Stop Hassette with Ctrl+C, then run `hassette run` again") where Haiku gave vague pointers.

**Why briefing files?** The main agent only needs page names, persona assignments, and returned findings. All heavy content (page HTML, persona definitions, voice rules, doc rules) is assembled into files by `tools/docs/assemble_persona_briefing.py` and read only by the subagents. This keeps the main context small enough to handle large section audits without compaction.

**Why not a Python script?** The cognitive walkthrough requires genuine language comprehension (is this term defined? would this step confuse someone?). Pattern matching can't do that. The voice audit script handles mechanical rules; this handles semantic ones.

**Why structured JSON output?** Freeform prose findings are hard to compare across personas, hard to track across runs, and hard to act on. Structured findings with line numbers, types, and quotes are directly actionable.
