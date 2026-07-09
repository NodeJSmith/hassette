---
topic: "Preventing LLMs from duplicating test infrastructure"
date: 2026-07-08
status: Draft
---

# Prior Art: Preventing LLMs from Duplicating Test Infrastructure

## The Problem

LLMs default to generation over discovery. When told to write or modify a test, they create new helpers, factories, and fixtures rather than finding and reusing existing ones. GitClear's analysis of 211M+ changed lines shows code duplication up 4x and code reuse down 70% in the AI era — test infrastructure duplication is a specific, measurable instance of this industry trend.

The problem compounds: each duplicated factory diverges slightly from the canonical version, naming collisions accumulate, and a reader can no longer tell which `make_job()` (of 11) is the "right" one. The hassette audit found ~130 local `make_*/build_*` factories across 400 test files, while the dedicated `factories.py` (built specifically to absorb them) held only 3.

## How We Do It Today

Hassette has a two-hop guidance chain: CLAUDE.md names the two primary mock strategies (`HassetteHarness` and `create_hassette_stub()`) and points to `tests/TESTING.md`, which provides a detailed decision table, factory inventory, and code examples. `test_utils/__init__.py` uses a two-tier export scheme (Tier 1 stable public API, Tier 2 internal re-exports). No `.claude/rules/` file addresses test writing. No lint rules enforce test infrastructure reuse. The guidance is comprehensive but entirely advisory — an LLM that skips TESTING.md (or whose context fills before reaching it) has nothing preventing reinvention.

## Patterns Found

### Pattern 1: Instruction File Prohibitions

**Used by**: Teams using CLAUDE.md, SKILL.md, .cursorrules, copilot-instructions.md
**How it works**: Explicit prohibitions in project instruction files name the canonical test infrastructure and ban alternatives. "Use `HassetteHarness` for integration tests" is enforceable; "follow existing test patterns" is not. The Canvas iOS `CLAUDE-unit-tests.md` is the gold standard: naming conventions, helper organization, factory patterns, what NOT to test — leaving almost no room for improvisation. Progressive loading via SKILL.md keeps context lean by loading test conventions on demand rather than bloating every session.
**Strengths**: Low-cost, immediately effective, version-controlled. Works across all AI coding tools.
**Weaknesses**: Advisory, not enforced. LLMs can ignore instructions as context fills. Effectiveness degrades with file length.
**Example**: https://github.com/instructure/canvas-ios/blob/master/CLAUDE-unit-tests.md

### Pattern 2: Banned-API Lint Rules

**Used by**: Teams with mature CI, documented in "Lint Against the Machine"
**How it works**: Linter rules ban direct usage of primitives that should go through project infrastructure. Ruff's `TID251` bans specific imports with a custom message pointing to the project's wrapper. Applied to tests: ban `MagicMock()` in test files that should use `make_mock_hassette()`, ban raw `Event()` construction in files that should use `create_state_change_event()`. Pre-commit hooks can block new class/function definitions matching patterns that duplicate shared implementations.
**Strengths**: Deterministic, cannot be ignored by the LLM, fast, catches human violations too. Error messages direct to the correct utility.
**Weaknesses**: Requires upfront pattern identification. Cannot catch semantic duplication (different code doing the same thing). Only as good as the patterns defined.
**Example**: https://medium.com/@montes.makes/lint-against-the-machine-a-field-guide-to-catching-ai-coding-agent-anti-patterns-3c4ef7baeb9e

### Pattern 3: Scaffold-First Generation

**Used by**: AgiFlow (aicode-toolkit), teams using template generators
**How it works**: Instead of letting the AI generate test files from scratch, a scaffolding tool creates the file from a project-defined template that already includes standard imports, fixture references, and helper functions. The AI "fills the blanks instead of rewriting the world." Hooks proactively trigger the scaffold when the AI creates a file matching a pattern (e.g., `test_*.py`).
**Strengths**: Structural prevention — the right infrastructure is there before the AI starts. Template changes propagate to all future tests.
**Weaknesses**: Requires maintaining templates alongside actual infrastructure. Overhead for projects with diverse test patterns. Not all AI tools support MCP-based scaffolding.
**Example**: https://github.com/AgiFlow/aicode-toolkit/tree/main/packages/scaffold-mcp

### Pattern 4: Decision Ladder / Reuse-First Hierarchy

**Used by**: Ponytail plugin users
**How it works**: Before writing any code, the AI walks a priority ladder: (1) Does this need to exist? (2) Already in codebase? (3) Standard library? (4) Installed dependency? (5) One-liner? (6) Only then, write minimum code. Applied to test infrastructure: check conftest.py and test_utils first, then pytest builtins, then installed libraries, then write a new helper. Benchmarked at 54% less code, 20% cheaper, 27% faster.
**Strengths**: Addresses the root cause (generation over discovery). Works as a general principle. Safety-exempt (validation/security untouched).
**Weaknesses**: Still advisory. Effectiveness depends on LLM's search quality. May slow simple tasks.
**Example**: https://github.com/DietrichGebert/ponytail

### Pattern 5: Subagent Investigation Before Test Writing

**Used by**: Claude Code users, documented in official best practices
**How it works**: Before writing tests, dispatch a subagent to explore existing test infrastructure. The subagent reports discovered helpers, fixtures, and patterns. The main session writes tests using the discovered infrastructure. Separates discovery from generation.
**Strengths**: Keeps discovery context separate. Forces explicit awareness. Works well for large codebases.
**Weaknesses**: Adds latency and cost. Not automated — relies on workflow discipline. The subagent may miss things.
**Example**: https://code.claude.com/docs/en/best-practices

### Pattern 6: Test Co-Location for Attention Amplification

**Used by**: Research finding (AIware 2026, peer-reviewed)
**How it works**: Co-located code receives 2.8-4.4x stronger attention from foundation models. A `conftest.py` in the same directory as the test file gets more attention than one three directories up. By extension, placing representative examples of correct test patterns near where the LLM will work increases reuse.
**Strengths**: Empirically backed across 12 models. Requires no tooling — just structural decisions.
**Weaknesses**: May conflict with project structure conventions. Research studied inline tests; extension to co-located helpers is inference.
**Example**: https://arxiv.org/abs/2604.19826

### Pattern 7: Multi-Layer Enforcement

**Used by**: Community consensus from GitHub discussions, practitioner reports
**How it works**: No single layer is sufficient. Combine: (1) instruction files for guidance, (2) lint rules for deterministic prevention, (3) CI checks for enforcement, (4) human/AI review as final safety net. "The AI can drift, but the tooling cannot." Models follow concrete examples more consistently than long prose, so the instruction layer should emphasize examples over description.
**Strengths**: Defense in depth. Each layer compensates for others' weaknesses. Catches both AI and human violations.
**Weaknesses**: Highest setup cost. Maintenance burden across multiple enforcement points.
**Example**: https://github.com/orgs/community/discussions/197384

## Anti-Patterns

1. **Vague instructions without specifics** — "Follow existing test patterns" is interpreted as license to infer patterns from training data. Name the helper, the import path, the convention.
2. **Over-long instruction files** — CLAUDE.md files over ~200 lines cause critical rules to get lost. Use progressive loading (core in CLAUDE.md, detail in SKILL.md or referenced files).
3. **Instructions without enforcement** — Advisory-only approaches reduce duplication but cannot prevent it. Without lint/CI, violations accumulate across sessions.
4. **Copy-paste-modify without refactoring** — AI users copy and modify code 4x more, while refactoring dropped 61%. Applied to tests: copied test files never extract common setup into shared fixtures.

## Relevance to Us

Hassette is well-positioned for Pattern 1 (instruction files) — TESTING.md is comprehensive and CLAUDE.md already references it. The gap is that this guidance is entirely advisory with no structural enforcement.

The highest-leverage additions based on this research:

**Pattern 2 (banned-API lint rules) maps directly to existing infrastructure.** Hassette already has custom pre-commit linters (`tools/check_*.py`). Adding a `check_test_factories.py` that bans raw `MagicMock(spec=Event)` in favor of `make_mock_event()`, or flags local `make_job()` definitions when `test_utils.factories.make_scheduled_job` exists, would catch the exact duplication pattern the audit found. This is the "encode lessons in structure" principle from the Claudefiles rules.

**Pattern 1 (instruction file prohibitions) needs a dedicated test-writing rule.** Currently no `.claude/rules/` file fires when an LLM writes test code. A `test-conventions.md` rule that names the canonical factories, links to TESTING.md, and says "check test_utils/factories.py before defining a local make_* function" would close the two-hop discovery gap.

**Pattern 4 (decision ladder) aligns with the existing laziness-protocol.md** in Claudefiles. A test-specific version of the ladder ("check conftest.py → check test_utils → check pytest builtins → only then write new") would be a natural extension.

**Pattern 6 (co-location) partially explains why duplication persists.** The test_utils package is 3-4 directories removed from most test files. The conftest hierarchy is the right structural answer for pytest, but the LLM may not attend to conftest files it doesn't explicitly read. Ensuring CLAUDE.md or a rule file names the specific factories would compensate.

**Pattern 3 (scaffold-first) is overkill for this project.** Hassette's test patterns are diverse enough that a scaffold would need many templates. The lint-rule approach is more surgical.

## Recommendation

The most impactful move is **Pattern 2 + Pattern 1 together**: a dedicated `.claude/rules/test-conventions.md` that names the canonical test infrastructure (closing the discovery gap) backed by a `tools/check_test_factories.py` lint rule that catches local reinventions of shared factories (closing the enforcement gap). This maps to the project's existing convention of hand-written linters in `tools/` and rule files in `.claude/rules/`.

Pattern 7 (multi-layer) is already partially in place — what's missing is the test-specific layer at each level.

## Sources

### Reference implementations
- https://github.com/instructure/canvas-ios/blob/master/CLAUDE-unit-tests.md — Production test instruction file for Canvas iOS
- https://github.com/clear-solutions/unit-tests-skills/blob/main/CLAUDE.md — Installable test-writing skill with duplicate checking
- https://github.com/rohitg00/awesome-claude-code-toolkit/blob/main/templates/claude-md/python-project.md — Python project CLAUDE.md template with test conventions
- https://github.com/DietrichGebert/ponytail — "Lazy senior dev" reuse-first hierarchy plugin
- https://github.com/AgiFlow/aicode-toolkit/tree/main/packages/scaffold-mcp — Template-based scaffold MCP server

### Blog posts & writeups
- https://medium.com/@montes.makes/lint-against-the-machine-a-field-guide-to-catching-ai-coding-agent-anti-patterns-3c4ef7baeb9e — Lint rules for AI anti-patterns
- https://medium.com/@gurudatt.sa26/stop-re-explaining-your-test-conventions-to-claude-use-skill-md-41a8a4d5d9ea — SKILL.md for test conventions
- https://dev.to/nishilbhave/claudemd-best-practices-the-complete-2026-guide-435j — CLAUDE.md best practices 2026
- https://alexop.dev/posts/custom-tdd-workflow-claude-code-vue/ — TDD workflow with shared test helpers
- https://addyosmani.com/blog/ai-coding-workflow/ — Context packing for AI coding
- https://dev.to/domizajac/is-your-repo-ready-for-the-ai-agents-revolution-checklist-1a1b — AI agent readiness checklist

### Research & industry analysis
- https://arxiv.org/abs/2604.19826 — Co-located tests receive 2.8-4.4x model attention (AIware 2026)
- https://www.gitclear.com/ai_assistant_code_quality_2025_research — Code duplication up 4x, reuse down 70%
- https://leaddev.com/ai/code-maintainability-plummets-in-the-ai-coding-era — Code reuse down 70%, duplication up 81%

### Community discussions
- https://github.com/orgs/community/discussions/197384 — Multi-layer enforcement consensus
- https://www.reddit.com/r/cursor/comments/1q9wmmu/ — "Cursor keeps reinventing your components"
- https://www.reddit.com/r/ExperiencedDevs/comments/1mg2r6y/ — "The era of AI slop cleanup"
- https://www.reddit.com/r/ClaudeCode/comments/1tb7edc/ — "Inherited a repo from a vibe engineer"

### Documentation & standards
- https://code.claude.com/docs/en/best-practices — Anthropic official best practices (subagents, instruction files)
