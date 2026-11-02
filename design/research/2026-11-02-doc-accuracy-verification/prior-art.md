---
topic: "Verifying documentation prose against source code: recall and run-to-run consistency"
date: 2026-11-02
status: Draft
---

# Prior Art: Verifying Documentation Prose Against Source Code

## The Problem

`doc-accuracy-review` runs one Sonnet agent per page, checks each claim against `src/hassette/`, reports only failures, and has the main agent triage them. Its findings seem to hold up, but it misses real errors, and which ones varies by run. `predicate-reference.md` wrongly says bare glob strings work as conditions. On that page, one run in four caught it (the October pass plus three identical runs on 2026-11-02). The clean runs reported 70, 95 and 92 claims checked, so the count didn't reveal the miss.

The question is what others have found raises recall and consistency, and whether they try at all.

## How We Do It Today

CI runs `mkdocs build --strict` (links and cross-references), Pyright on snippets, and `check_snippet_orphans.py`. Nothing executes snippets, and nothing compares prose to code except this skill. `check_bare_symbols.py`, `check_xref_coverage.py` and `check_doc_voice.py` cover conventions only, and aren't referenced from `prek.toml` or `docs.yml`.

The `doc-persona-review` seeded-recall experiment (`design/research/2026-10-21-persona-review-seeded-recall/`) gives a method to reuse: clean and seeded copies, a blind judge, opaque names. All its seeds were comprehension defects, so accuracy recall has never been measured.

The `doc-rules.md` gate fires when a page is edited. A `src/` change that makes an untouched page false doesn't trigger it.

## Patterns Found

### Pattern 1: Repeat passes and take the union

**Used by**: OpenSSF AI vulnerability guidance; Song's cross-model study; Snyk's repeatability benchmark (measurement, not a mitigation).

**How it works**: Run the review several times and keep anything any run raised, deduplicated on a normalized key. Optionally vary the model or framing between passes.

**Strengths**: This is the only recall lever with direct numbers. In Song's preprint (150 planted errors, 900 sessions), two same-model fresh reviews matched 42.7% of planted errors, and one same-model plus one cross-model review matched 56.7%. Reviewers' found-error sets overlapped only partly (Jaccard 41.2%). Snyk found that findings matching its reference mostly repeat (134 of 158 appeared in all 5 runs), so what varies is the marginal findings. That fits our miss, though Snyk measured security review.

**Weaknesses**: Union collects every run's false positives. Half of Snyk's unmatched findings appeared in only 1 of 5 runs. Song's gain isn't cleanly about model diversity: one cross-model pass plus one same-model pass wasn't significantly better than two top-tier cross-model reviews, and a lightweight cross-model reviewer did no better than same-model review, so model difference and capability aren't separated. No source gives a curve past two passes. OpenSSF says only that later runs find less, with a long tail.

**Example**: https://arxiv.org/html/2610.01471v1 ; https://snyk.io/blog/snyk-vulnbench-js-1-0-llm-security-review-repeatability/ ; https://best.openssf.org/Finding-and-Fixing-Vulnerabilities-Using-AI/run-ai-multiple-times.html

**Read**: Song: abstract and key findings, figures re-checked against the page text; results sections not read. Snyk: first part of the post. OpenSSF: full page.

### Pattern 2: Expand from each found error

**Used by**: 2389 `documentation-audit` plugin.

**How it works**: After the first pass, turn each false claim into a pattern and search for it everywhere: `every \d+ (seconds?|minutes?)`, script references, service names.

**Strengths**: Cheap and targeted. It suits repeated false claims, which our docs do have: the October pass found the same wrong `name=` claim on about nine pages, and that spread was handled by hand.

**Weaknesses**: It only helps once one instance has been found, so it can't rescue a run that finds nothing. The plugin's "10-20% more issues" is an unmeasured vendor claim.

**Example**: https://github.com/2389-research/documentation-audit/blob/main/skills/SKILL.md

**Read**: `skills/SKILL.md` in full.

### Pattern 3: Claim ledger

**Used by**: FActScore, SAFE and VeriScore pipelines (research); Docverity (tool, README only).

**How it works**: One stage lists every checkable claim. Another verifies each and records a verdict for all of them, including passes.

**Strengths**: A list can be diffed across runs, which a count can't. It would show whether a miss came from never extracting the claim or from wrongly passing it.

**Weaknesses**: Extraction is its own measured source of noise. A claim the extractor skips is silently never checked (Decomposition Dilemmas; Wanner et al.). A ledger written in the same context as the verdicts may only record what the agent meant to do. No study measures ledger versus no ledger on documentation. The closest product isn't an example either: the 2389 report shows `Claims verified | ~180` and lists only false claims, which is the same self-reported count we already found useless.

**Example**: https://arxiv.org/html/2411.02400v2 ; https://arxiv.org/html/2403.11903 ; https://arxiv.org/html/2406.19276

**Read**: Decomposition Dilemmas: abstract, conclusion, limitations. VeriScore and Wanner: abstracts. No implementation read.

### Pattern 4: Smaller scope per verifier

**Used by**: Chain-of-Verification (answers each check independently); per-claim verification in the fact-checking pipelines.

**How it works**: Each check gets a short prompt containing only the claim and its evidence, so earlier judgments can't color it.

**Strengths**: "Curse of Instructions" shows all-instructions success falling roughly as (per-item success)^N, and our pages carry about 100 claims per agent.

**Weaknesses**: That result covers at most 10 formatting instructions, so applying it to 100 verification claims is inference. Cost scales with claim count. No one has measured per-claim against per-page agents on documentation.

**Example**: https://shivam.dev/papers/curse-of-instructions.pdf ; https://arxiv.org/abs/2309.11495

**Read**: abstracts and intros only.

### Pattern 5: Deterministic checks for the mechanical slice

**Used by**: DocRef (code-name consistency); pydoclint and griffe's docstring parsers (docstring against signature); Hibi (no model in the verdict path); Docverity (reference checker).

**How it works**: Names, paths, flags and parameter lists are checked by AST, grep or import. The LLM handles only behavior statements.

**Strengths**: No variance, and exhaustive within what the tool parses. DocRef reports over 1,000 real API documentation errors found this way.

**Weaknesses**: No tool found checks markdown prose pages against signatures, so we would have to build the claim-to-symbol mapping. It wouldn't have caught our miss, which is a behavior claim. In the October pass, 39 of 62 findings were behavior claims and only 20 were signatures or defaults.

**Example**: https://jsh9.github.io/pydoclint/notes_for_users.html ; https://people.inf.ethz.ch/suz/publications/oopsla13-docref.pdf ; https://hibi.mintlify.app/design

**Read**: pydoclint notes page; griffe parser warnings via code search; Hibi design page; DocRef abstract; Docverity README.

### Pattern 6: Execution-based verification

**Used by**: FastAPI and pydantic (`pytest-examples`) for doc examples; Doc Detective for procedures; Metamon and Cascade in research.

**How it works**: Examples run in CI. The research tools generate tests from prose and run them against the code.

**Strengths**: The verdict comes from execution, not an LLM's judgment. Metamon gives the most honest ceiling found: precision 0.72, recall 0.48 on Java doc-versus-behavior inconsistencies, using LLMs plus execution.

**Weaknesses**: It covers only what an example or generated test exercises. FastAPI's PR #14569 shows even example coverage needed separate policing.

**Example**: https://github.com/pydantic/pytest-examples/ ; https://arxiv.org/html/2502.02794 ; https://arxiv.org/html/2604.19400v1

**Read**: `pytest-examples` README; head of pydantic `tests/test_docs.py`; FastAPI PR #14569 body and `scripts/docs.py` command list; Metamon and Cascade abstracts and intros.

### Pattern 7: Accept the limitation

**Used by**: FastAPI and pydantic (no prose checking found in what was read); Home Assistant.

**How it works**: Test the examples and leave prose to review and bug reports. Home Assistant's FAQ accepts out-of-date docs and routes them to user feedback, and its RFC to generate docs from schemas (#86050) was closed not_planned.

**Strengths**: No review cost and no false positives.

**Weaknesses**: Errors last until a user hits them.

**Example**: https://www.home-assistant.io/faq/missing-documentation/ ; https://github.com/home-assistant/core/issues/86050

**Read**: both pages. FastAPI and pydantic as listed under Pattern 6, so "no prose checking" means none found in those files, not a proven absence.

### Pattern 8: Seeded-defect evaluation

**Used by**: Song; a mutation-testing study of LLM judges; the "Plant Bugs" harness; the 51-run experiment below.

**How it works**: Apply scripted mutations to known-good artifacts, keep ground truth away from the reviewer, rerun several times, and report recall per defect class plus false positives on clean copies. The "Plant Bugs" harness anchors ground truth by text, not line number.

**Strengths**: It's the only way to get a recall number without hand-labeling.

**Weaknesses**: Easy mutations saturate (95.8-97.8% caught for the easiest operators, 62.3% for removing an attribute). Recall alone can't see over-flagging: two setups differed by 0.5 points on it and 28 points on precision. About one pair in four was ordered differently from manual assessment. Those figures come from a write-up of arXiv 2608.14315, not the paper.

**Example**: https://agentpatterns.ai/verification/mutation-testing-llm-judges/ ; https://dev.to/aicpp_7811/plant-bugs-before-you-trust-the-reviewer-calibrating-a-cheap-model-on-agent-generated-prs-1pck

**Read**: both pages; the underlying paper wasn't opened.

## Anti-Patterns

- **Majority voting on free-text findings.** In a 51-run experiment, a real bug found in 45 of 51 runs failed the threshold because its votes split across two adjacent lines, while repeated grey warnings passed. The model was tiny, so the numbers don't transfer, but the mechanism does. (https://dev.to/tauridev/i-had-a-local-llm-review-the-same-code-51-times-majority-voting-picks-persistence-not-correctness-4g15)
- **Telling the model to find inconsistencies without defining them.** DocPrism's plain prompting flagged 98% of functions, mostly for incompleteness. Filtering after categorization raised F1 from 0.22 to 0.77. Pushing for recall through wording alone is how this fails. (https://arxiv.org/html/2511.00215)
- **Relying on temperature 0 for repeatability.** Outputs still varied across repeated identical prompts at temperature 0, on Claude 3.5 Sonnet among others. (https://arxiv.org/html/2502.20747)

## Emerging Trends

- Change-triggered checking of each PR against the docs (Docdrift, Promptless; Panthaplackel et al. in research), in place of whole-corpus audits. No published recall for prose claims.
- Designs that keep the model out of the pass/fail decision (Hibi, Cascade).

## Gaps

- **Per-page versus per-claim recall on documentation:** none of Metamon, DocPrism, Cascade or CCISolver compares batch sizes.
- **Recall gain past a second pass:** only qualitative guidance found.
- **Whether Docdrift, Promptless, DeepDocs or Mintlify verify prose:** product pages at most; no code or evaluations.
- **Rust doctests, mdBook and Sphinx nitpicky internals:** found but not opened.
- **Primary sources for Hibi's judge-leniency figures:** not traced, so they aren't used here.

Almost all the numbers come from other domains: security review, Java method docs, mixed artifacts. None measures this task.

## Relevance to Us

**We're already past what peers do.** No comparable framework found checks prose at all. Nobody has solved this, and the best LLM-plus-execution recall found is under half, so the realistic goal is better recall and an honest gate, not exhaustive proof.

**The one peer standard we lack is running examples.** FastAPI and pydantic execute theirs; ours are only type-checked. That's a separate, cheap-to-reason-about gap, and it wouldn't have caught the glob claim.

**Candidate order changes.** Multiple passes have the best evidence. The ledger, which looked like the obvious fix, has no evidence for recall and only earns its place as a diagnostic. Scripted checks don't touch the class of claim we actually missed.

**Our agents already want a borderline channel.** Two of today's three runs added an unrequested notes field to their JSON. Run 3 used it to report the `C.Regex` anchoring and dismiss it as "loose but not wrong"; #3723 later listed the same point as a defect. Today the briefing's "confusing but true" line leaves those calls to the verifier, and DocPrism's result suggests separating that judgment from detection.

**The gate has a trigger gap.** Peers working on drift trigger on code changes, while ours triggers on doc edits. Drift caused by a `src/` change is only caught if someone later edits that page.

## Recommendation

**Superseded in part:** `seeded-baseline/README.md` found that moving from Sonnet to Opus closed the recall gap without prompt changes. Test the list below only if Opus proves too expensive.

Test these against a seeded baseline, in this order:

1. **Add a `BORDERLINE` verdict that the main agent adjudicates.** Agents already notice these cases. It's the cheapest change, and triage already exists to filter them.
2. **Run two independent passes and take the union, with no voting.** Triage absorbs the extra false positives, which matters because voting demonstrably loses real findings. Include a condition where the second pass uses a stronger model or a different framing, since the evidence can't say which of those helps.
3. **Add pattern expansion after confirmed findings.** The October pass shows the need, and it costs one targeted search.
4. **Use a per-claim ledger as a diagnostic during the experiment.** Keep it only if it changes recall or shows why misses happen.

**Test smaller batches only if those fall short.** The support is inference and the cost is highest.

**Don't build scripted signature or default checks yet.** They'd need custom mapping, and they miss the class of error that prompted this work.

**Fix the gate's wording regardless.** A clean run should mean "no errors found", not "accurate", which is what peers' acceptance of this limitation implies.

**Evaluation requirements, from the pitfalls above:**

- Report recall by claim class, plus findings on clean copies.
- Include hard behavior seeds, not only easy renames.
- Anchor ground truth by text.
- Include natural defects alongside planted ones. The glob and regex claims are ready-made, as long as #3723 hasn't been fixed or the tests pin the current page.
- Run each cell more than twice. The persona experiment's two runs per cell let one run swing a result by 50 points, and today's page shows a 1-in-4 catch rate.

## Sources

### Reference implementations
- https://github.com/2389-research/documentation-audit/blob/main/skills/SKILL.md — nearest analogue: per-doc agents, pattern expansion, behavior claims sent to human review
- https://github.com/pydantic/pytest-examples/ — lints and runs doc examples
- https://github.com/pydantic/pydantic/blob/b7e81cfc/tests/test_docs.py — pydantic's use of it
- https://github.com/fastapi/fastapi/pull/14569 — policing example test coverage
- https://github.com/deveshagarwal/docverity — deterministic reference checks plus LLM verifier (README only; early project)
- https://mkdocstrings.github.io/griffe/guide/users/checking/ — snapshot API breakage, not docs against code
- https://jsh9.github.io/pydoclint/notes_for_users.html — docstring against signature
- https://docs.doc-detective.com/ — executes doc procedures
- https://swimm.io/blog/how-does-swimm-s-auto-sync-feature-work — tracks code referenced from docs; no language semantics

### Papers
- https://arxiv.org/html/2610.01471v1 — Song: cross-model review with planted errors
- https://arxiv.org/html/2502.20747 — Klishevich et al.: LLM code review determinism
- https://shivam.dev/papers/curse-of-instructions.pdf — recall against instruction count
- https://aclanthology.org/2025.findings-emnlp.896/ — When Instructions Multiply
- https://arxiv.org/html/2411.02400v2 — Decomposition Dilemmas
- https://arxiv.org/html/2403.11903 — A Closer Look at Claim Decomposition
- https://arxiv.org/html/2406.19276 — VeriScore
- https://arxiv.org/abs/2309.11495 — Chain-of-Verification
- https://arxiv.org/html/2502.02794 — Metamon
- https://arxiv.org/html/2511.00215 — DocPrism
- https://arxiv.org/html/2604.19400v1 — Cascade
- https://arxiv.org/abs/2506.20558 — CCISolver: mislabeled benchmark datasets
- https://people.inf.ethz.ch/suz/publications/oopsla13-docref.pdf — DocRef
- https://arxiv.org/abs/2010.01625 — Panthaplackel et al.: just-in-time inconsistency detection

### Blog posts & writeups
- https://snyk.io/blog/snyk-vulnbench-js-1-0-llm-security-review-repeatability/ — 300-run repeatability benchmark
- https://dev.to/tauridev/i-had-a-local-llm-review-the-same-code-51-times-majority-voting-picks-persistence-not-correctness-4g15 — why voting loses real bugs
- https://agentpatterns.ai/verification/mutation-testing-llm-judges/ — mutation testing pitfalls (secondary write-up)
- https://dev.to/aicpp_7811/plant-bugs-before-you-trust-the-reviewer-calibrating-a-cheap-model-on-agent-generated-prs-1pck — seeded-defect harness recipe
- https://hibi.mintlify.app/design — model kept out of the verdict path
- https://docdrift.io/ — change-triggered drift checks (marketing page)
- https://promptless.ai/blog/technical/documentation-drift-detection-problem — drift framing
- https://docs.deepdocs.dev/get-started/introduction/ (not opened)

### Documentation & standards
- https://best.openssf.org/Finding-and-Fixing-Vulnerabilities-Using-AI/run-ai-multiple-times.html — OpenSSF guidance on repeated runs
- https://www.home-assistant.io/faq/missing-documentation/ — accepted limitation
- https://github.com/home-assistant/core/issues/86050 — doc generation RFC, closed not_planned
- https://code.djangoproject.com/ticket/8956 — weak evidence on Django's stance
- https://github.com/sphinx-doc/sphinx/issues/6761 — cross-reference validity
