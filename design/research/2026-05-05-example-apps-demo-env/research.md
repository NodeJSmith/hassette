---
topic: "Example apps and demo environments in automation frameworks"
date: 2026-05-05
status: Draft
---

# Prior Art: Example Apps and Demo Environments in Automation Frameworks

## The Problem

Automation frameworks that depend on external services (like Home Assistant) face a bootstrapping problem: users can't try the framework without first setting up the external dependency. This creates friction for new users, makes visual QA difficult, and makes demo environments fragile. The question is where examples should live (monorepo vs separate repo), how they should be run, and how the full stack (framework + examples + external dependencies) should be composed for development and testing.

## How We Do It Today

Hassette maintains **both patterns** — an in-repo `examples/` directory with 7 sample apps and Docker Compose setup, plus a separate `hassette-examples` repo intended as a standalone demo for end users. System tests already spin up a real HA container via Docker Compose with pre-seeded config and a static JWT token, and the frontend dev server proxies to the backend on `:8126`. The infrastructure for a one-command demo exists in pieces but isn't composed into a single entry point.

## Patterns Found

### Pattern 1: In-Repo Examples Directory (Tested)

**Used by**: Flask, AppDaemon (untested variant), Node-RED (per-node examples), ESPHome (test configs)

**How it works**: The framework maintains an `examples/` directory versioned alongside the framework code. Each example is self-contained with its own README and config. Flask's approach is the gold standard: `examples/tutorial` is a complete installable app whose tests run as part of the main CI suite. AppDaemon has ~28 examples but doesn't test them, so they drift.

The critical differentiator is whether examples are tested in CI. Untested in-repo examples are worse than no examples — they look maintained but silently break.

**Strengths**: Examples always match the current branch. Single PR for "feature + example." Version skew is impossible. Refactoring tools catch example breakage.

**Weaknesses**: Adds to repo size and CI time. Without CI testing, creates a false sense of correctness. Large example apps can distract from core framework review.

**Example**: https://github.com/pallets/flask/tree/main/examples

### Pattern 2: Docs-as-Tests (Tested Documentation Snippets)

**Used by**: FastAPI (`docs_src/`), pytest, Click, Rust crates (doctests)

**How it works**: Code examples live in a `docs_src/` directory. The documentation system includes these files directly — the rendered docs page pulls from the actual source file. CI runs tests against these files, so stale docs break the build. FastAPI is the exemplar: every tutorial page corresponds to tested source files.

This is distinct from Pattern 1 — these are small focused snippets that prove the docs work, not complete apps.

**Strengths**: Documentation never goes stale. Catches breaking changes immediately. Low maintenance overhead once set up.

**Weaknesses**: Snippets aren't complete apps — users still need project structure guidance. Not suitable for complex multi-file examples.

**Example**: https://github.com/fastapi/fastapi (`docs_src/` directory)

### Pattern 3: Separate Template/Starter Repository

**Used by**: Homebridge (plugin template), Cookiecutter Django, FastAPI (full-stack template), create-react-app

**How it works**: A separate repo (or generator) scaffolds a new project with all the wiring in place. Users clone/generate the template, not the framework. Homebridge's plugin template includes TypeScript config, a debug launcher with auto-restart, and VS Code settings. Clone, `npm install`, `npm run watch` — running immediately.

**Strengths**: Clean separation between framework and user code. Users start with a working project. Can include opinionated tooling without burdening the framework repo.

**Weaknesses**: Templates drift from the framework if not actively tested against HEAD. Two repos to keep in sync. Updates don't reach existing projects.

**Example**: https://github.com/homebridge/homebridge-plugin-template

### Pattern 4: Demo Component / Fake Data Generator

**Used by**: ESPHome (`demo` component), Storybook (stories as demos), Home Assistant (`demo` integration)

**How it works**: The framework includes a built-in component that generates realistic fake data for development and UI testing. ESPHome's `demo` platform creates synthetic sensor readings, light states, etc. without real hardware. HA's own `demo` integration populates the UI with sample entities. Hassette's system tests already use HA's `demo:` integration in the fixture config.

This pattern is specifically designed for visual QA. Storybook extends it — each "story" serves triple duty as documentation, visual regression baseline, and interactive demo.

**Strengths**: Zero external dependencies for UI development. Deterministic data for visual regression testing. Works in CI without real hardware.

**Weaknesses**: Demo data can diverge from real data shapes. Risk of testing against data that hides real-world issues.

**Example**: https://esphome.io/components/demo/

### Pattern 5: Docker Compose Dev Environment with Real Dependencies

**Used by**: node-red-contrib-home-assistant, Testcontainers ecosystem, many microservice frameworks

**How it works**: A `docker-compose.yml` defines all external dependencies. For HA integrations: `docker-compose up` starts both the framework and HA pre-configured with test entities. node-red-contrib-home-assistant exemplifies this — one command, both services, wired together.

Hassette's system tests already implement this pattern (`tests/system/docker-compose.yml`), but it's not exposed as a developer-facing demo environment.

**Strengths**: Tests against real dependencies. Catches integration issues mocks miss. "One command" experience. Reproducible across machines.

**Weaknesses**: Requires Docker. HA containers are large and slow to start (~5-20s). Port binding assumptions. Network flakiness in CI.

**Example**: node-red-contrib-home-assistant docker-compose setup

## Anti-Patterns

- **Untested in-repo examples (AppDaemon)**: 28 examples that aren't CI-tested. Users waste time debugging framework drift vs. their own mistakes. Worse than no examples. Source: https://github.com/AppDaemon/appdaemon/tree/dev/conf/example_apps

- **Requiring a live external service with no alternative (AppDaemon Docker)**: Need a real HA + token before you can even try the framework. Chicken-and-egg problem for new users. Source: https://appdaemon.readthedocs.io/en/latest/DOCKER_TUTORIAL.html

- **Separate example repo that drifts from main**: Breaking changes in the framework don't fail the example repo's CI unless there's explicit cross-repo testing. The template works when created but becomes stale.

- **Conflating documentation snippets with runnable examples**: Code in docs that looks complete but requires surrounding context. Copy-paste fails erode trust.

## Emerging Trends

- **"Example IS the test" (Storybook/Chromatic)**: Component examples double as visual regression test inputs. One artifact, two purposes.

- **Demo/sandbox components as first-class framework features**: ESPHome and HA show a trend toward built-in demo modes that generate realistic test data without real hardware.

## Relevance to Us

Hassette is currently split across Pattern 1 (in-repo `examples/`) and Pattern 3 (separate `hassette-examples` repo), but neither is fully realized:

- The in-repo examples exist but aren't tested against the framework in CI
- The separate repo provides a user-facing demo but drifts from framework HEAD and has zero tests
- System tests already implement Pattern 5 (Docker Compose with real HA) but it's not exposed as a developer tool
- HA's `demo` integration (Pattern 4) is already used in test fixtures but not leveraged for interactive development

The biggest gap is the **drift risk** of the separate repo — the exact anti-pattern documented across multiple frameworks. The strongest pattern for hassette's situation is a combination:

1. **Bring examples in-repo and test them** (Pattern 1, Flask-style) — eliminates drift
2. **Reuse the system test HA infrastructure** (Pattern 5) — already built, just needs a developer-facing entry point
3. **The separate repo becomes optional** — either archived, or repurposed as a "getting started from scratch" template (Pattern 3) that scaffolds against the published framework, not the dev branch

## Recommendation

**Bring `hassette-examples` into the main repo.** The prior art strongly favors in-repo examples when:
- The framework is pre-1.0 and changing rapidly (drift risk is highest)
- Examples need to be tested against the current branch (not a published release)
- The demo environment depends on framework internals (test fixtures, docker-compose patterns)

The separate repo pattern works well for stable frameworks where examples target published releases (Cookiecutter Django, Homebridge template). Hassette isn't there yet — the API is still evolving, and having examples in-repo means a single PR can update both framework and examples.

The in-repo examples should be **tested in CI** (Flask pattern, not AppDaemon pattern). At minimum, import-test them; ideally, run them against the system test HA container.

For the visual QA environment (issue #695), compose the existing pieces: system test HA container + in-repo example apps + frontend dev server, exposed as a nox session or mise task. This is Pattern 5, and most of the infrastructure already exists.

Coverage note: Research was solid across the HA ecosystem and major Python frameworks. Less coverage of non-Python automation frameworks (Ansible, Terraform) which may have additional patterns.

## Sources

### Reference implementations
- https://github.com/pallets/flask/tree/main/examples — Flask in-repo examples (tested, curated)
- https://github.com/fastapi/full-stack-fastapi-template — FastAPI full-stack template (separate repo)
- https://github.com/AppDaemon/appdaemon/tree/dev/conf/example_apps — AppDaemon examples (untested)
- https://github.com/custom-components/pyscript — Pyscript monorepo structure
- https://github.com/homebridge/homebridge-plugin-template — Homebridge plugin template repo
- https://github.com/cookiecutter/cookiecutter-django — Django project generator

### Blog posts & writeups
- https://shipyard.build/blog/docker-compose-test-environments/ — Docker Compose test environments
- https://www.tweag.io/blog/2023-04-04-python-monorepo-1/ — Python monorepo structure
- https://sqr-075.lsst.io/ — LSST vertical monorepo for FastAPI

### Documentation & standards
- https://fastapi.tiangolo.com/tutorial/bigger-applications/ — FastAPI docs-as-tests
- https://esphome.io/components/demo/ — ESPHome demo component
- https://nodered.org/docs/creating-nodes/examples — Node-RED example conventions
- https://appdaemon.readthedocs.io/en/latest/DOCKER_TUTORIAL.html — AppDaemon Docker tutorial
- https://www.chromatic.com/storybook — Storybook visual QA
- https://testcontainers.com/ — Testcontainers
