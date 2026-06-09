---
topic: "beginner-persona-doc-testing"
date: 2026-06-08
status: Draft
---

# Prior Art: Beginner Persona Testing for Developer Documentation

## The Problem

Documentation that passes style checks and structural audits can still be incomprehensible to a newcomer. The curse of knowledge makes expert reviewers unreliable judges of beginner experience: they unconsciously fill in gaps, assume context, and approve docs that would lose a first-time reader at step 3.

The question is whether LLMs, prompted with a beginner persona, can simulate that "fresh eyes" evaluation at CI-friendly speed and cost, or whether this is a category of problem that requires real humans.

## How We Do It Today

Hassette has a comprehensive voice audit tool (`tools/docs/check_doc_voice.py`) that enforces 15+ prose and structural rules across 71 pages in CI. It catches em dashes, copula avoidance, pronoun violations, stacked admonitions, and missing recipe sections. Code snippets are Pyright-tested via `--8<--` includes. What's missing is any evaluation of whether a page is *followable* by someone who doesn't already know the system.

## Patterns Found

### Pattern 1: Automated Style Linting (Vale)

**Used by**: GitLab, Datadog, Spectro Cloud, Elastic
**How it works**: CLI tools like Vale run configurable prose rules in CI: sentence length, banned jargon, passive voice, readability scores. Teams start with industry rulesets (Microsoft, Google) and add project-specific rules.
**Strengths**: Fast, deterministic, scales to any team size, runs on every commit.
**Weaknesses**: Cannot evaluate conceptual comprehension. A perfectly Vale-clean page can still confuse a beginner if the conceptual progression is wrong or prerequisites are missing.
**Example**: https://docs.gitlab.com/development/documentation/testing/vale/

### Pattern 2: Cognitive Walkthrough (Human Expert Simulation)

**Used by**: UX teams broadly, adapted for docs by technical writing teams
**How it works**: An evaluator walks through a tutorial step by step as a first-time user, asking four questions at each step: (1) Will the user know what to do? (2) Will they notice the correct action? (3) Will they connect the action to the goal? (4) Will they see progress?
**Strengths**: Low cost (no real users), structured methodology, specifically targets learnability.
**Weaknesses**: Experts struggle to suppress their own knowledge. The "curse of knowledge" is the whole reason this is hard. Time-intensive for long doc sets.
**Example**: https://www.nngroup.com/articles/cognitive-walkthroughs/

### Pattern 3: Task-Based Usability Testing with Real Users

**Used by**: Sendbird, Stripe, Twilio
**How it works**: Real developers matching the target persona follow docs to complete tasks while observed. Single-blind design prevents bias. Measures time-to-completion, error count, satisfaction. Think-aloud captures reasoning.
**Strengths**: Highest fidelity. Captures failure modes no automated tool finds ("I assumed the import was in the previous step"). Sendbird's study identified broken copy-paste code as the #1 friction point.
**Weaknesses**: Expensive ($500-2000/participant), slow (weeks of recruitment), small samples, point-in-time snapshots.
**Example**: https://sendbird.com/blog/evaluating-developers-onboarding-experience-ux-benchmarking-study

### Pattern 4: Documentation-as-Tests (Executable Docs)

**Used by**: Doc Detective users, Stripe (internal tooling)
**How it works**: Code samples and commands in docs are extracted and executed against the real product in CI. Catches documentation drift when the product changes but docs don't.
**Strengths**: Catches the #1 onboarding killer (broken code samples). Deterministic. Hassette already partially does this via Pyright-checked snippet files.
**Weaknesses**: Only tests "does this work?" not "does this make sense?"
**Example**: https://docs.doc-detective.com/

### Pattern 5: LLM Persona-Based Documentation Review

**Used by**: Early adopters, no standardized framework. Google officially recommends it. UW research validated it empirically.
**How it works**: An LLM is prompted with a detailed persona (skill level, domain knowledge, goals) and asked to read docs as that persona, flagging confusion points. The prompt includes cognitive walkthrough questions or a quality rubric. Multiple personas run in parallel (complete beginner, intermediate dev new to the domain, experienced dev skimming).

The UW synthetic heuristic evaluation study (2025) found LLM evaluators identified 73-77% of usability issues vs 57-63% for experienced human evaluators.

**Strengths**: Cheap (pennies per review), fast (minutes), repeatable on every PR, produces reasoning traces showing where and why confusion occurs. Avoids the curse of knowledge that plagues expert walkthroughs. Can run multiple personas in parallel.
**Weaknesses**: LLMs don't genuinely lack knowledge, they simulate lacking it. May miss confusion arising from real knowledge gaps. No established benchmarks for how well findings correlate with real beginner findings. Risk of false positives and false negatives.
**Example**: https://developers.google.com/tech-writing/two/llms (Google guidance), https://arxiv.org/abs/2507.02306 (UW empirical validation)

### Pattern 6: Quality Rubric / Checklist Assessment

**Used by**: Tom Johnson (idratherbewriting), API documentation teams
**How it works**: A 50-70+ item checklist covering Findability, Accuracy, Clarity, Completeness, Readability is applied systematically. Each item gets pass/fail/partial. Originally for human reviewers; increasingly given to LLMs as evaluation criteria.
**Strengths**: Structured, comprehensive, produces actionable findings. The checklist itself documents quality standards.
**Weaknesses**: Time-intensive for humans. Can become compliance exercise rather than genuine comprehension check.
**Example**: https://idratherbewriting.com/learnapidoc/docapis_quality_checklist.html

### Pattern 7: Metrics-Based Health Tracking

**Used by**: Stripe, Twilio, DX-focused platforms
**How it works**: Track time-to-first-API-call, support ticket categories, page analytics, search queries with no results. DX research found 2.4x delivery performance correlation with doc quality.
**Strengths**: Objective, continuous, tied to business outcomes.
**Weaknesses**: Lagging indicators. Requires traffic volume Hassette doesn't have yet.
**Example**: https://getdx.com/blog/developer-documentation/

## Anti-Patterns

- **Readability scores as quality measure**: Flesch-Kincaid measures syllable count, not conceptual clarity. Short sentences with undefined prerequisites still confuse beginners.
- **User surveys as primary signal**: Low response rates, vague feedback, self-blame bias. Not actionable.
- **Expert review without persona adoption**: Domain experts unconsciously fill gaps. Without structured walkthrough questions, they approve docs that confuse newcomers.
- **Comprehension testing without code correctness testing**: Sendbird found broken copy-paste code was the #1 friction point, outweighing all prose quality concerns. Both layers are needed.

## Emerging Trends

**LLM personas as cognitive walkthrough automation** is the most active area. It combines the structured methodology of cognitive walkthroughs with LLM persona simulation to address the curse-of-knowledge problem. No standardized tool exists yet; teams are building bespoke prompts. The UW 2025 study provides early empirical validation.

**Multi-layer pipelines** are forming: Vale for style (every commit), Doc Detective for code correctness (every commit), LLM persona review for comprehension (periodic or on significant changes), real user testing for validation (quarterly).

## Relevance to Us

Hassette already covers layers 1 and 2 well: `check_doc_voice.py` handles style enforcement and structural rules, and Pyright-checked snippet files handle code correctness. The missing layer is comprehension testing.

Pattern 5 (LLM persona review) is the best fit because:
- It addresses the exact gap (is this followable by a beginner?)
- It can reuse the cognitive walkthrough methodology (structured per-step questions)
- It integrates with our existing subagent patterns (dispatch persona agents in parallel)
- It's cheap enough to run on every significant docs change
- The voice guide and doc-rules already define page types and expectations, which can serve as evaluation criteria

The main risk: the LLM simulates lacking knowledge rather than genuinely lacking it. Mitigation: constrain the persona tightly ("you do NOT know what dependency injection is, you have never seen the D.StateNew syntax") and look for specific failure classes (undefined terms, missing imports, unclear next steps) rather than vague "this is confusing" feedback.

## Recommendation

Build an LLM persona reviewer as a new tool or skill. The design would be:

1. **Persona definitions**: 2-3 personas with explicit knowledge boundaries (e.g., "Python developer, 2 years, no HA experience, no async event systems"; "Node.js developer, HA user, first time writing Python automations")
2. **Cognitive walkthrough prompt**: At each step, answer the four questions (will the reader know what to do? notice the action? connect it to the goal? see progress?)
3. **Page-type awareness**: Getting-started pages get the full walkthrough; concept pages get a "can you explain back what this does?" check; recipes get "could you modify this for a different sensor?"
4. **Structured output**: Findings as a JSON list with line numbers, confusion type, and severity

Start with getting-started pages (highest beginner traffic) and recipes (task-oriented, most testable). Run it manually first before CI integration.

## Sources

### Academic research
- https://arxiv.org/abs/2507.02306 -- UW synthetic heuristic evaluation study (LLM evaluators outperformed human experts)
- https://arxiv.org/pdf/2312.02586 -- Documentation experience study (exploration/comprehension/application phases)
- https://www.emergentmind.com/topics/personallm -- PersonaLLM research aggregator

### Reference implementations
- https://docs.gitlab.com/development/documentation/testing/vale/ -- GitLab Vale CI integration
- https://www.datadoghq.com/blog/engineering/how-we-use-vale-to-improve-our-documentation-editing-process/ -- Datadog Vale usage
- https://docs.doc-detective.com/ -- Doc Detective executable documentation testing

### Industry case studies
- https://sendbird.com/blog/evaluating-developers-onboarding-experience-ux-benchmarking-study -- Sendbird single-blind onboarding study
- https://sendbird.com/blog/qualitative-evaluation-of-onboarding-new-developers-a-ux-benchmarking-study-part-2 -- Sendbird qualitative findings

### Methodologies and guides
- https://developers.google.com/tech-writing/two/llms -- Google's guidance on LLM persona prompting for doc review
- https://www.nngroup.com/articles/cognitive-walkthroughs/ -- NN/g cognitive walkthrough methodology
- https://en.wikipedia.org/wiki/Cognitive_walkthrough -- Cognitive walkthrough overview
- https://idratherbewriting.com/learnapidoc/docapis_quality_checklist.html -- Tom Johnson's quality checklist
- https://idratherbewriting.com/blog/measuring-documentation-quality-rubric-developer-docs/ -- Documentation quality rubric

### Tools
- https://vale.sh/library -- Vale prose linter
- https://hemingwayapp.com/articles/readability/readability-score -- Hemingway readability scoring
- https://www.docsastests.com/validate-api-with-doc-detective -- Docs as tests methodology

### Industry research
- https://getdx.com/blog/developer-documentation/ -- DX documentation impact (2.4x delivery performance)
- https://aws.amazon.com/blogs/machine-learning/simulate-realistic-users-to-evaluate-multi-turn-ai-agents-in-strands-evals/ -- AWS Strands persona simulation
- https://buildwithfern.com/post/docs-linting-guide -- Fern docs linting guide (2026)
- https://klariti.com/2025/02/11/comparing-5-llms-to-review-long-documents-a-technical-writers-experiment/ -- Multi-LLM doc review experiment
- https://www.spectrocloud.com/blog/how-we-use-vale-to-enforce-better-writing-in-docs-and-beyond -- Spectro Cloud Vale usage
