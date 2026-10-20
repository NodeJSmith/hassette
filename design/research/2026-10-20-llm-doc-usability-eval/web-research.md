# Web research: LLM agents for documentation usability evaluation

Comparable projects searched first: UXAgent (LLM usability-testing agents), Mintlify / Fern (docs platforms with agent-readiness work), Microsoft/CircleCI/Resend/Builder.io (AX writing), Anthropic skill-authoring docs. Kapa.ai: nothing relevant found. "Verified" = fetched page/abstract; "snippet" = search-result text only.

## Sources Found

### Synthetic Cognitive Walkthrough: Aligning LLM Performance with Human Cognitive Walkthrough
- **URL**: https://arxiv.org/abs/2512.03568
- **Date**: 2025-12-03
- **Type**: paper (verified abstract)
- **Key takeaway**: LLMs (GPT-4, Gemini 2.5 Pro) complete tasks more often and via more optimal paths than humans, but find FEWER usability issues; additional prompting closes much of the gap in predicting human failure points.
- **Relevance**: Opposite failure direction from your inflation problem. Prompting is what moves the issue count, which matches your finding that wording drives counts. The agent-succeeds-where-human-fails gap also cautions that task success is an upper bound on human success.

### What Would GPT Click: Human-AI Behavioral Misalignment and the Cost of Synthetic Participants in UX
- **URL**: https://arxiv.org/abs/2605.18302
- **Date**: 2026-05-18
- **Type**: paper (verified abstract)
- **Key takeaway**: 12 first-click tests (n=3,431 humans); GPT's click distribution differed significantly from real data in 53% of tasks. Persona tweaks and sampling parameters mostly raised perceived credibility, not fidelity.
- **Relevance**: Direct evidence that persona prompts ("fresh Python dev", "AppDaemon migrator") add little real fidelity. Treat persona as framing, not a validated simulation.

### UXBench: Measuring the Actionability of LLM-Generated UX Critiques
- **URL**: https://arxiv.org/abs/2606.16262
- **Date**: 2026-06-15
- **Type**: paper/benchmark (verified abstract)
- **Key takeaway**: Models must gather interaction evidence in runnable web fixtures, then critiques are scored by whether a fixed downstream repair agent can improve the interface from them. Actionability and reliability vary by model and interface type.
- **Relevance**: A model for scoring findings by "does fixing it help" instead of counting them. Could be adapted: apply the finding's fix, re-run the task eval, see if success improves.

### When Synthetic Users Fail: Cross-Domain Benchmark of LLM-Simulated Human Survey Responses
- **URL**: https://arxiv.org/pdf/2607.26348
- **Date**: ~2026-07 (arXiv ID; not fetched)
- **Type**: paper (title only, from search)
- **Key takeaway**: Not read; listed as a lead for synthetic-user failure modes.
- **Relevance**: Low-confidence pointer only.

### Grounding Persona-Driven Usability Simulation in Established Standards
- **URL**: https://www.researchgate.net/publication/413823893_Grounding_Persona-Driven_Usability_Simulation_in_Established_Standards
- **Date**: unknown (2026 likely)
- **Type**: paper (snippet)
- **Key takeaway**: Snippet says LLM synthetic users may fail to link frustrations to diagnosable standards and can confound genuine defects with hallucinated constraints.
- **Relevance**: Matches your "undefined term" inflation from single-page isolation: the agent invents a constraint (no context) and reports it as a defect. Not read in full.

### The Challenges of Synthetic Users in UX Research (ACM Interactions)
- **URL**: https://interactions.acm.org/archive/view/january-february-2026/the-challenges-of-synthetic-users-in-ux-research
- **Date**: 2026-01/02
- **Type**: magazine article (snippet only; search also surfaced a "Synthetic Persona Fallacy" piece in the same issue)
- **Key takeaway**: Synthetic users are unfalsifiable, sycophantic, and "care about everything equally." Recommended use: early exploration only; decisions go through real participants.
- **Relevance**: Explains why severity/priority from personas is unreliable: no differential weighting. Argues for counting verifiable task failures over persona opinions.

### Synthetic Heuristic Evaluation (UW, the earlier brief's source)
- **URL**: https://arxiv.org/pdf/2507.02306
- **Date**: 2025-07
- **Type**: paper (snippet; not re-read)
- **Key takeaway**: LLM evaluators caught most issues humans did, but also produced many false positives and misplaced issues (per snippet-level recall of the paper; the 73-77% figure is from the earlier brief, not re-verified here).
- **Relevance**: Recall-only framing. Doesn't give you a precision/control methodology.

### UXAgent: LLM-Agent-Based Usability Testing Framework for Web Design
- **URL**: https://arxiv.org/pdf/2502.12561 (CHI EA 2025: https://dl.acm.org/doi/10.1145/3706599.3719729; system paper https://arxiv.org/pdf/2504.09407)
- **Date**: 2025-02 / 2025-04
- **Type**: paper / reference implementation (https://uxagent.hailab.io/)
- **Key takeaway**: Persona generator + agent that browses a live site + connector; produces thousands of simulated sessions with behavioral logs. It generates data; fidelity against humans is a separate open question.
- **Relevance**: Closest architecture to your option (2), a live-site browsing agent. Its value is behavioral traces (steps, dead ends), not opinions.

### Mintlify 2026 State of Knowledge Report (controlled navigation benchmark)
- **URL**: https://www.mintlify.com/state-of-knowledge/2026/report
- **Date**: published ~2026-09-17 (press: https://www.morningstar.com/news/business-wire/20260917477557/...)
- **Type**: vendor report (snippet from search; page not fetched)
- **Key takeaway**: 2,400 controlled tests over 20 docs sites, same questions served 4 ways, every agent request counted. Reported mean 404s per task: HTML 2.23, Markdown 1.42, Markdown+llms.txt 0.11. Conclusion: reading wasn't the failure, navigation was (agents guess URLs).
- **Relevance**: Best template for option (2): same question set, observe request traces, measure failed requests/steps instead of asking the agent how it felt. Vendor-run, so treat the headline numbers with caution.

### Fern Agent Score (AFDocs)
- **URL**: https://buildwithfern.com/post/agent-score ; engine: github.com/agent-ecosystem/afdocs ; leaderboard https://buildwithfern.com/agent-score
- **Date**: 2026 (exact date unknown)
- **Type**: reference implementation (snippet; post fetch failed to render)
- **Key takeaway**: Lighthouse-style 0-100 score from ~23 deterministic checks (llms.txt, markdown availability, JS rendering, auth walls, page size, etc.), proportional scoring across pages. Structural, not content comprehension.
- **Relevance**: Deterministic checks give zero run-to-run variance and no finding inflation. Complements, not replaces, content evals. Possibly useful to run once on the MkDocs site.

### Agent experience (AX) writing: Microsoft, CircleCI, Resend, Builder.io
- **URL**: https://developer.microsoft.com/blog/what-is-agent-experience-ax/ ; https://circleci.com/topics/agent-experience/ ; https://resend.com/blog/agent-experience
- **Date**: 2025-2026
- **Type**: blog posts (snippets)
- **Key takeaway**: Recommended practice: run representative agent workflows (find tool, construct valid request, recover from failure) and keep fixed failures as regression cases.
- **Relevance**: Supports "task + known answer + regression suite" design. No calibration methodology offered.

### Are LLMs Reliable Code Reviewers? Systematic Overcorrection in Requirement Conformance Judgement
- **URL**: https://arxiv.org/abs/2603.00539 (journal: https://link.springer.com/article/10.1007/s10515-026-00638-5); summary: https://agentpatterns.ai/patterns/anti-patterns/llm-review-overcorrection/
- **Date**: 2026-02-28
- **Type**: paper (verified abstract)
- **Key takeaway**: LLMs misclassify correct code as non-compliant, a directional bias toward finding problems; more elaborate prompts asking for explanation and correction INCREASE misjudgment. Mitigation: fix-guided verification (a finding counts only if the proposed fix changes an objective outcome).
- **Relevance**: Closest published analogue to your 13-25 vs 3-8 finding result, in a different domain. The fix-guided filter maps onto "finding is real only if applying it makes a task pass."

### Microsoft BAT/CAT white paper: Measuring Quality with LLM Judges
- **URL**: https://microsoft.github.io/mcscatblog/assets/posts/better-llm-scoring/20260626_LLM1-5Scoring_WhitePaper.pdf
- **Date**: 2026-06-26
- **Type**: practitioner white paper (snippet only)
- **Key takeaway**: Per snippets: 1-5 Likert without exemplars collapses to middle scores; judges disagree on what "3" vs "5" means; position-swap debiasing raised consistency from ~60% to ~85%.
- **Relevance**: Explains verdict collapse to "followable-with-effort." Remedy: anchored exemplars per level, or binary checks.

### Auditing Multimodal LLM Raters: Central Tendency Bias in Clinical Ordinal Scoring
- **URL**: https://arxiv.org/abs/2605.16386
- **Date**: 2026-05
- **Type**: paper (snippet)
- **Key takeaway**: Systematic compression toward the scale middle across three LLM families, over-predicting low and under-predicting high ends.
- **Relevance**: Independent confirmation that a 4-level ordinal verdict will collapse. Different domain.

### Hidden Measurement Error in LLM Pipelines
- **URL**: https://arxiv.org/abs/2604.11581
- **Date**: 2026-04-13 (rev. 2026-05-13)
- **Type**: paper (verified abstract)
- **Key takeaway**: Naive standard errors are 40-60% smaller than ones that include judge-model, temperature and prompt-formulation variance; that variance doesn't shrink with more samples.
- **Relevance**: Your 24/24 identical verdicts is not evidence of reliability: runs share one prompt and model, so run-to-run agreement hides prompt-design sensitivity. Vary prompt wording and model as a factor in the control.

### Reliability without Validity: Large-Scale Evaluation of LLM-as-a-Judge (agreement, consistency, bias)
- **URL**: https://arxiv.org/pdf/2606.19544
- **Date**: 2026-06
- **Type**: paper (title/snippet only)
- **Key takeaway**: Judges can be highly self-consistent yet invalid.
- **Relevance**: Same point as the previous entry, and exactly what 24/24 identical verdicts on FastAPI vs Hassette shows. Not read in full.

### Judge calibration guides (gold set, confusion matrix, abstention)
- **URL**: https://insights.v3rsai.com/articles/llm-judge-calibration-guide/ ; https://galileo.ai/blog/why-llm-as-a-judge-fails
- **Date**: unknown
- **Type**: practitioner blogs (snippets)
- **Key takeaway**: Calibrate against a labelled gold set; report precision/recall for the class that matters, false-pass and false-fail rates, abstention rate. "Not mentioned" must not count as support.
- **Relevance**: Standard methodology for your "controls" question. Low authority, but consistent with the papers.

## Patterns Found

### Pattern 1: Task-based trace evaluation (count what the agent does, not what it says)
**Used by**: Mintlify's navigation benchmark; UXAgent (behavioral logs); AX-testing guidance (CircleCI, Resend); UXBench (interaction-grounded).
**How it works**: Fix a question set with known answers. Give an agent a live site (or a controlled variant). Record every request or click, whether it reached the answer, number of dead ends and 404s. Score against ground truth. Vary one factor (format, nav link, page edit) between arms.
**Strengths**: Outcome is objective. No finding-count inflation because there is no "find problems" instruction. Per-page edits can be A/B tested.
**Weaknesses**: LLM agents out-navigate humans (2512.03568), so success overstates human success; failures are the informative signal. Question authoring is the cost. Vendor results are self-reported.
**Example**: https://www.mintlify.com/state-of-knowledge/2026/report (snippet-level)

### Pattern 2: Controlled-contrast calibration (known-good vs known-bad vs degraded)
**Used by**: Mintlify (same questions across 4 serving formats); general judge-calibration guidance (gold sets). Your own FastAPI control is an instance.
**How it works**: Include a known-good doc, a known-bad doc, and a deliberately degraded copy of a good doc (remove a prerequisite, break a link, delete a definition). The evaluator is valid only if it separates them. Report discrimination (does degraded score worse than original, run-for-run), not agreement with itself.
**Strengths**: Directly tests whether the evaluator can see a difference; your 24/24 tie shows the current one cannot. Degradations also give recall ground truth.
**Weaknesses**: Synthetic defects may not represent real ones. No published docs-specific version found. [no source found] for a docs-page-specific seeded-defect protocol.
**Example**: [no source found]

### Pattern 3: Neutral prompt with permitted-empty output, verified findings
**Used by**: Overcorrection literature (2603.00539); calibration guides (abstention rate, false-fail rate).
**How it works**: Don't instruct "you must flag"; allow `[]`. Require each finding to quote evidence and to state which task step it blocks. Optionally apply fix-guided verification: a finding survives only if the suggested edit changes a task outcome in a re-run.
**Strengths**: Matches your own result (3-8 vs 13-25). Cuts false positives without a human.
**Weaknesses**: Can swing to under-detection (2512.03568 found under-detection). Needs a recall check from seeded defects.
**Example**: https://agentpatterns.ai/patterns/anti-patterns/llm-review-overcorrection/

### Pattern 4: Replace ordinal verdicts with anchored or binary checks
**Used by**: Microsoft BAT/CAT white paper (snippet); central-tendency literature (2605.16386).
**How it works**: Per-step yes/no questions ("could the reader complete step N using only text on this page?") or per-level exemplars, instead of a 4-level holistic verdict. Aggregate checks into a score.
**Strengths**: Avoids the "middle category" attractor; easier to calibrate; checks are comparable across pages.
**Weaknesses**: Needs authoring; checklists can miss holistic problems.
**Example**: https://microsoft.github.io/mcscatblog/assets/posts/better-llm-scoring/20260626_LLM1-5Scoring_WhitePaper.pdf

### Pattern 5: Deterministic structural lint of the docs site
**Used by**: Fern Agent Score / AFDocs; Mintlify.
**How it works**: Script checks (llms.txt, markdown availability, page size, JS rendering, broken links). Score is repeatable.
**Strengths**: Free, zero variance, CI-friendly.
**Weaknesses**: Says nothing about whether content teaches.
**Example**: https://buildwithfern.com/agent-score

## Anti-Patterns

- **Persona as fidelity**: persona prompts increased credibility without fidelity (2605.18302). Don't read persona verdicts as human predictions.
- **Self-consistency as validity**: 24/24 same verdict is consistent but invalid (2604.11581, 2606.19544).
- **"Must flag" prompting**: directional bias toward findings (2603.00539); your 13-25 result.
- **Single-page isolation for term-definition checks**: manufactures "undefined term" findings (snippet-level support from the persona-grounding paper; your own control is the stronger evidence). Give the agent the site's nav/glossary or judge terms against a task.
- **Treating synthetic output as decision data**: ACM Interactions guidance is to route decisions through real users.

## Emerging Trends

- Evaluation shifting from "agent opinion" to "agent behavior traces" (Mintlify, UXBench).
- Actionability scoring: judge findings by whether a repair agent's fix improves outcomes (UXBench).
- Docs-for-agents is a mainstream concern (Mintlify's report claims agents now outnumber humans as readers; vendor claim), so an agent-navigability eval is increasingly justified on its own, independent of human-simulation validity.

## Gaps

- No published docs-specific benchmark of "agent finds answer on a live docs site, scored against known answer" besides Mintlify's vendor study. [no source found]
- No Kapa.ai or Anthropic/OpenAI docs-team writeup on eval methodology found.
- No docs-page persona-review calibration study found. [no source found]
- Several sources above are snippet-only (flagged in each entry); the Fern post and Mintlify report page were not successfully fetched.
