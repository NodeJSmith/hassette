---
topic: "LLM-agent-based documentation usability evaluation (update of 2026-06-08 beginner-persona-testing)"
date: 2026-10-20
status: Draft
---

# Prior Art: LLM Agents for Docs Usability Evaluation

## The Problem

`doc-persona-review` almost always returns "followable-with-effort", and nothing tells us whether that reflects the docs or the reviewer. A control run on 2026-10-20 (`control/` in this directory) settled the first part. FastAPI's tutorial pages and Hassette's getting-started pages received the identical middle verdict in 24 of 24 runs. Prompt wording, not page quality, decided the finding count: 13–25 findings per page under today's "you must flag" briefing, 3–8 under neutral wording that allows an empty result. Removing our voice guide and doc rules from the briefing did not change the counts.

So the evaluator in its current form cannot discriminate. This brief asks what has changed since the June brief in how people evaluate docs, and LLM judges generally, with agents.

## How We Do It Today

- `doc-persona-review` gives each Sonnet subagent one extracted page plus a persona, the voice guide and the doc rules. The subagent returns JSON findings and a four-level verdict.
- The briefing tells the model to flag anything outside the persona's knowledge even when the model itself understands it. The aim is to counter the curse of knowledge.
- The skill's `schema` enforcement relies on an Agent-tool option that doesn't exist, and the briefing never lists the verdict values. In practice the verdict is free text.
- `ui-qa` already does task-driven persona walkthroughs against the live demo stack: a shared Playwright browser, about 25 actions per persona. It states that per-page review can't see between pages. Docs review has no equivalent.
- The June brief recommended LLM persona review on a cognitive-walkthrough model. Its main source was the UW synthetic heuristic evaluation paper (arXiv 2507.02306). It named "simulating ignorance rather than having it" as the main risk, and the control suggests that risk is real.

## Patterns Found

### Pattern 1: Task-based trace evaluation

**Used by:** Mintlify's 2026 navigation benchmark, UXAgent, UXBench, AX-testing guidance (CircleCI, Resend)
**How it works:** Fix a question set with known answers and give an agent the live site. Record every request or click, whether it reached the answer, and how many dead ends and 404s it hit. Score against ground truth, and vary one factor between arms (page edit, nav change, serving format). Mintlify ran 2,400 such tests over 20 docs sites and concluded the failure was navigation (agents guessing URLs), not reading comprehension.
**Strengths:** The outcome is objective. There's no "find problems" instruction to inflate. Edits can be A/B tested.
**Weaknesses:** LLM agents complete tasks more often than humans (arXiv 2512.03568), so success is an upper bound and failures are the informative signal. Writing the questions is the cost. Mintlify's numbers are vendor-reported and came from search snippets.
**Example:** https://www.mintlify.com/state-of-knowledge/2026/report (snippet only)

### Pattern 2: Controlled-contrast calibration (known-good, known-bad, degraded)

**Used by:** Mintlify (the same questions across four formats), general judge-calibration guidance (gold sets). Our FastAPI control is a partial instance.
**How it works:** Run the evaluator on a known-good doc and on a deliberately degraded copy of it (prerequisite removed, definition deleted, link broken). It is valid only if it separates them run for run. The seeded defects also give recall ground truth.
**Strengths:** Tests discrimination directly, and the current setup fails it. Cheap to build from pages we already have.
**Weaknesses:** Seeded defects may not resemble real ones. No docs-specific published protocol was found.
**Example:** [no source found]

### Pattern 3: Neutral prompt, empty result allowed, findings verified

**Used by:** the overcorrection literature (arXiv 2603.00539, Feb 2026), judge-calibration guides
**How it works:** Drop "you must flag" and make `[]` acceptable. Each finding must quote evidence and name the step it blocks. With fix-guided verification, a finding survives only if applying its fix changes an objective outcome, such as a task passing on re-run. 2603.00539 found that more elaborate review prompts increased false "non-compliant" judgments, which is the same direction as our 13–25 vs 3–8 result.
**Strengths:** Matches what we observed. Cuts false positives without a human.
**Weaknesses:** Can swing to under-detection; 2512.03568 found LLMs reported fewer issues than humans until prompted. It needs the Pattern 2 recall check to catch that.
**Example:** https://arxiv.org/abs/2603.00539

### Pattern 4: Binary or anchored checks instead of an ordinal verdict

**Used by:** Microsoft's BAT/CAT judge white paper (June 2026, snippet only), central-tendency research (arXiv 2605.16386)
**How it works:** Replace the holistic four-level verdict with per-step yes/no questions ("could the reader finish step N with only this page and the ones before it?"), or anchor each level with an exemplar. Unanchored ordinal scales collapse to the middle across model families.
**Strengths:** Removes the attractor that produced 24/24 "with effort". Results are comparable across pages.
**Weaknesses:** The checks have to be written, and a checklist can miss holistic problems.
**Example:** https://microsoft.github.io/mcscatblog/assets/posts/better-llm-scoring/20260626_LLM1-5Scoring_WhitePaper.pdf

### Pattern 5: Deterministic structural scoring of the site

**Used by:** Fern Agent Score (AFDocs), Mintlify
**How it works:** About 23 scripted checks (llms.txt, Markdown availability, page size, JS rendering, auth walls). The score is repeatable.
**Strengths:** Zero variance, free, CI-friendly.
**Weaknesses:** Says nothing about whether the content teaches.
**Example:** https://buildwithfern.com/agent-score

## Anti-Patterns

- **Persona as fidelity.** In 12 first-click tests (n=3,431 humans), GPT's click distribution differed from humans' in 53% of tasks. Persona tweaks raised perceived credibility, not fidelity (arXiv 2605.18302, May 2026). ACM Interactions (Jan 2026) describes synthetic users as unfalsifiable and as "caring about everything equally". Treat personas as framing, not as a simulation of a real reader.
- **Self-consistency read as validity.** Repeated runs under one prompt and one model understate the true variance by 40–60% (arXiv 2604.11581). A judge can be highly self-consistent and still invalid (arXiv 2606.19544). 24/24 agreement is the symptom, not reassurance.
- **"Must flag" prompting.** It produces a directional bias toward finding problems (2603.00539, plus our own control).
- **Checking definitions on a single page in isolation.** It manufactures "undefined term" findings, which were 64 of about 150 under today's setup.

## Emerging Trends

- Evaluation is moving from what the agent says to what the agent does: request traces, dead ends, task success.
- Findings are increasingly scored by whether a repair agent can act on them (UXBench, June 2026).
- Docs for agents is a concern in its own right. Mintlify claims agents now outnumber humans as docs readers (a vendor claim). That justifies an agent-navigability eval even if it never predicts human confusion.

## Relevance to Us

- The control's three main results each match a named pattern in the literature: middle-verdict collapse, prompt-driven inflation, and self-consistency without validity. The problem is mostly the setup, as suspected.
- `ui-qa` already has the machinery for Pattern 1 (Playwright, persona, action budget). A docs version is close to a port, not new infrastructure.
- Pattern 2 is the gate for any change. Whatever replaces today's setup should first show it can tell a page apart from a degraded copy of itself.
- Persona fidelity research argues for keeping personas thin: knowledge boundaries for the task, not a simulation of a person.

## Recommendation

1. Build a seeded-defect control first (Pattern 2). It is the cheapest test, and every later change gets judged against it.
2. Move per-page review to neutral wording with binary per-step checks (Patterns 3 and 4), give the reader the pages that come before, and drop the ordinal verdict.
3. Add task-based navigation as the primary signal (Pattern 1), reusing `ui-qa`'s approach, with a small question set that has written answers. Run the same questions against FastAPI's docs for calibration.
4. Optionally, run Fern's Agent Score once on the site (Pattern 5). It's cheap context but not a quality measure.

**Coverage caveats:**
- Docs-specific prior art is thin.
- Mintlify, Microsoft, and the Fern post are snippet-level or failed to fetch.
- No Kapa.ai or Anthropic/OpenAI docs-team methodology writeup was found.
- The UW 73–77% figure from the June brief was not re-verified.

## Sources

URLs were not live-verified. Per-source detail and dates are in `web-research.md`.

### Papers
- https://arxiv.org/abs/2512.03568 — Synthetic cognitive walkthrough: LLMs complete tasks more often than humans but find fewer issues without extra prompting
- https://arxiv.org/abs/2605.18302 — "What Would GPT Click": persona prompts add credibility, not fidelity
- https://arxiv.org/abs/2606.16262 — UXBench: critiques scored by actionability
- https://arxiv.org/abs/2603.00539 — LLM reviewer overcorrection; fix-guided verification
- https://arxiv.org/abs/2604.11581 — Hidden measurement error in LLM pipelines
- https://arxiv.org/pdf/2606.19544 — Reliability without validity in LLM-as-judge (snippet)
- https://arxiv.org/abs/2605.16386 — Central-tendency bias in LLM ordinal raters (snippet)
- https://arxiv.org/pdf/2502.12561 — UXAgent (https://uxagent.hailab.io/)
- https://arxiv.org/pdf/2507.02306 — UW synthetic heuristic evaluation (from the June brief)

### Reference implementations and reports
- https://www.mintlify.com/state-of-knowledge/2026/report — Mintlify navigation benchmark (snippet)
- https://buildwithfern.com/agent-score — Fern Agent Score / AFDocs

### Writeups
- https://interactions.acm.org/archive/view/january-february-2026/the-challenges-of-synthetic-users-in-ux-research — critique of synthetic users
- https://microsoft.github.io/mcscatblog/assets/posts/better-llm-scoring/20260626_LLM1-5Scoring_WhitePaper.pdf — anchored judge scoring (snippet)
- https://agentpatterns.ai/patterns/anti-patterns/llm-review-overcorrection/ — overcorrection summary
- https://developer.microsoft.com/blog/what-is-agent-experience-ax/ — agent experience (AX)
