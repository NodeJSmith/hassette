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

Read `references/personas.md` to load all three persona definitions. Then select which personas to run based on page type:

| Page type | Personas |
|-----------|----------|
| `getting-started/*` | Alex (fresh Python dev) |
| `migration/*` | Sam (AppDaemon migrator) |
| `core-concepts/*` | Jordan (experienced dev) |
| `recipes/*` | Alex + Sam + Jordan (all three) |
| `testing/*` | Jordan (experienced dev) |
| `cli/*`, `operating/*`, `web-ui/*` | Alex + Jordan |

For multi-page runs, each page gets its own persona set based on its path.

### Read voice context

Read these files before dispatching subagents (pass relevant excerpts to each subagent):
- `.claude/rules/voice-guide.md` (rules 10, 15, 17 matter for persona-appropriate voice)
- `.claude/rules/doc-rules.md` (page type templates define what structure the reader expects)

## Phase 2: Dispatch Persona Walkthroughs

For each (page, persona) pair, dispatch a **Sonnet** subagent with this prompt structure:

```
You are {persona_name}, reading Hassette documentation for the first time.

{full persona definition from personas.md, including Knows / Does NOT know / Reading goal / Failure signals}

IMPORTANT: You must genuinely adopt this persona's knowledge boundaries. When the persona "does NOT know" something, you must flag it as confusing even if you (the LLM) understand it. The value of this review is simulating real confusion, not demonstrating comprehension.

---

Read the following documentation page and walk through it as {persona_name} would, step by step. For each section or paragraph:

1. **Can I follow this?** Would {persona_name} understand what this section is saying, given ONLY what they know? Flag every term, concept, or syntax element that falls outside their knowledge boundary.

2. **Do I know what to do next?** At each step or code example, would {persona_name} know what action to take? Flag missing commands, unclear "where do I put this?" moments, and steps that assume setup not covered on this page.

3. **Can I connect this to my goal?** Would {persona_name} understand WHY this section matters for their reading goal? Flag sections that feel like detours or unmotivated technical detail.

4. **Can I tell it worked?** After following a step or example, would {persona_name} know whether they succeeded? Flag missing verification steps, expected output, or "you should now see..." moments.

Return your findings as a JSON object:

{{
  "persona": "{persona_name}",
  "page": "{page_path}",
  "overall_verdict": "followable" | "followable-with-effort" | "stuck-at-step-N" | "lost",
  "findings": [
    {{
      "line": <approximate line number>,
      "section": "<heading text>",
      "type": "undefined-term" | "missing-prerequisite" | "unclear-next-step" | "no-verification" | "assumed-knowledge" | "unmotivated-content" | "missing-import" | "jargon",
      "quote": "<the specific text that caused confusion>",
      "confusion": "<what {persona_name} would think or feel at this point>",
      "suggestion": "<what would help — define the term, add a sentence, show expected output, etc.>"
    }}
  ],
  "stopped_at": "<section heading where the persona would give up, or null if they'd finish>",
  "summary": "<2-3 sentences: would this persona succeed with this page?>"
}}

Here is the page content:

---
{page content with line numbers}
---
```

Use `schema` on the agent call to enforce the JSON structure.

### Parallelism

- Single page with 1 persona: one subagent.
- Single page with 3 personas: three subagents in parallel.
- Multi-page section: batch by page, all personas for each page in parallel. Cap at 5 concurrent subagents.

## Phase 3: Collate and Present

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

**Why not a Python script?** The cognitive walkthrough requires genuine language comprehension (is this term defined? would this step confuse someone?). Pattern matching can't do that. The voice audit script handles mechanical rules; this handles semantic ones.

**Why structured JSON output?** Freeform prose findings are hard to compare across personas, hard to track across runs, and hard to act on. Structured findings with line numbers, types, and quotes are directly actionable.
