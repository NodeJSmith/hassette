---
topic: "Python framework lint and CI quality gate setup"
date: 2026-05-02
status: Draft
---

# Prior Art: Python Framework Lint & CI Quality Gates

## The Problem

Static analysis and CI checks are the automated quality floor — they catch regressions, security issues, and style drift before code reaches review. But the ecosystem moves fast: new tools emerge, existing tools gain rules, and the "standard" setup drifts. A project that was well-configured two years ago may now be missing checks that every peer framework runs. The question is: what are large Python async frameworks running that we aren't, and which gaps are worth closing?

## How We Do It Today

Hassette runs a solid baseline: ruff (16+ rule sets), pyright, flake8-async (ASYNC103/104 as of today), plus frontend linting (eslint, tsc). Pre-commit is two-tiered: fast checks at commit time, slow checks (pyright, schema validation, facade generation) at pre-push. CI runs tests across Python 3.11-3.13 with coverage, e2e via Playwright, system tests via Docker, and lint/type checking. Notable gaps: no security scanning (SAST or dependency audit), no spell checking, no CI workflow security linting, no slots validation, no documentation quality enforcement, and ruff's additional ASYNC rules (beyond 103/104) are not enabled.

## Patterns Found

### Pattern 1: GitHub Actions Security Linting (zizmor)

**Used by**: FastAPI, Pydantic, Trio, Django, Litestar (5/9 surveyed)
**How it works**: zizmor audits GitHub Actions workflow YAML for injection vulnerabilities, excessive permissions, unpinned actions, and credential exposure. Runs as a pre-commit hook on workflow file changes. Near-universal adoption in the Python ecosystem within one year.
**Strengths**: Catches a class of supply-chain vulnerabilities no other tool addresses. Low false-positive rate. Fast.
**Weaknesses**: Only covers GitHub Actions (not Azure DevOps, GitLab CI).
**Example**: https://github.com/fastapi/fastapi/blob/master/.pre-commit-config.yaml

### Pattern 2: Broader Async Linting via Ruff's ASYNC Rules

**Used by**: Any project enabling the ASYNC rule prefix in ruff
**How it works**: Ruff natively implements most flake8-async rules. Beyond ASYNC103/104 (which we now check via flake8-async), there are rules for: synchronous HTTP calls inside async functions (ASYNC210), synchronous file I/O in async functions (ASYNC230), `sleep(0)` instead of `checkpoint()` (ASYNC115), and more. These are already in ruff — just not enabled.
**Strengths**: Zero additional dependencies. Catches blocking calls in async code, a major source of performance issues.
**Weaknesses**: Some rules are opinionated; fast sync file reads may be intentional.
**Example**: https://flake8-async.readthedocs.io/

### Pattern 3: Dependency Health (pip-audit / deptry)

**Used by**: PyPA recommends pip-audit; deptry gaining traction
**How it works**: pip-audit queries the OSV database for known CVEs in installed packages. deptry cross-references imports against declared dependencies to catch unused deps, missing deps, and transitive dependency reliance. Both run as CI jobs.
**Strengths**: pip-audit is zero-config and catches known vulnerabilities. deptry prevents the "works because X installs it transitively" trap.
**Weaknesses**: pip-audit only catches *known* CVEs. deptry false-positives on conditional imports and plugin systems.
**Example**: https://deptry.com/usage/, https://github.com/pypa/pip-audit

### Pattern 4: Spell Checking (typos / codespell)

**Used by**: Trio (both), Litestar (typos), Pydantic (codespell), AnyIO (codespell)
**How it works**: typos (Rust-based) handles identifier names in camelCase/snake_case, catching typos in variable names. codespell focuses on natural language misspellings. Trio runs both for non-overlapping coverage; most projects pick one.
**Strengths**: typos catches `respnose_handler`; codespell catches "recieve" in docstrings. Both have auto-fix.
**Weaknesses**: Domain-specific terms need whitelisting. Running both adds config maintenance.
**Example**: https://github.com/python-trio/trio/blob/main/.pre-commit-config.yaml

### Pattern 5: Slots Validation (slotscheck)

**Used by**: Litestar (in CI)
**How it works**: Validates that `__slots__` inheritance is correct. A subclass that forgets `__slots__` when its parent uses them silently negates the memory optimization for all instances.
**Strengths**: Catches a silent performance regression that no other tool detects.
**Weaknesses**: Only relevant for projects using `__slots__`. Framework code with dynamic attributes needs exclusion lists.
**Example**: https://slotscheck.readthedocs.io/

### Pattern 6: Documentation Quality Enforcement

**Used by**: Pydantic (markdownlint-cli2), Django (blacken-docs), Litestar (sphinx-lint, docs-linkcheck)
**How it works**: blacken-docs formats code examples in Markdown/RST documentation to match the project's formatter output. markdownlint-cli2 enforces Markdown structure. docs-linkcheck validates all links in built documentation. Multiple tools used together.
**Strengths**: Catches broken code examples, dead links, and structural issues before users see them. blacken-docs is particularly valuable for docs with code examples.
**Weaknesses**: Requires choosing tools matched to docs format. Configuration overhead for custom dictionaries.
**Example**: https://github.com/django/django/blob/main/.pre-commit-config.yaml

### Pattern 7: Ruff's Bandit Rules (S prefix) Instead of Standalone Bandit

**Used by**: Implicit in any project using ruff with S rules enabled
**How it works**: Ruff natively implements most bandit SAST rules under the S rule prefix. Catches pickle deserialization, shell injection, insecure imports, hardcoded passwords, and more. No additional dependency needed.
**Strengths**: Already available in ruff. No false-positive overlap with a separate bandit run.
**Weaknesses**: Not 100% bandit coverage. For security-critical projects, semgrep offers deeper semantic analysis.
**Example**: https://docs.astral.sh/ruff/rules/#flake8-bandit-s

### Pattern 8: Commit Message Enforcement

**Used by**: Litestar (conventional-pre-commit)
**How it works**: Pre-commit hook validates commit messages follow Conventional Commits spec at commit time, not just at PR level. Ensures release-please and changelog generators work correctly.
**Strengths**: Catches malformed commit messages before they need amending. Pairs well with release-please.
**Weaknesses**: Frustrating for quick WIP commits.
**Example**: https://github.com/litestar-org/litestar/blob/main/.pre-commit-config.yaml

## Anti-Patterns

- **Running type checkers in pre-commit (not pre-push)**: mypy/pyright take 14+ seconds vs <2s for ruff. FastAPI and Litestar do this, but it slows commit cycles. Run type checkers at pre-push or CI only. Hassette already does this correctly.
- **Running standalone bandit alongside ruff**: Creates redundant findings. Enable ruff's S rules instead.
- **Ignoring CI workflow security**: Before zizmor, most projects had no security checks on their Actions files. Workflow injection is a real attack vector.
- **Using only codespell OR only typos**: They have non-overlapping coverage. If spell checking at all, typos alone gives the best single-tool coverage due to identifier awareness.

## Emerging Trends

- **ty (Astral's Rust type checker)**: 10-60x faster than mypy/pyright, ~15% spec conformance. FastAPI already runs it alongside mypy. Not ready as primary checker but worth watching.
- **Universal zizmor adoption**: Fastest adoption curve of any tool observed — 0 to 5/9 major projects in one year.
- **prek (Rust pre-commit replacement)**: Faster hook execution. Still early.

## Relevance to Us

**Already strong**: ruff config is thorough (16+ rule sets), pyright at pre-push, flake8-async for CancelledError, two-tier pre-commit, CI test matrix across 3 Python versions.

**Clear gaps worth closing** (ordered by impact/effort):

1. **zizmor** — near-zero effort, catches a real attack vector, universally adopted by peers. Add as pre-commit hook on `.github/` files.
2. **Ruff ASYNC rules (ASYNC100, 105, 109, 110, 115, 116)** — already in ruff, just not enabled. Enable them in `ruff.toml` select. We already have ASYNC103/104 via flake8-async.
3. **Ruff S rules (bandit)** — already in ruff, catches hardcoded secrets, shell injection, pickle deserialization. Enable in select.
4. **pip-audit in CI** — zero-config dependency vulnerability scanning. Add as a CI job.
5. **typos** — fast spell checker that catches identifier typos. Pre-commit hook.
6. **slotscheck** — hassette uses `__slots__` in Resource/Service hierarchies. Add as CI job.

**Worth considering but lower priority**:

7. **deptry** — dependency health. Good for catching transitive deps, but may need tuning for framework patterns.
8. **blacken-docs** — hassette has mkdocs with code examples. Ensures examples stay formatted.
9. **conventional-pre-commit** — hassette uses release-please + conventional commits. Would catch malformed messages at commit time instead of relying on PR title enforcement.

**Skip for now**:

- **ty** — too low conformance (~15%) to be useful yet. Revisit in 6 months.
- **Standalone bandit/semgrep** — ruff's S rules cover most of it. Not security-critical enough to warrant the overhead.
- **vulture/deadcode** — high false-positive rate with framework/registry patterns. Not worth the config burden.
- **markdownlint-cli2** — hassette's docs are primarily in mkdocs/Markdown but not at the scale where structural linting pays off yet.

## Recommendation

The top 3 are clear wins — zizmor, enabling existing ruff ASYNC rules, and enabling ruff's bandit (S) rules. All three are near-zero effort (config changes, not new dependencies) and close real gaps. pip-audit and typos are easy CI/pre-commit additions worth doing in the same pass. slotscheck is relevant given hassette's `__slots__` usage in core classes but is lower urgency.

## Sources

### Reference implementations
- https://github.com/fastapi/fastapi/blob/master/.pre-commit-config.yaml — FastAPI pre-commit (ruff, mypy, ty, zizmor)
- https://github.com/pydantic/pydantic/blob/main/.pre-commit-config.yaml — Pydantic pre-commit (codespell, markdownlint, yamlfmt, zizmor, pyright)
- https://github.com/litestar-org/litestar/blob/main/.pre-commit-config.yaml — Litestar pre-commit (typos, slotscheck, conventional-pre-commit, flake8-dunder-all)
- https://github.com/litestar-org/litestar/blob/main/.github/workflows/ci.yml — Litestar CI (mypy, pyright, slotscheck parallel jobs)
- https://github.com/agronholm/anyio/blob/master/.pre-commit-config.yaml — AnyIO pre-commit (codespell, pygrep-hooks)
- https://github.com/python-trio/trio/blob/main/.pre-commit-config.yaml — Trio pre-commit (codespell + typos, zizmor)
- https://github.com/django/django/blob/main/.pre-commit-config.yaml — Django pre-commit (blacken-docs, zizmor, biome)
- https://github.com/encode/httpx/blob/master/scripts/lint — HTTPX (minimalist: ruff only)

### Blog posts & writeups
- https://gatlenculp.medium.com/effortless-code-quality-the-ultimate-pre-commit-hooks-guide-for-2025-57ca501d9835 — Comprehensive pre-commit hooks guide 2025
- https://medium.com/@sparknp1/10-bandit-pip-audit-safeguards-for-secure-python-builds-f4860a1c0771 — Bandit and pip-audit for secure Python builds
- https://semgrep.dev/blog/2021/python-static-analysis-comparison-bandit-semgrep/ — Semgrep vs Bandit comparison

### Documentation & standards
- https://flake8-async.readthedocs.io/ — flake8-async rules documentation
- https://slotscheck.readthedocs.io/ — slotscheck documentation
- https://deptry.com/usage/ — deptry dependency health checker
- https://learn.scientific-python.org/development/guides/style/ — Scientific Python style guide
- https://astral.sh/blog/ty — ty type checker announcement
- https://docs.astral.sh/ruff/rules/#flake8-bandit-s — ruff bandit rules reference
