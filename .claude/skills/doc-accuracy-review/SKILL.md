# Doc Accuracy Review

Verify documentation pages against the actual source code. Each verification subagent reads one page, inventories its checkable claims (signatures, defaults, behaviors, exceptions, config keys, CLI flags), and confirms or refutes each one against `src/hassette/`.

Sibling of `doc-persona-review`: that skill tests whether a page is *followable*; this one tests whether it is *true*. Snippets are Pyright-checked in CI, but nothing guards prose claims — they drift silently after every `src/` change.

## Arguments

The page or section to verify. Examples:
- `core-concepts/bus` (verifies all pages in the section)
- `core-concepts/scheduler/methods`
- `cli` (verifies all CLI pages)

If empty, ask what to verify.

## Phase 1: Resolve Pages

If the argument is a section, expand to all pages in that directory (excluding `snippets/`). If it's a single page, use that page.

No persona selection — every page gets the same verification treatment.

## Phase 2: Extract and Assemble

Two scripts handle all file preparation. Run them, don't read their output. Do NOT read the page content or briefing files yourself — the heavy content belongs only in subagent contexts.

### Step 1: Get a tmp directory

```bash
get-skill-tmpdir doc-accuracy-review
```

Use the printed path as `$TMPDIR` below.

### Step 2: Build docs and extract pages

```bash
uv run mkdocs build --strict
uv run tools/docs/extract_doc_page.py --section <section> --output-dir $TMPDIR/pages
# or for a single page:
uv run tools/docs/extract_doc_page.py <page> --output-dir $TMPDIR/pages
```

### Step 3: Assemble briefing files

One command per page (no persona argument — the template is fixed):

```bash
uv run tools/docs/assemble_accuracy_briefing.py $TMPDIR/pages/<page-slug>.txt $TMPDIR/briefings
```

Chain with `&&` for multi-page sections. Each briefing lands at `$TMPDIR/briefings/accuracy--<page-slug>.md`.

## Phase 3: Dispatch Verification Agents

For each briefing file, dispatch a **Sonnet** subagent with this prompt:

```
Read the file at {briefing_path} and follow the instructions inside. You have full read access to the repository — verify claims against the source code in src/hassette/. Return the JSON result exactly as specified.
```

Unlike persona walkthroughs, these agents actively explore the repo (Read, Grep, Glob), so they run longer per page. Cap at 5 concurrent subagents.

Use `schema` on the agent call to enforce the JSON structure:

```json
{
  "type": "object",
  "properties": {
    "page": {"type": "string"},
    "claims_checked": {"type": "integer"},
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "line": {"type": "integer"},
          "claim_type": {"type": "string", "enum": ["api-signature", "default-value", "behavior", "exception", "config", "cli", "import-path", "version", "file-path"]},
          "verdict": {"type": "string", "enum": ["WRONG", "OUTDATED_API", "UNVERIFIABLE"]},
          "severity": {"type": "string", "enum": ["high", "low"]},
          "doc_quote": {"type": "string"},
          "code_evidence": {"type": "string"},
          "explanation": {"type": "string"},
          "suggested_fix": {"type": "string"}
        },
        "required": ["line", "claim_type", "verdict", "severity", "doc_quote", "code_evidence", "explanation", "suggested_fix"]
      }
    },
    "summary": {"type": "string"}
  },
  "required": ["page", "claims_checked", "findings", "summary"]
}
```

## Phase 4: Triage and Present

### Triage before trusting

Verification agents make mistakes in both directions, and for accuracy work a wrong "fix" is worse than the original error — it makes a true sentence false. Before presenting or fixing anything:

1. For each `WRONG` and `OUTDATED_API` finding, open the cited `code_evidence` location and confirm the contradiction is real and that the cited code is the code path the page describes.
2. Findings with no usable code citation are discarded.
3. `UNVERIFIABLE` findings get a quick independent grep — agents sometimes miss a symbol that one targeted search finds. If you find it and the claim holds, drop the finding; if you find it and the claim is false, upgrade to `WRONG`.

### Sanity-check coverage

A page with `claims_checked: 3` that plainly contains dozens of API references got a lazy pass — re-dispatch it. Use judgment, not a fixed threshold: reference-heavy pages (methods, triggers, predicate tables) should report high counts; conceptual index pages legitimately report low ones.

### Output format

Group confirmed findings by page, worst first (`high` severity, then `WRONG` before `OUTDATED_API` before `UNVERIFIABLE`):

```
## page-name.md — N findings (M claims checked)

- **[verdict / claim_type / severity]** L{line}: "{doc_quote}"
  Code: {code_evidence}
  {explanation}
  Fix: {suggested_fix}
```

End with a summary table:

| Page | Claims checked | WRONG | OUTDATED_API | UNVERIFIABLE |
|------|----------------|-------|--------------|--------------|

Pages with zero findings appear in the table only — that's the success case, not a gap.

### Fixing

When the user asks for fixes (or pre-authorized auto-fixing), edit the markdown source in `docs/pages/`, not the rendered output. After fixes, run `uv run mkdocs build --strict` to verify the build. If a fix changes a snippet file, re-run Pyright on snippets per the docs CI.

## Design Decisions

**Why a separate skill from doc-persona-review?** Opposite stances toward the repo. The persona reviewer is deliberately blind — it must not know more than the persona does. The accuracy reviewer is the opposite: it greps and reads source freely. One briefing template can't serve both without contradicting itself.

**Why no second adversarial verification pass?** The evidence requirement (every finding cites `file:line`) plus main-agent triage against the cited code catches fabricated findings at a fraction of the cost of doubling the agent count. If triage starts rejecting a large share of findings, revisit this.

**Why `claims_checked`?** Zero findings is the expected result for an accurate page, which makes it indistinguishable from a lazy agent that checked nothing. The count is the cheap signal that separates the two.

**Why Sonnet?** Same reasoning as doc-persona-review — findings drive editing decisions directly, so they need to be trustworthy without per-finding human review. Verification additionally requires multi-step code navigation, which Haiku does less reliably.
