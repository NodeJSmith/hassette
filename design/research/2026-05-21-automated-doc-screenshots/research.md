---
topic: "automated-doc-screenshots"
date: 2026-05-21
status: Draft
---

# Prior Art: Automated Screenshot Capture for Documentation

## The Problem

Documentation screenshots go stale. When the UI changes — new layout, updated theme, added features — screenshots must be recaptured manually. The real cost isn't the capture itself, it's remembering to do it and getting the state right each time. Jenkins, Appsmith, and other large projects have filed issues about this exact problem.

For hassette specifically, this will happen frequently: the docs site is being refreshed to match the new UI, and ongoing UI improvements mean screenshots need updating regularly. A manual workflow (start demo, navigate pages, screenshot, crop, save) doesn't scale.

## How We Do It Today

Fully manual. 12 PNG files live in `docs/_static/`, referenced via relative Markdown paths. Screenshots are captured interactively using the Playwright MCP tools during conversations and committed to git. The demo environment (`scripts/hassette_demo.py`) provides deterministic seed data, and Playwright is already in dev deps for e2e tests — but nothing wires these together for automated capture.

## Patterns Found

### Pattern 1: YAML-Manifest Screenshot Capture

**Used by**: shot-scraper (Simon Willison), Heroshot, various custom implementations

**How it works**: Screenshots are defined in a YAML manifest that lives alongside the docs. Each entry specifies a URL, output path, viewport dimensions, and optional pre-capture actions (click elements, fill forms, execute JavaScript). A CLI tool reads the manifest and uses Playwright to capture each screenshot. Adding a new screenshot means adding a YAML entry and referencing the output path in Markdown.

CI integration is straightforward: run the tool as a build step, committing results back or publishing as artifacts. shot-scraper provides a GitHub Actions template; Heroshot provides similar workflows.

**Strengths**: Declarative and readable. Non-developers can add screenshots by editing YAML. Separates capture config from implementation. Easy to review in PRs — a new YAML entry is self-documenting. Deterministic when combined with seed data.

**Weaknesses**: CSS selectors for element cropping are fragile and break when DOM structure changes. Pre-capture actions can become complex for multi-step UI states, essentially recreating e2e tests in YAML. No built-in mechanism to detect stale vs. intentionally changed screenshots.

**Example**: https://github.com/simonw/shot-scraper, https://github.com/omachala/heroshot

### Pattern 2: Build-Integrated Screenshot Generation

**Used by**: Jelly (James Adam / interblah.net)

**How it works**: Screenshot capture is part of the docs build pipeline, not a separate step. Building docs spins up the app, navigates to each page, captures screenshots, and writes them to the output directory. Screenshots are derived content — regenerated from the app, not maintained as static assets.

The key reported outcome: after building this system, documentation was updated "far more often" because friction dropped. Change the UI, run the build, commit results.

**Strengths**: Zero-friction updates — screenshots update as a side effect of building docs. Impossible for screenshots to drift. Co-locates documentation and development workflows.

**Weaknesses**: Requires the app to be runnable during docs build (Docker, dependencies, etc.). Build times increase. Not suitable for docs-only hosting without app access.

**Example**: https://interblah.net/self-updating-screenshots

### Pattern 3: CI-Triggered Screenshot Refresh with PR Review

**Used by**: Appsmith (20k+ stars)

**How it works**: A CI workflow runs on schedule or on push to main. It starts the app with seed data, captures all screenshots via manifest, and diffs against committed versions. If anything changed, it opens a PR with updated screenshots for human review.

Critical detail: commit messages must include `[skip ci]` to prevent infinite loops.

**Strengths**: Human review catches unintentional changes. Screenshots are versioned and diffable. Doesn't affect docs build times.

**Weaknesses**: Delayed feedback — screenshots update asynchronously. PR review adds overhead. Image diffs in GitHub are functional but not great for subtle changes. Risk of screenshot PRs being ignored.

**Example**: https://github.com/appsmithorg/appsmith/pull/38243

### Pattern 4: Visual Picker + Config Generation

**Used by**: Heroshot

**How it works**: Instead of writing CSS selectors manually, a visual picker opens an interactive browser overlay where you click on the element to capture. The tool generates the selector and config automatically. Subsequent runs use `heroshot capture` headlessly.

Also supports: automatic light/dark mode variants, multiple viewport sizes, element hiding (cookie banners, timestamps), and in-browser annotations (arrows, callouts) baked into the screenshot.

**Strengths**: Eliminates fragile-selector problem. Annotations solve "I need an arrow pointing to this button" without image editors. Multi-variant generation from single config. Accessible to non-technical contributors.

**Weaknesses**: Requires interactive browser session for setup. Relatively new tool (2026). Generated selectors may still break on major DOM restructuring.

**Example**: https://heroshot.sh/, https://github.com/omachala/heroshot

### Pattern 5: Seed Data + Demo Mode (Prerequisite Pattern)

**Used by**: Implicit across all approaches above

**How it works**: The app starts with a fixed dataset producing known, repeatable UI state. This eliminates non-determinism from live data. For projects with a demo mode already built, this requires minimal additional work.

Implementation includes: database fixtures, optional clock mocking for relative timestamps, disabled animations, and hidden dynamic content (notification badges, "last seen" text).

**Strengths**: Deterministic output enables meaningful diffs. Seed data can cover specific states (empty, error, full). Reuses existing demo infrastructure.

**Weaknesses**: Seed data must be maintained alongside the UI. Time-dependent UI needs clock mocking. Animations must be disabled.

**Example**: [no source found — implicit across multiple approaches]

## Anti-Patterns

- **Bespoke Playwright scripts per screenshot**: Starts as "just one script" and becomes 14+ over two months, each handling different interactions. Config-driven approaches scale better. ([source](https://dev.to/omachala/you-wrote-14-playwright-scripts-just-to-screenshot-your-own-app-2ckf))

- **Conflating doc screenshots with visual regression testing**: Visual regression tests *fail* on any pixel diff. Doc screenshots should *update* when the UI changes. Using a regression framework for doc screenshots creates false failures on every UI change. ([source](https://dev.to/ericwoooo_kr/self-updating-screenshots-in-your-docs-how-to-stop-doing-it-by-hand-2bbd))

- **Ignoring font loading in CI**: Playwright's `page.screenshot()` can hang when custom fonts load slowly. The `PW_TEST_SCREENSHOT_NO_FONTS_ENVIRONMENT` variable fixes this but is non-obvious. ([source](https://momentic.ai/blog/playwright-pitfalls))

- **Screenshot commits triggering CI loops**: Automated screenshot commits can trigger another workflow run, creating infinite loops. Fix with `[skip ci]` or conditional checks on commit author.

## Relevance to Us

Hassette is well-positioned for this. The hard prerequisites are already in place:

1. **Playwright** — already in dev deps for e2e tests
2. **Demo mode** — `hassette_demo.py` provides deterministic seed data with real HA container + hassette + frontend
3. **E2E fixtures** — `tests/e2e/conftest.py` has viewport constants, mock data, and live server setup
4. **MkDocs** — images referenced via simple relative paths, no special plugin needed

The gap is the automation layer connecting these pieces. Currently screenshots are captured interactively (Playwright MCP in conversation) and committed manually.

The YAML-manifest pattern (Pattern 1) aligns best with the existing setup — it's Python/Playwright-based, doesn't require restructuring the docs build, and provides a declarative manifest that's easy to review and extend. shot-scraper is the most mature option and could use the existing demo environment as its target.

The build-integrated pattern (Pattern 2) is aspirational but may be overkill given that hassette already has a working demo startup — a script that starts the demo, captures from manifest, and stops is simpler than wiring screenshot capture into `mkdocs build`.

## Recommendation

**shot-scraper** (or a similar YAML-manifest approach) is the natural starting point. It's Python, Playwright-powered, pip-installable, and designed for exactly this use case. The workflow would be:

1. Add a `screenshots.yml` manifest defining all doc screenshots (URL, viewport, selector/crop, pre-capture JS)
2. Write a wrapper script that starts the demo, runs `shot-scraper multi screenshots.yml`, and stops the demo
3. Optionally add a CI workflow to refresh screenshots on schedule and open a PR

**Heroshot** is worth evaluating if annotation support matters (arrows/callouts on screenshots), but it's newer and less battle-tested.

The anti-pattern to avoid is writing custom Playwright scripts per screenshot — config-driven approaches scale dramatically better.

## Sources

### Reference implementations
- https://github.com/simonw/shot-scraper — YAML-manifest Playwright screenshot tool (Python)
- https://github.com/omachala/heroshot — visual picker + config-driven screenshot tool with annotations
- https://github.com/appsmithorg/appsmith/pull/38243 — CI screenshot automation retrofit
- https://github.com/trion-development/screen-capture-puppeteer-playwright — starter template

### Blog posts & writeups
- https://simonwillison.net/2022/Mar/10/shot-scraper/ — shot-scraper announcement and design rationale
- https://interblah.net/self-updating-screenshots — build-integrated screenshots for Jelly
- https://dev.to/ericwoooo_kr/self-updating-screenshots-in-your-docs-how-to-stop-doing-it-by-hand-2bbd — doc screenshots vs visual regression
- https://dev.to/omachala/you-wrote-14-playwright-scripts-just-to-screenshot-your-own-app-2ckf — anti-pattern analysis
- https://momentic.ai/blog/playwright-pitfalls — font loading and CI gotchas
- https://www.lirantal.com/blog/advanced-usage-patterns-for-taking-page-element-screenshots-with-playwright — element-level screenshot patterns
- https://dev.to/debs_obrien/automate-your-screenshot-documentation-with-playwright-mcp-3gk4 — Playwright MCP for doc screenshots

### Documentation & standards
- https://heroshot.sh/ — Heroshot documentation
- https://blog.jetbrains.com/writerside/2022/01/the-holy-grail-of-always-up-to-date-documentation/ — JetBrains on docs freshness

### Community discussion
- https://news.ycombinator.com/item?id=47908051 — HN thread on self-updating screenshots
- https://github.com/jenkins-infra/jenkins.io/issues/7526 — Jenkins screenshot staleness issue
