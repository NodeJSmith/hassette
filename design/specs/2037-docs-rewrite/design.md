# Design: Hassette Documentation Rewrite

**Date:** 2026-04-11
**Status:** archived
**Spec:** design/specs/2037-docs-rewrite/spec.md
**Research:** /tmp/claude-mine-design-research-oEN2jn/brief.md

## Problem

The Hassette docs have never been reviewed by a technical writer. The result is a corpus that will embarrass a public launch: the AppDaemon comparison is a 1039-line monolith with ~48 inline code blocks; the Testing page is 637 lines covering beginner and expert content without separation; roughly a dozen pages are under 50 lines (placeholder-quality); the custom CSS targets the wrong theme framework and isn't even loaded; the API reference exposes every internal module; and ~100 inline code blocks across 30 pages violate the snippet-only convention. None of this was caught because no external quality bar was applied during initial authoring.

## Non-Goals

- Source code changes beyond docstring improvements for the API reference.
- Documenting undocumented internal implementation details.
- Changing any public API behavior or signatures.

## Architecture

### Phase structure

The rewrite runs as a single caliper spec (`2037-docs-rewrite`) in two phases separated by an explicit author approval gate:

**Phase 1 — Nav audit (WP01).** A single WP that does no content rewriting — only analysis and proposal. It produces a committed artifact (`docs/nav-audit.md` or similar) containing:

1. A before/after `mkdocs.yml` nav block diff (proposed new nav tree).
2. Per-page recommendations: keep / rewrite / split / merge / delete, with rationale.
3. Resolution of the Hassette-vs-YAML placement question (options: keep in Getting Started, promote to top-level "Why Hassette?", or fold into the home page — the nav audit presents all three and author picks during approval).
4. Theme/CSS recommendations for Material (any comparison-table, side-by-side code block, or tab format gaps).
5. The complete snippet dependency map (the research brief already produced this — the audit WP includes it by reference and flags any changes from the rewrite).
6. mkdocstrings API reference scope: the audit produces the allowlist of modules to expose. The allowlist is everything in `hassette.__all__` (37 entries) plus a curated set of commonly-referenced types not at the top level (e.g., `ScheduledJob`, event model classes, state model base classes). Anything not on the allowlist gets no reference page.
7. A per-module docstring gap list for the allowlisted public surface (`App`, `Bus`, `Scheduler`, `Api`, `StateManager`, `test_utils` Tier 1 layer). A class/function is considered documented if it has at least a one-line summary and all non-obvious parameters are annotated.
8. A redirect table for any pages the audit recommends deleting or merging (to fix inbound cross-links).

The orchestrator **pauses after WP01** and waits for an explicit author approval signal: either a committed `APPROVED` comment in the audit document, or an explicit chat signal. The approval records which structural recommendations are accepted. No content WP starts until the approval is recorded.

**Phase 2 — Content rewrite WPs (WP02–WP11).** Grouped by nav section. Executed by the `engineering-technical-writer` agent. Each WP reads relevant source files alongside the doc page to verify accuracy. Inaccuracies are corrected. Anything the agent cannot confidently verify is flagged with `!!! warning "Needs human review"` (greppable, visually prominent in Material). Every WP completion report includes a mandatory **Flags** section listing each flag added (page name + one-line description of the uncertainty).

### Verification gate

Every content WP runs `mkdocs build --strict` as its verification step. Strict mode catches unresolved autorefs, missing pages, and broken `--8<--` snippet includes (the existing `check_paths: true` already makes snippet errors fatal). A WP that fails `mkdocs build --strict` is not considered complete — subsequent WPs are blocked until the failing WP is fixed.

### Navigation structure (post-audit decisions already made)

The following structural decisions are resolved before planning and do not need to be revisited in the nav audit:

- **Migration Guide**: The 1039-line `appdaemon-comparison.md` is split into a multi-page top-level section with ~6–8 pages mirroring the Core Concepts structure: an index page plus one page per concept area (Bus, Scheduler, API, Configuration, Testing, and a Migration Checklist). Each section shows AppDaemon patterns → Hassette equivalents side-by-side. The nav audit confirms exact page boundaries from the existing `###`-section breakdown.

- **Testing section**: The 637-line `testing/index.md` becomes a multi-page section under the existing `Testing:` nav folder. Main page: Quick Start + basic assertions (what a beginner needs). Subpages: Time Control, Concurrency & pytest-xdist, Factories & Internals. Split points are specified by the nav audit before WP07 runs.

- **Hassette-vs-YAML placement**: Deferred to the nav audit. The audit presents the three options (keep in Getting Started, promote to top-level "Why Hassette?", fold into home page) with a recommendation; the author picks during approval.

- **FR#7 interpretation**: Core Concepts pages use a shared knowledge baseline — Python knowledge assumed, HA concepts explained. AppDaemon parallels are confined to the Migration Guide, not inlined into Core Concepts pages. This is simpler to maintain and makes the Migration Guide the definitive cross-audience resource.

### Snippet policy

After the rewrite, no inline fenced code blocks appear in rendered pages. All code examples exist as runnable `.py` files (or `.toml`/`.yml` for config) in the relevant `snippets/` directory, embedded via `--8<--` with section markers. Snippet files must contain all necessary imports and be valid, parseable Python. Pages with zero snippet includes and non-trivial code blocks must be converted during the relevant content WP:

- `appdaemon-comparison.md` (~48 inline blocks) — WP09
- `testing/index.md` (~31 inline blocks) — WP07
- `persistent-storage.md` (~13 inline blocks) — WP05
- Docker pages (`troubleshooting.md`, `dependencies.md`, `image-tags.md`) — WP03
- `database-telemetry.md`, `web-ui/index.md`, `log-level-tuning.md`, `bus/index.md`, `api/index.md` — respective WPs

The extraction pattern for self-referencing snippets (e.g., `self.bus` without class context): wrap in a minimal `App` subclass with `async def on_initialize(self):` and use `# --8<-- [start:section]` / `[end:section]` markers to embed only the relevant lines.

Dead snippet files to delete during the inline-to-snippet WPs:
- `pages/getting-started/snippets/hello_world.py`
- `pages/advanced/snippets/state-registry/basic_custom_state.py`
- `pages/advanced/snippets/state-registry/error_handling_examples.py`
- `pages/advanced/snippets/state-registry/integration_snippets.py`

### API reference scoping

`tools/gen_ref_pages.py` currently walks all of `src/` with no public/internal filter. After WP10, it is rewritten to emit `::: module.path` stubs only for modules in the nav audit's allowlist. The allowlist is seeded from `hassette.__all__` and `hassette.test_utils.__all__` (Tier 1 only), then extended by the nav audit WP with curated additions for types users commonly reference via mkdocstrings autorefs. Any `[Symbol][module.path]` autoref in the narrative docs that points to a non-allowlisted module is either updated to point to an allowlisted equivalent or converted to plain text.

### CSS and theme

`docs/_static/style.css` uses Sphinx/Read-the-docs selectors (`.wy-nav-content`, `.rst-content`) that have no effect in MkDocs Material. It is also not registered in `mkdocs.yml`'s `extra_css:`. It is **deleted** during WP02 (or as part of WP01 cleanup). Any `.hero` styling on `index.md:1` is replaced with a valid Material `attr_list` + short inline rule if needed.

The nav audit WP evaluates whether any Material extensions or configuration changes are needed for comparison tables and side-by-side code blocks (the Material `content.tabs` feature is already enabled via `pymdownx.tabbed`).

### WP grouping sketch

This is planning context for `/mine.draft-plan`, not a binding WP plan (that comes after nav audit approval):

| WP | Scope | Key outputs |
|----|-------|-------------|
| WP01 | Nav audit + theme audit + API ref scope + snippet map | Committed audit doc; orchestrator pauses for approval |
| WP02 | Home, Getting Started, HA Token | 30-minute path; CSS cleanup |
| WP03 | Docker Deployment (4 pages) | Inline-to-snippet conversion; accuracy check |
| WP04 | Core Concepts: Apps + Bus + Scheduler | Accuracy + remaining inline-to-snippet |
| WP05 | Core Concepts: API + States + Persistent Storage + Database & Telemetry + Configuration | Persistent-storage and database-telemetry heavy |
| WP06 | Web UI (5 pages) | Polish + snippet conversion |
| WP07 | Testing restructure | Multi-page split; largest content WP |
| WP08 | Advanced section | Fill 9-line index; all mostly snippet-based |
| WP09 | Migration Guide (AppDaemon split) | ~48 inline blocks → snippets; multi-page nav |
| WP10 | API reference scope + docstring gap fill | Filter `gen_ref_pages.py`; expand thin docstrings |
| WP11 | Troubleshooting + final `mkdocs build --strict` + getting-started walkthrough | Verification; straggler fixes |

**Ordering constraints:**
- WP01 gates all others.
- WP02 should come early so the 30-minute path acceptance gate can be exercised.
- WP10 should come after most content WPs so autoref targets are stable.
- WP07 and WP09 are highest-risk; schedule with buffer.
- WP11 always runs last.

### Shared snippet tracking

The research brief identified four cross-section shared snippets that require a completion-report note in any WP that touches them:

- `apps/snippets/app_config_definition.py` and `app_config.toml` — shared by `apps/configuration.md` and `configuration/applications.md`
- `configuration/snippets/file_discovery.md` — shared by `configuration/index.md` and `getting-started/index.md`
- `dependency-injection/custom_type_converter.py` — shared by `advanced/dependency-injection.md` and `advanced/type-registry.md`
- `state-registry/basic_custom_state_usage.py` — lives in state-registry snippets but referenced from `custom-states.md`

Any WP that touches a shared snippet must list all other pages that include it in its completion report.

## Alternatives Considered

**Single-pass rewrite without nav audit gate.** Start content WPs immediately using the current nav as-is. Rejected because the AppDaemon comparison split and testing restructure require real decisions about section boundaries — making those decisions mid-content-WP rather than up front produces incoherent nav structures that need rework. The gate is cheap (one committed doc) and prevents the "well-intentioned touch-up" trap.

**Audit-only, no caliper orchestration.** Produce a human-readable audit report and let the author drive content manually. Rejected because the 40+ page scope is too large for ad-hoc editing — consistent snippet policy, mandatory flag reporting, and build-gate verification require orchestration to hold.

**Keep AppDaemon comparison as one restructured page.** The page is already too long at 1039 lines, and the spec's accepted resolution is a multi-page Migration Guide. A single restructured page with better internal anchors is a half-measure that still fails the "calibrated to content" criterion.

## Test Strategy

This is a documentation project — there is no application code to unit test. Verification is at the build and integration level:

- **`mkdocs build --strict`** after every content WP merge. This is the primary verification gate. `check_paths: true` on `pymdownx.snippets` makes broken `--8<--` includes build-fatal. Strict mode adds unresolved autoref detection.
- **Snippet parseability**: every new or converted snippet file is checked with `python -m py_compile` as part of the WP completion step.
- **Getting Started walkthrough**: WP11 includes a live walkthrough of the 30-minute path (Home → orientation → Local or Docker Setup → first automation running), confirming no step requires off-page knowledge beyond Python basics.
- **Dead snippet audit**: WP completion reports include a check that no new dead snippet files were introduced.

## Open Questions

- **Hassette-vs-YAML placement**: deferred to nav audit WP. The three options (keep in Getting Started / promote to top-level / fold into home page) will be presented with a recommendation for author approval during the audit review.
- **Exact Migration Guide page boundaries**: the nav audit WP maps the existing `###`-section breakdown in `appdaemon-comparison.md` to a proposed multi-page structure. The design calls for ~6–8 pages; exact count and titles TBD in the audit.
- **Testing section split points**: the nav audit specifies the exact subpage boundaries for the testing restructure (which content goes to Time Control, Concurrency, Factories/Internals). WP07 executes against the approved split, not against a self-determined split.
- **API reference allowlist additions**: the nav audit produces the curated additions to the `__all__`-seeded allowlist. Until the audit runs, we cannot enumerate the exact modules in scope.
- **`mkdocs build --strict` CI integration**: WP11 enables strict mode, but the CI pipeline may need a configuration change. WP11 scopes this — if the pipeline change is out of scope for a docs WP, it becomes a follow-up issue.

## Impact

**Files directly modified:**
- `mkdocs.yml` — nav restructure, `extra_css:` removal (dead CSS), possibly new extensions
- `docs/_static/style.css` — deleted
- `tools/gen_ref_pages.py` — public-API filter added
- `docs/pages/appdaemon-comparison.md` — deleted; replaced by `docs/pages/migration/` section (~6–8 files)
- `docs/pages/testing/index.md` — restructured; 3–4 subpages added under `docs/pages/testing/`
- ~30 Markdown pages with inline code blocks — inline blocks extracted to snippet files
- ~4 dead snippet files — deleted
- ~10–20 public-API Python source files — docstring additions only (no behavior change)

**Dependencies that will need updates:**
- Any inbound cross-links to the AppDaemon comparison page (currently at least `index.md:71`) must be updated to the new Migration Guide index.
- Any inbound cross-links to pages that the audit recommends deleting or merging must be updated before the old page is removed (redirect table is a WP01 output).
- CI pipeline: if `mkdocs build --strict` is not the current CI command, the pipeline configuration must be updated (scoped to WP11 or a follow-up).

**Blast radius:** Documentation only. No runtime behavior changes. Public API is not affected. The only source code changes are additive docstring prose on ~10–20 classes/functions — zero behavior impact.
