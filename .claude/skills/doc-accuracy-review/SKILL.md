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
mktemp -d <scratchpad>/doc-accuracy-review-XXXXXX
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

For each briefing file, dispatch an **Opus** subagent with this prompt:

```
Read the file at {briefing_path} and follow the instructions inside. You have full read access to the repository — verify claims against the source code in src/hassette/. Return the JSON result exactly as specified.
```

Unlike persona walkthroughs, these agents actively explore the repo and often run code to test claims, so they run longer per page. Cap at 5 concurrent subagents.

Strip any code fence or surrounding text from each result and parse it as JSON. It must have `page`, `claims_checked` (an integer), `findings` (a list) and `summary`. Each finding must have:

- `line`: an integer
- `claim_type`: one of `api-signature`, `default-value`, `behavior`, `exception`, `config`, `cli`, `import-path`, `version`, `file-path`
- `verdict`: one of `WRONG`, `OUTDATED_API`, `UNVERIFIABLE`
- `severity`: `high` or `low`
- `doc_quote`, `code_evidence`, `explanation`: non-empty strings
- `suggested_fix`: a string, which may be empty only for `UNVERIFIABLE`

If a result fails those checks, re-dispatch that page once. If the second result also fails, list the page as not reviewed in Phase 4, with the reason.

## Phase 4: Triage and Present

### Triage before trusting

Verification agents make mistakes in both directions, and for accuracy work a wrong "fix" is worse than the original error — it makes a true sentence false. Before presenting or fixing anything:

1. For each `WRONG` and `OUTDATED_API` finding, open the cited `code_evidence` location and confirm the contradiction is real and that the cited code is the code path the page describes.
2. Findings with no usable code citation are discarded.
3. `UNVERIFIABLE` findings get a quick independent grep — agents sometimes miss a symbol that one targeted search finds. If you find it and the claim holds, drop the finding; if you find it and the claim is false, upgrade to `WRONG`.
4. A claim that holds in the common case and overstates an edge case is `low`, whatever severity the agent gave it.

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

Pages with zero findings appear in the table only. That means no errors were found, not that the page is proven accurate. After the table, list any pages not reviewed, each with the reason, and give them no table row.

### Fixing

When the user asks for fixes (or pre-authorized auto-fixing), edit the markdown source in `docs/pages/`, not the rendered output. After fixes, run `uv run mkdocs build --strict` to verify the build. If a fix changes a snippet file, re-run Pyright on snippets per the docs CI.

## Design Decisions

**Why a separate skill from doc-persona-review?** Opposite stances toward the repo. The persona reviewer is deliberately blind — it must not know more than its reader does. The accuracy reviewer is the opposite: it greps and reads source freely. One briefing template can't serve both without contradicting itself.

**Why no second adversarial verification pass?** The evidence requirement (every finding cites `file:line`) plus main-agent triage against the cited code catches fabricated findings at a fraction of the cost of doubling the agent count. If triage starts rejecting a large share of findings, revisit this.

**Why `claims_checked`?** Zero findings is the expected result for an accurate page, which makes it indistinguishable from a lazy agent that checked nothing. The count only catches an agent that barely looked: in the seeded baseline (`design/research/2026-11-02-doc-accuracy-verification/seeded-baseline/`), a higher count didn't mean more errors caught.

**Why Opus?** On the same briefing in that baseline, Opus caught far more errors than Sonnet, especially claims that need tracing through the code. The likely reason is that it ran code to test claims, which Sonnet rarely did, though that hasn't been tested on its own. It costs more and reports more low-severity overstatements, which triage has to sort. The baseline's README has the numbers and caveats.
