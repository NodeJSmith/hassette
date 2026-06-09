# Design: Documentation Overhaul

**Date:** 2026-06-01
**Status:** archived
**Scope-mode:** hold
**Research:** design/specs/070-doc-overhaul/brief.md

## Problem

The 76 hand-written documentation pages grew organically over months. Voice-guide.md and doc-rules.md define mature standards, but adherence varies widely: recipes and getting-started are closest to the target voice, core-concepts and advanced are furthest. The reader cost is concrete: dependency injection is explained in three places at contradictory depth, so readers get different answers depending on where they land. Web UI docs organized by tab name mean a reader searching "how do I debug a handler?" can't find it. State customization is buried in "Advanced" instead of next to the States concept page where readers look first. The Architecture page mixes app-author and contributor audiences. Patching individual pages won't fix structural rot. A blank-slate rewrite with a planned structure is the faster path to consistent, reader-serving documentation.

## Goals

Each section is evaluated against concrete reader outcomes:

- **Getting Started:** A new user installs Hassette, connects to Home Assistant, deploys a working app, and verifies it connected — without external help.
- **Core Concepts:** A reader can explain what Bus, Scheduler, Api, StateManager, and Cache do and when to use each, without looking it up.
- **Recipes:** A reader can adapt example code to their own entities and verify the automation fired.
- **CLI:** A reader can find and run any CLI command for their task.
- **Testing:** A reader can write and run a test for their app using the harness.
- **Web UI:** A reader can use the web UI to debug a failing handler or check app status.
- **Migration:** An AppDaemon user can map their existing automation to the Hassette equivalent.

## Non-Goals

- API reference auto-generation (`tools/docs/gen_ref_pages.py`) — Phase 1 reviews which modules are in `PUBLIC_MODULES` but does not rewrite the generator
- Source code docstrings — separate concern from the docs site
- Design documents in `design/` — not part of the docs site
- Frontend/CSS/design system changes
- New documentation for features that don't exist yet
- Docs CI improvements beyond what's needed to validate the rewrite

## User Scenarios

### Evaluator: Considering Hassette for their HA automations

- **Goal:** Determine whether Hassette fits their needs
- **Context:** Comparing Hassette to AppDaemon, HA YAML automations, or pyscript

#### Quick Assessment

1. **Lands on home page or Getting Started**
   - Sees: What Hassette is, who it's for, how it compares
   - Decides: Whether to invest time in the quickstart
   - Then: Follows quickstart or leaves

#### Deeper Evaluation

1. **Reads Architecture overview**
   - Sees: The "five handles" model (Bus, Scheduler, Api, StateManager, Cache), how apps work
   - Decides: Whether the programming model fits their mental model
   - Then: Skims recipes to see real-world usage

### New User: Building their first automation

- **Goal:** Install Hassette, connect to HA, write and deploy a working app
- **Context:** Has a Home Assistant instance, knows Python, new to Hassette

#### First App

1. **Follows Quickstart**
   - Sees: Installation commands, configuration steps, connection setup
   - Decides: Nothing — follows prescribed steps
   - Then: Has a running Hassette instance connected to HA
2. **Follows First Automation**
   - Sees: A complete app with config, handler registration, and DI
   - Decides: Which entity to subscribe to
   - Then: Deploys the app and verifies it fires via `hassette log`
3. **Adapts a recipe**
   - Sees: Full app code, how-it-works walkthrough, variations
   - Decides: Which recipe matches their use case, what to customize
   - Then: Deploys the adapted recipe and verifies via the prescribed verification step

### Active Developer: Extending their automation suite

- **Goal:** Look up specific API behavior, debug issues, use advanced features
- **Context:** Has working Hassette apps, needs reference and depth

#### Debugging a Handler

1. **Opens Web UI docs**
   - Sees: Task-oriented guidance for "debug a failing handler"
   - Decides: Which tool to use (web UI handlers page, logs, CLI)
   - Then: Identifies the issue through handler invocation history or logs

#### Using a New Feature

1. **Reads concept page for the feature**
   - Sees: What it does, minimal example, common patterns
   - Decides: Whether and how to apply it
   - Then: Scrolls to depth content or follows links to sibling pages

#### Can't Find the Right Page

1. **Searches for a topic (e.g., "dependency injection" or "DI")**
   - Sees: Single canonical result, not three contradictory pages at different depths
   - Decides: Whether this is the right page
   - Then: Reads the canonical page
2. **If search fails, browses the nav**
   - Sees: Task-oriented section titles that match what they're trying to do
   - Decides: Which section to explore
   - Then: Finds the content within 2-3 clicks from the top-level nav

## Functional Requirements

- **FR#1:** Every hand-written page conforms to the voice-guide.md style rules, verifiable via the voice audit checklist
- **FR#2:** Concept and API reference pages use system-as-subject voice — no "you" outside getting-started and recipe procedure sections
- **FR#3:** Getting-started pages use direct "you" address with code-first ordering
- **FR#4:** Every recipe includes a "Verify it's working" step with concrete verification commands (`hassette log --app <key>` or web UI Handlers tab)
- **FR#5:** Dependency injection has a single canonical documentation page at `core-concepts/bus/dependency-injection.md`; all other pages that reference DI compress to one sentence with a link
- **FR#6:** When any page uses `D.*`, `states.*`, `C.*`, `P.*`, or `A.*` for the first time, it links to the canonical page for that module
- **FR#7:** The Web UI docs section contains at most 6 pages organized by user task, not by UI element. Candidate task pages: debugging a failing handler, reading logs, managing apps (start/stop/reload/health). Phase 1 refines this list but must justify each page as a discrete user task
- **FR#8:** The "Advanced" section no longer exists in the `mkdocs.yml` nav
- **FR#9:** The States subsection under `core-concepts/states/` has depth pages matching the Bus pattern: overview, plus at minimum a "Subscribing to State Changes" page and a "DomainStates Reference" page. Custom States, State Registry, and Type Registry also reside here as extension pages
- **FR#10:** An "Operating Hassette" section exists in the nav for operational how-to content: Log Level Tuning, Upgrading Hassette (extracted from current Troubleshooting), and operational runbook content. Troubleshooting remains pure symptom-lookup
- **FR#11:** The Architecture page addresses app-authors only — the "five handles" model (Bus, Scheduler, Api, StateManager, Cache)
- **FR#12:** Contributor/maintainer content (dependency graphs, wave ordering, cycle detection, internal service names) resides in `internals.md`
- **FR#13:** Every snippet file in `docs/pages/*/snippets/` is referenced by at least one page via `--8<--` include
- **FR#14:** Every code example in a page comes from a CI-tested snippet file — no inline code blocks for examples
- **FR#15:** Troubleshooting and operational pages preserve all named failure modes, log signatures, timing values, and runbook commands from their predecessors
- **FR#16:** The Managing Helpers page has consistent nav placement and filesystem location (currently in `pages/advanced/` but rendered under Core Concepts > API)
- **FR#17:** Each page that introduces Hassette-specific terms (Bus, Scheduler, Api, Cache, App, StateManager, Resource) defines them functionally on first use within the page
- **FR#18:** The Getting Started section includes a dedicated evaluator-facing page covering what Hassette is, who it's for, and how it compares to AppDaemon, HA YAML automations, and pyscript

## Edge Cases

- **Snippet sequencing:** `pymdownx.snippets` has `check_paths: true` — any `--8<--` reference to a non-existent file fails the build. Pages and snippets must be created together. Mitigation: create snippet files as minimal stubs before adding references; stubs satisfy `check_paths` and Pyright.
- **Cross-link breakage:** Pages reference each other heavily. Phase 1 mitigates this by creating stub files for every page in the new tree alongside the nav — stubs satisfy `mkdocs build --strict` and the link checker even before content is written. Section PRs replace stubs with real content; `--strict` stays green throughout.
- **Knowledge loss on blank-slate operational pages:** Troubleshooting pages contain log signatures, timing values, and runbook commands that exist nowhere else in the codebase. FR#15 guards against this with the mandatory pre-write knowledge inventory.
- **Voice drift across sessions:** 76 pages written across many sessions risk gradual voice drift. The three exemplar pages plus per-section voice audit checklist guard against this. `docs-context.md` consolidates exemplar paths, the full checklist, and common violation patterns into a single calibration artifact read at the start of each writing session.
- **Regression on already-good pages:** Some recipes and getting-started pages are already close to the voice standard. Starting blank risks producing pages that are worse in spots. The exemplar + voice audit process guards against this, but requires discipline.

## Acceptance Criteria

- **AC#1:** All rewritten pages pass the voice audit checklist (5-10 items drawn from the most commonly violated voice-guide rules) — FR#1, FR#2, FR#3
- **AC#2:** `mkdocs build --strict` succeeds with zero warnings on the final docs branch
- **AC#3:** Post-build link checker (new CI job) finds zero broken links, including anchor fragments
- **AC#4:** Pyright passes on all snippet files under `docs/pyrightconfig.json`
- **AC#5:** No snippet file exists under `docs/pages/*/snippets/` that isn't referenced by at least one page — FR#13
- **AC#6:** The Getting Started section includes a step where the reader runs `hassette status` and sees `websocket_connected: True`, and a step where they run `hassette app` and see their app listed as running — reader outcome
- **AC#7:** Each recipe's "Verify it's working" step names a concrete command or UI action that produces observable output — FR#4
- **AC#8:** `mkdocs.yml` nav contains no "Advanced" section — FR#8
- **AC#9:** `core-concepts/bus/dependency-injection.md` is the only page with a full DI explanation; grep of other pages shows only one-sentence references with links — FR#5
- **AC#10:** Web UI docs section in `mkdocs.yml` contains ≤6 pages with task-oriented titles, not tab names — FR#7
- **AC#11:** The States subsection in `mkdocs.yml` has an overview, at least two depth pages (state change subscriptions, DomainStates reference), plus Custom States, State Registry, and Type Registry as extension pages — FR#9
- **AC#12:** Every page that uses `D.*`, `states.*`, `C.*`, `P.*`, or `A.*` links to the canonical page for that module on first use — FR#6
- **AC#13:** An "Operating Hassette" section exists in `mkdocs.yml` containing Log Level Tuning and Upgrading content; Troubleshooting contains only symptom-lookup entries — FR#10
- **AC#14:** The Architecture page (`core-concepts/index.md`) does not mention dependency graphs, wave ordering, cycle detection, or internal service names — FR#11
- **AC#15:** `internals.md` contains dependency graphs, wave ordering, cycle detection, and internal service names — FR#12
- **AC#16:** No page contains an inline code example (fenced code block for a Hassette code example) that isn't sourced from a snippet file via `--8<--` — FR#14
- **AC#17:** Troubleshooting page preserves every named failure mode and log signature from the current version (verified by pre-write knowledge inventory diff) — FR#15
- **AC#18:** Managing Helpers page filesystem path matches its nav position under Core Concepts > API — FR#16
- **AC#19:** Every page's first use of Bus, Scheduler, Api, Cache, App, StateManager, or Resource includes a functional definition — FR#17
- **AC#20:** Getting Started section in `mkdocs.yml` includes a dedicated evaluator page (e.g., "Is Hassette Right for You?") — FR#18

## Key Constraints

- Snippet files use `--8<--` includes with `check_paths: true` — pages and their snippets must exist simultaneously or the build breaks. No half-created states.
- The voice-guide.md 22-rule set and doc-rules.md page templates are the authoritative standards. The rewrite conforms to them; it does not revise them.
- `mkdocs build --strict` must pass on every section PR to the docs branch. Phase 1 creates stub files for all pages in the new tree so cross-links resolve from the start; section PRs replace stubs with real content.

## Dependencies and Assumptions

- **mkdocs and plugins** (search, glightbox, panzoom, gen-files, literate-nav, autorefs, mkdocstrings) — all stay as-is; the rewrite is content, not tooling
- **Pyright CI** — snippet type-checking continues using `docs/pyrightconfig.json`
- **CSS checker scripts** (`tools/check_global_css_allowlist.py`, etc.) — no interaction with docs content
- **Assumption:** Issue #540 ("final docs sweep before v1.0.0") is superseded by this issue and should be closed when work begins
- **Assumption:** The current 258 snippet files will be largely replaced — the Phase 2 audit determines which survive

## Architecture

The three-phase approach optimizes for structural consistency and voice coherence — everything is planned before anything is written. The trade-off is speed: outlining 76 pages before writing any of them delays visible progress and increases the risk of scope fatigue across the writing phase.

### Three-Phase Process

**Phase 1: Site Outline** — The most consequential phase. Deliverables:
- Restructured page tree and `mkdocs.yml` nav with stub files for every page (title + placeholder line) — stubs keep `mkdocs build --strict` green from the start
- Structural changes: eliminate "Advanced" (rehome content), restructure Web UI (task-oriented), scope Architecture (app-author only), fix Managing Helpers placement, designate DI canonical home
- Decision on Migration section page count: keep at 8 pages or condense to fewer (section stays — drop is off the table)
- Three exemplar page selections with criteria from the brief: concept exemplar must (a) introduce multiple related terms, (b) send readers to sibling depth pages, (c) have a clear new-reader audience; recipe/getting-started exemplar must demonstrate the prose "How It Works" pattern; reference exemplar must demonstrate terse/tabular voice distinct from concept pages
- Voice audit checklist (5-10 items from the most commonly violated voice-guide rules)
- `docs-context.md` in the spec directory — the single calibration artifact for writing sessions. Contains: paths to all three exemplar pages, the full voice audit checklist inline (not referenced), and the 3 most common voice violations found in the current docs
- Decision on whether to review `PUBLIC_MODULES` in `gen_ref_pages.py`

**Phase 2: Per-Page Content Outlines** — For each page in the Phase 1 tree:
- Section headings with 1-2 sentence descriptions of content
- Snippet inventory: what code examples the page needs (named, not just counted)
- Mapping of unclaimed existing snippets → keep or kill
- For troubleshooting/operational pages: knowledge inventory extracted from current pages (log signatures, timing values, runbook commands)

**Phase 3: Section-by-Section Writing** — For each section (approximately 8 section PRs):
- Write pages from blank with the Phase 2 outline as guide
- Create snippet files (stub-first to satisfy `check_paths`, then fill content)
- Voice audit against the checklist before the section PR
- Rebase docs branch onto main after each section PR merges

### Branch Strategy

```
main ← docs ← section-pr-1, section-pr-2, ...
```

Section PRs merge to the long-lived `docs` branch. One big PR from `docs` to `main` when all sections are complete. Users see an atomic swap; review happens incrementally. After each section PR merges, rebase `docs` onto current `main` and run CI — eight section PRs = eight opportunities to catch API drift.

### Exemplar Pages

Three pages are written and reviewed before bulk writing begins:
1. **Concept exemplar** — hardest voice (system-as-subject, no "you"). Strong candidate: Bus overview. Must introduce multiple related terms, send readers to sibling depth pages.
2. **Getting-started or recipe exemplar** — friendlier register. Strong candidate: First Automation or Motion Lights. Must demonstrate the prose "How It Works" pattern from voice-guide.md.
3. **Reference exemplar** — terse functional definitions, tables before prose, no narrative arc. Strong candidate: DI annotations page or CLI command reference. Must demonstrate the reference-mode voice distinct from concept pages.

Before using any candidate as an exemplar, verify it passes the voice audit checklist — remediate first if it does not. These anchor voice for everything that follows. Selection happens in Phase 1 with explicit criteria from the brief.

### Voice Audit Checklist

A Phase 1 deliverable. 5-10 concrete items drawn from the most commonly violated voice-guide rules. Examples of likely items:
- No bullet lists with bolded lead-ins in "How It Works" sections
- System-as-subject in concept pages (no "you")
- No transition sentences opening paragraphs
- Verification steps in recipes name concrete commands
- Terms defined functionally on first use

The checklist includes a reference-mode addendum (3-4 items) for pages like CLI command reference, Testing factories, and DI annotation tables: tables before prose in reference sections, no narrative arc in annotation tables, terse functional definitions in table cells, no admonitions in reference tables.

The checklist is the pass/fail gate for section PRs — not a subjective scan.

### Link Validation

Add a post-build HTML link checker (e.g., `muffet` or `htmltest`) targeting the built `site/` directory. `mkdocs build --strict` and lychee both miss broken anchor fragments (`#section-name`). Run on every section PR to the docs branch.

### Pre-Phase 3 Cleanup

Audit Pyright suppressions in `docs/pyrightconfig.json`: determine whether `reportOperatorIssue` and `reportAssignmentType` can move from global suppressions to per-file exclusions. New snippet files should not inherit broad suppressions by default.

## Replacement Targets

| Target | Replaced by | Action |
|---|---|---|
| `mkdocs.yml` nav structure (lines 32-126) | New nav from Phase 1 site outline | Replace in place |
| All 76 `.md` files under `docs/pages/` | Blank-slate rewrites from Phase 3 | Overwrite per section PR |
| `docs/pages/advanced/` directory (6 pages) | Content rehomed to `core-concepts/states/` and troubleshooting | Delete directory after rehoming |
| Unclaimed snippet files (count determined in Phase 2 audit) | Nothing — dead code | Delete |
| `docs/pages/advanced/managing-helpers.md` filesystem location | `docs/pages/core-concepts/api/managing-helpers.md` (consistent with nav placement) | Move file |

## Convention Examples

The conventions for this rewrite are the voice-guide.md style rules and doc-rules.md page templates. Rather than extracting code snippets, the authoritative convention sources are:

### Voice: System-as-subject (concept pages)

**Source:** `.claude/rules/voice-guide.md`, "After" example in Concept Page section

```markdown
The event bus delivers Home Assistant events — state changes, service calls,
component loads — to any app handler that subscribes. It also delivers
Hassette-internal events.

`self.bus` is available on every `App` instance. Hassette creates it at startup.
```

### Voice: Code-first with "you" (getting-started pages)

**Source:** `.claude/rules/voice-guide.md`, "After" example in Getting-Started Page section

```markdown
## Step 3: Subscribe to a state change

Call `self.bus.on_state_change()` to subscribe. The `"sun.*"` pattern matches
any entity in the `sun` domain — in practice, `sun.sun`.
```

### Voice: Prose "How It Works" (recipe pages)

**Source:** `.claude/rules/voice-guide.md`, "After" example in Recipe Page section

```markdown
`on_state_change` subscribes to every state transition on the motion sensor.
`D.StateNew[states.BinarySensorState]` delivers the new state as a typed
object — the handler covers both `"on"` and `"off"` transitions in one place
rather than two separate subscriptions.
```

### Snippet inclusion pattern

**Source:** `.claude/rules/doc-rules.md`, Examples section

```markdown
Full file:
  --8<-- "pages/core-concepts/bus/snippets/subscribe_example.py"

Fragment via section markers:
  --8<-- "pages/core-concepts/bus/snippets/bus_subscribe.py:subscribe"
```

### DO/DON'T: "How It Works" formatting

**Source:** `.claude/rules/voice-guide.md`, Recipe Page before/after

DON'T — bullet list with bolded lead-ins:
```markdown
- **`on_state_change`** subscribes to every state transition on the motion
  sensor. The handler uses **dependency injection** ...
- When state is `"on"`, any pending off job is cancelled...
```

DO — flowing prose paragraphs:
```markdown
`on_state_change` subscribes to every state transition on the motion sensor.
`D.StateNew[states.BinarySensorState]` delivers the new state as a typed
object — the handler covers both transitions in one place.

When motion turns on, any pending off job is cancelled before the light
turns on. This resets the timer...
```

## Alternatives Considered

**Incremental patching (page-by-page voice and structure fixes):** Faster per-page but doesn't fix structural problems — "Advanced" grab-bag, DI scattered across three locations, tab-mirroring Web UI docs. The issues compound because each page links to and assumes the structure of others. Rejected because structural changes require a coordinated rewrite, not incremental patches.

**Partial rewrite (rewrite worst sections, leave good ones):** Lower risk for already-good sections (recipes, getting-started). Rejected because it preserves the structural rot in the nav and cross-section organization. The blank-slate approach with exemplar anchoring guards against regression on good pages.

**Automated voice linting:** A script that checks docs against voice-guide rules mechanically. Complementary but insufficient — voice rules like "system-as-subject" and "no transition sentences" require judgment. The voice audit checklist is the manual equivalent; automated checks could be added later for the mechanical subset.

## Test Strategy

### Existing Tests to Adapt

No software tests are affected. The "tests" for documentation are CI validation jobs:

- `mkdocs build --strict` — already runs in CI; continues as-is
- Pyright on `docs/pages/*/snippets/*.py` — already runs in CI; continues with current `docs/pyrightconfig.json`
- `tools/check_schemas_fresh.py` — pre-push hook; unaffected

### New Test Coverage

- **Link checker CI job** (AC#3): Post-build HTML link checker targeting the built `site/` directory to catch broken anchor fragments that `mkdocs build --strict` misses. Run on every PR to the docs branch.
- **Snippet orphan check** (FR#13, AC#5): Script or CI step that verifies every `.py` file under `docs/pages/*/snippets/` is referenced by at least one `--8<--` include in a `.md` file. Run on every PR to the docs branch.

### Tests to Remove

No tests to remove. Snippet files deleted during the Phase 2 audit are the only removals, and they have no dedicated test infrastructure beyond Pyright's glob-based inclusion.

## Documentation Updates

This change IS the documentation. No other documentation artifacts need updating:

- `CHANGELOG.md` — auto-generated by release-please from commit messages; no manual edit
- `README.md` — if the docs site URL or getting-started link changes, update the README reference (verify in Phase 1 when finalizing nav)
- `.claude/rules/doc-rules.md` — recipe template updated to include "Verify it's working" step (FR#4 gap). Voice-guide.md unchanged

## Impact

### Changed Files

**Cross-cutting:**
- `mkdocs.yml` — nav structure replaced (lines 32-126)

**By section (all pages overwritten or moved):**
- `docs/pages/getting-started/` — 9 pages (5 main + 4 docker)
- `docs/pages/core-concepts/` — ~31 pages across 8 subsections + architecture + internals
- `docs/pages/web-ui/` — ≤6 pages (consolidated from 12 tab-mirroring pages to task-oriented)
- `docs/pages/cli/` — 4 pages
- `docs/pages/testing/` — 4 pages
- `docs/pages/recipes/` — 7 pages
- `docs/pages/advanced/` — 6 pages (directory deleted; content rehomed)
- `docs/pages/migration/` — 8 pages (Phase 1 decides whether to condense to fewer pages)
- `docs/pages/troubleshooting.md` — 1 page
- `docs/index.md` — home page

**Snippet files:** 258 files across all sections — audited in Phase 2, unclaimed files deleted, remaining files rewritten alongside their pages

### Behavioral Invariants

- `mkdocs build --strict` must continue to pass
- Pyright CI on snippet files must continue to pass
- The docs site URL structure must not break existing external links (use `use_directory_urls: true` and preserve section-level paths where possible)
- API reference auto-generation via `gen_ref_pages.py` is unaffected

### Blast Radius

- **Docs site readers** — every page changes; users see an atomic swap when the docs branch merges to main
- **Issue #540** — superseded and should be closed
- **README.md** — may need link updates if nav paths change

## Open Questions

- Pyright config scoping: whether `reportOperatorIssue` and `reportAssignmentType` can move from global suppressions to per-file exclusions. Pre-Phase 3 cleanup item.

## Resolved Decisions (Phase 1)

- **Exemplars:** Bus overview (concept), Motion Lights (recipe), DI annotations page (reference)
- **Migration:** Keep all 8 pages — each covers a distinct mapping and the section is a primary inflow path
- **Web UI consolidation:** 5 pages — Overview, Debug a Failing Handler, Read and Filter Logs, Manage Apps, Inspect App Configuration and Code
- **PUBLIC_MODULES:** Review included in Phase 1 (T01)
- **Link checker:** Muffet for post-build HTML link checking
