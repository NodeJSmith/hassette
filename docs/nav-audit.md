**Approval status:** PENDING — author must add `**APPROVED**` and a date before content WPs run.

---

# Hassette Documentation Nav Audit

**Date:** 2026-04-11
**Auditor:** Technical Writer Agent (engineering-technical-writer)
**Scope:** Full nav structure, per-page content assessment, CSS/theme review, snippet dependency map, mkdocstrings API reference scope, docstring gaps, and build baseline.

This document is the authoritative input for all downstream content WPs. Every subsequent WP that references nav structure, split points, or the API reference allowlist must cite a section of this document.

---

## Section 1: Nav Structure Evaluation

### Current nav tree (verbatim from `mkdocs.yml` lines 22–78)

```yaml
nav:
  - Home: index.md
  - Getting Started:
      - Local Setup: pages/getting-started/index.md
      - Hassette vs. YAML: pages/getting-started/hassette-vs-ha-yaml.md
      - Docker Deployment:
          - Docker Setup: pages/getting-started/docker/index.md
          - Managing Dependencies: pages/getting-started/docker/dependencies.md
          - Image Tags: pages/getting-started/docker/image-tags.md
          - Troubleshooting: pages/getting-started/docker/troubleshooting.md
      - Home Assistant Token: pages/getting-started/ha_token.md
  - Core Concepts:
      - Architecture: pages/core-concepts/index.md
      - Apps:
          - Overview: pages/core-concepts/apps/index.md
          - Lifecycle: pages/core-concepts/apps/lifecycle.md
          - Configuration: pages/core-concepts/apps/configuration.md
      - Bus:
          - Overview: pages/core-concepts/bus/index.md
          - Writing Handlers: pages/core-concepts/bus/handlers.md
          - Filtering & Predicates: pages/core-concepts/bus/filtering.md
      - Scheduler:
          - Overview: pages/core-concepts/scheduler/index.md
          - Scheduling Methods: pages/core-concepts/scheduler/methods.md
          - Job Management: pages/core-concepts/scheduler/management.md
      - API:
          - Overview: pages/core-concepts/api/index.md
          - Entities & States: pages/core-concepts/api/entities.md
          - Services: pages/core-concepts/api/services.md
          - Utilities: pages/core-concepts/api/utilities.md
      - States: pages/core-concepts/states/index.md
      - Persistent Storage: pages/core-concepts/persistent-storage.md
      - Database & Telemetry: pages/core-concepts/database-telemetry.md
      - Configuration:
          - Overview: pages/core-concepts/configuration/index.md
          - Authentication: pages/core-concepts/configuration/auth.md
          - Global Settings: pages/core-concepts/configuration/global.md
          - Applications: pages/core-concepts/configuration/applications.md
  - Web UI:
      - Overview: pages/web-ui/index.md
      - Dashboard: pages/web-ui/dashboard.md
      - Apps: pages/web-ui/apps.md
      - Sessions: pages/web-ui/sessions.md
      - Logs: pages/web-ui/logs.md
  - Testing:
      - Testing Your Apps: pages/testing/index.md
  - Advanced:
      - Overview: pages/advanced/index.md
      - Dependency Injection: pages/advanced/dependency-injection.md
      - Custom States: pages/advanced/custom-states.md
      - State Registry: pages/advanced/state-registry.md
      - TypeRegistry: pages/advanced/type-registry.md
      - Log Level Tuning: pages/advanced/log-level-tuning.md
  - Troubleshooting: pages/troubleshooting.md
  - AppDaemon Comparison: pages/appdaemon-comparison.md
  - Changelog: CHANGELOG.md
  - API Reference: reference/
```

### Structural issues with the current nav

1. **`AppDaemon Comparison` is a top-level orphan** — it sits between Changelog and the API Reference, breaking the logical reading order. A first-time reader who reaches it is already past all the learning content. It belongs as a top-level `Migration Guide:` section, earlier in the nav.

2. **`Testing:` section has a single page** — `pages/testing/index.md` is 636 lines. It covers Quick Start, the test harness API, state seeding, three simulate methods, asserting API calls, time control (full section), event factories, configuration errors, advanced harness use, limitations (concurrency lock details, pytest-xdist guidance), and troubleshooting. This is three logical documents collapsed into one. The spec (FR#6) requires restructuring so beginners do not need to read advanced content to understand the basic testing model.

3. **`Advanced: Overview` is stub-thin** — `pages/advanced/index.md` is 9 lines. It is a pure link list with no conceptual context about when to use advanced features. Either expand it or drop the `Overview` sub-entry and let the section title be its own index.

4. **`Getting Started: Home Assistant Token`** — a 21-line page consisting entirely of screenshots for creating an HA token. It is appropriately brief but is placed after `Docker Deployment`, which forces readers who need it (referenced from `Authentication`) to navigate backwards. It should remain in Getting Started but its `Home Assistant Token` placement is fine — readers following Getting Started sequentially reach it naturally. No change needed.

5. **`Hassette vs. YAML` placement** — spec FR#2 requires the audit to evaluate whether this page is misplaced. Assessment: at 67 lines the page is thin but serves a real decision-support function for readers evaluating Hassette. Three placement options and their tradeoffs:

   - **Option A (current): Keep in Getting Started** — The reader evaluating Hassette has just found it and reads the home page, then Getting Started. Placing it here means they see it immediately. Con: Getting Started should be about *doing*, not *deciding*. A decision-support page interrupts the action flow.

   - **Option B: Promote to top-level "Why Hassette?"** — A dedicated top-level entry before Getting Started makes it explicit this is a "should I use this?" page. Con: most readers skip it because they've already decided to try it.

   - **Option C: Fold into the home page** — The home page already covers what Hassette is and why it matters. The comparison table in `hassette-vs-ha-yaml.md` could be an expandable section on the home page. Con: makes the home page longer; comparison tables are harder to maintain inline.

   **Recommendation: Option A (keep current placement, but rename)**. The page is a soft prerequisite for `Local Setup` — the reader should decide if Hassette is worth installing before following a setup guide. Rename the nav entry from `Hassette vs. YAML` to `Is Hassette Right for You?` to make its decision-support purpose explicit. This is a non-structural change and does not require WP approval to execute.

### Proposed nav structure

The proposed structure implements the spec decisions: `AppDaemon Comparison` replaced by a multi-page Migration Guide section, Testing section gains three subpages, Advanced Overview stub expanded or promoted.

```yaml
nav:
  - Home: index.md
  - Getting Started:
      - Local Setup: pages/getting-started/index.md
      - Is Hassette Right for You?: pages/getting-started/hassette-vs-ha-yaml.md
      - Docker Deployment:
          - Docker Setup: pages/getting-started/docker/index.md
          - Managing Dependencies: pages/getting-started/docker/dependencies.md
          - Image Tags: pages/getting-started/docker/image-tags.md
          - Troubleshooting: pages/getting-started/docker/troubleshooting.md
      - Home Assistant Token: pages/getting-started/ha_token.md
  - Core Concepts:
      - Architecture: pages/core-concepts/index.md
      - Apps:
          - Overview: pages/core-concepts/apps/index.md
          - Lifecycle: pages/core-concepts/apps/lifecycle.md
          - Configuration: pages/core-concepts/apps/configuration.md
      - Bus:
          - Overview: pages/core-concepts/bus/index.md
          - Writing Handlers: pages/core-concepts/bus/handlers.md
          - Filtering & Predicates: pages/core-concepts/bus/filtering.md
      - Scheduler:
          - Overview: pages/core-concepts/scheduler/index.md
          - Scheduling Methods: pages/core-concepts/scheduler/methods.md
          - Job Management: pages/core-concepts/scheduler/management.md
      - API:
          - Overview: pages/core-concepts/api/index.md
          - Entities & States: pages/core-concepts/api/entities.md
          - Services: pages/core-concepts/api/services.md
          - Utilities: pages/core-concepts/api/utilities.md
      - States: pages/core-concepts/states/index.md
      - Persistent Storage: pages/core-concepts/persistent-storage.md
      - Database & Telemetry: pages/core-concepts/database-telemetry.md
      - Configuration:
          - Overview: pages/core-concepts/configuration/index.md
          - Authentication: pages/core-concepts/configuration/auth.md
          - Global Settings: pages/core-concepts/configuration/global.md
          - Applications: pages/core-concepts/configuration/applications.md
  - Web UI:
      - Overview: pages/web-ui/index.md
      - Dashboard: pages/web-ui/dashboard.md
      - Apps: pages/web-ui/apps.md
      - Sessions: pages/web-ui/sessions.md
      - Logs: pages/web-ui/logs.md
  - Testing:
      - Testing Your Apps: pages/testing/index.md
      - Time Control: pages/testing/time-control.md
      - Concurrency & pytest-xdist: pages/testing/concurrency.md
      - Factories & Internals: pages/testing/factories.md
  - Advanced:
      - Overview: pages/advanced/index.md
      - Dependency Injection: pages/advanced/dependency-injection.md
      - Custom States: pages/advanced/custom-states.md
      - State Registry: pages/advanced/state-registry.md
      - Type Registry: pages/advanced/type-registry.md
      - Log Level Tuning: pages/advanced/log-level-tuning.md
  - Migration Guide:
      - Overview: pages/migration/index.md
      - Core Concepts: pages/migration/concepts.md
      - Bus: pages/migration/bus.md
      - Scheduler: pages/migration/scheduler.md
      - API: pages/migration/api.md
      - Configuration: pages/migration/configuration.md
      - Testing: pages/migration/testing.md
      - Migration Checklist: pages/migration/checklist.md
  - Troubleshooting: pages/troubleshooting.md
  - Changelog: CHANGELOG.md
  - API Reference: reference/
```

### Before/after nav diff (key changes only)

```diff
 nav:
   - Home: index.md
   - Getting Started:
-      - Hassette vs. YAML: pages/getting-started/hassette-vs-ha-yaml.md
+      - Is Hassette Right for You?: pages/getting-started/hassette-vs-ha-yaml.md
       ...
   - Testing:
-      - Testing Your Apps: pages/testing/index.md
+      - Testing Your Apps: pages/testing/index.md
+      - Time Control: pages/testing/time-control.md
+      - Concurrency & pytest-xdist: pages/testing/concurrency.md
+      - Factories & Internals: pages/testing/factories.md
+  - Migration Guide:
+      - Overview: pages/migration/index.md
+      - Core Concepts: pages/migration/concepts.md
+      - Bus: pages/migration/bus.md
+      - Scheduler: pages/migration/scheduler.md
+      - API: pages/migration/api.md
+      - Configuration: pages/migration/configuration.md
+      - Testing: pages/migration/testing.md
+      - Migration Checklist: pages/migration/checklist.md
-  - AppDaemon Comparison: pages/appdaemon-comparison.md
```

### Rationale for each change

| Change | Rationale |
|--------|-----------|
| Rename `Hassette vs. YAML` → `Is Hassette Right for You?` | The nav label should describe the reader's goal, not the content format. |
| Split `Testing:` into four pages | Current page is 636 lines covering three distinct concerns. Beginners must read past 200+ lines of advanced content (time control, concurrency, factories) before they understand the testing mental model. Split ensures beginners can stop after the first page. |
| Replace `AppDaemon Comparison` with `Migration Guide:` section (8 pages) | Spec decision (design.md). The 1039-line comparison page is the densest page in the entire doc set. It needs to be broken into focused guides by topic so AppDaemon users can navigate to the specific equivalents they need without reading the entire page. |
| Move Migration Guide before Troubleshooting | A reader migrating from AppDaemon benefits from this content before they hit troubleshooting. |
| Rename `TypeRegistry` → `Type Registry` | Typography consistency: other entries use spaces. |

---

## Section 2: Per-Page Recommendations

| Page path | Lines | Snippet includes | Recommendation | Rationale |
|-----------|------:|-----------------|----------------|-----------|
| `index.md` (home) | 72 | 0 | **keep / minor update** | Solid overview. Video embeds work. One link points to `pages/appdaemon-comparison.md` — update to `pages/migration/index.md`. |
| `pages/getting-started/index.md` | 109 | 3 | **rewrite** | Good structure but inline code blocks (non-snippet) throughout. Convert to snippet files per FR#9. |
| `pages/getting-started/hassette-vs-ha-yaml.md` | 67 | 0 | **expand + rename** | 67 lines, no code. Thin for a decision-support page. Needs a comparison table and a concrete "when to use AppDaemon" section. |
| `pages/getting-started/docker/index.md` | 203 | 3 snippet files | **rewrite** | Well-structured with snippets. Rewrite for accuracy and prose quality. |
| `pages/getting-started/docker/dependencies.md` | 325 | 0 | **rewrite** | Dense but appropriate depth for the topic. Zero snippet files — all inline fenced blocks. Convert to snippets. |
| `pages/getting-started/docker/image-tags.md` | 155 | 0 | **rewrite** | Inline fenced blocks. Convert to snippets. |
| `pages/getting-started/docker/troubleshooting.md` | 412 | 0 | **rewrite** | No snippet files — all inline fenced blocks. Convert to snippets. Appropriate page length for troubleshooting reference. |
| `pages/getting-started/ha_token.md` | 21 | 0 | **keep** | Entirely screenshots. No inline code. Appropriate length and format. |
| `pages/core-concepts/index.md` | 94 | 0 | **keep / minor update** | Good architecture overview with Mermaid diagrams. Minor prose polish. |
| `pages/core-concepts/apps/index.md` | 118 | 1 snippet file | **rewrite** | Inline fenced blocks alongside snippet includes — mixed pattern. Convert all inline fences to snippet files. |
| `pages/core-concepts/apps/lifecycle.md` | 49 | 1 snippet file | **rewrite** | Very short — 1 snippet include plus 2 fence markers (for code in prose). Thin but topic is naturally bounded. |
| `pages/core-concepts/apps/configuration.md` | 36 | 3 snippet files | **rewrite** | Very thin at 36 lines but the topic is appropriately scoped — app config definition is simple. |
| `pages/core-concepts/bus/index.md` | 135 | 0 | **rewrite** | All inline fenced blocks. Convert to snippets. |
| `pages/core-concepts/bus/handlers.md` | 89 | 6 snippet files | **rewrite** | Good snippet discipline. Prose quality review needed. |
| `pages/core-concepts/bus/filtering.md` | 99 | 10 snippet files | **rewrite** | Good snippet discipline. |
| `pages/core-concepts/scheduler/index.md` | 47 | 0 | **rewrite** | Thin overview. All inline fenced blocks. Convert to snippets. |
| `pages/core-concepts/scheduler/methods.md` | 175 | 8 snippet files | **rewrite** | Good snippet discipline. |
| `pages/core-concepts/scheduler/management.md` | 57 | 3 snippet files | **rewrite** | Short but appropriately scoped. Good snippet discipline. |
| `pages/core-concepts/api/index.md` | 50 | 0 | **rewrite** | Thin overview. Inline fenced blocks. Convert to snippets. |
| `pages/core-concepts/api/entities.md` | 72 | 5 snippet files | **rewrite** | Good snippet discipline. Prose review needed. |
| `pages/core-concepts/api/services.md` | 35 | 3 snippet files | **rewrite** | Short but focused. Good snippet discipline. |
| `pages/core-concepts/api/utilities.md` | 40 | 3 snippet files | **rewrite** | Short. Good snippet discipline. |
| `pages/core-concepts/states/index.md` | 65 | 4 snippet files | **rewrite** | Good snippet discipline. Prose review needed. |
| `pages/core-concepts/persistent-storage.md` | 424 | 0 | **rewrite** | Dense (424 lines) with all inline fenced blocks. Convert to snippets. Split candidate if content review reveals logical subsections. |
| `pages/core-concepts/database-telemetry.md` | 115 | 0 | **rewrite** | Reasonable length. All inline fenced blocks. Convert to snippets. |
| `pages/core-concepts/configuration/index.md` | 26 | 1 snippet include | **rewrite** | Thin overview with one snippet include (file_discovery.md). Expand conceptual explanation. |
| `pages/core-concepts/configuration/auth.md` | 30 | 0 | **rewrite** | Very thin at 30 lines. No code blocks. Appropriate for narrow topic but prose is sparse. |
| `pages/core-concepts/configuration/global.md` | 229 | 1 snippet file | **rewrite** | Dense reference table. Appropriate depth. Convert remaining inline fenced blocks to snippets. |
| `pages/core-concepts/configuration/applications.md` | 82 | 4 snippet files | **rewrite** | Good snippet discipline. |
| `pages/web-ui/index.md` | 64 | 0 | **keep / minor update** | Overview with screenshots. 2 inline fence markers (for display). |
| `pages/web-ui/dashboard.md` | 59 | 0 | **keep / minor update** | Screenshot-heavy reference. No code blocks needed. |
| `pages/web-ui/apps.md` | 52 | 0 | **keep / minor update** | Screenshot-heavy reference. |
| `pages/web-ui/sessions.md` | 48 | 0 | **keep / minor update** | Screenshot-heavy reference. |
| `pages/web-ui/logs.md` | 39 | 0 | **keep / minor update** | Screenshot-heavy reference. Short but topic is narrow. |
| `pages/testing/index.md` | 636 | 0 | **rewrite + split** | 636 lines, zero snippet files. Split into four pages (see Section 1). Convert all inline fenced blocks to snippet files in a new `pages/testing/snippets/` directory. The main `index.md` covers Quick Start through Asserting API Calls. `time-control.md` covers freeze_time through trigger_due_jobs. `concurrency.md` covers the two concurrency lock sections and pytest-xdist. `factories.md` covers event factories, make_test_config, and limitations/troubleshooting. |
| `pages/advanced/index.md` | 9 | 0 | **expand** | Stub. 9 lines, pure link list. Expand with 2–3 sentences explaining when advanced features are needed and which to reach for first. |
| `pages/advanced/dependency-injection.md` | 273 | 16 snippet files | **rewrite** | Good snippet discipline. Prose review needed. |
| `pages/advanced/custom-states.md` | 174 | 10 snippet files | **rewrite** | Good snippet discipline. |
| `pages/advanced/state-registry.md` | 219 | 16 snippet files | **rewrite** | Good snippet discipline. |
| `pages/advanced/type-registry.md` | 359 | 14 snippet files | **rewrite** | Largest Advanced page. Good snippet discipline. Verify length is justified by content depth vs. split. |
| `pages/advanced/log-level-tuning.md` | 101 | 0 | **rewrite** | Inline fenced blocks. Convert to snippets. |
| `pages/troubleshooting.md` | 59 | 0 | **keep / minor update** | Well-structured symptom-oriented guide. No code blocks needed. |
| `pages/appdaemon-comparison.md` | 1039 | 0 | **delete / migrate** | Replace with 8-page Migration Guide section (see Section 1 and Section 3). |
| **New pages (to create):** | | | | |
| `pages/testing/time-control.md` | — | — | **create** | Extracted from testing/index.md §Time Control. |
| `pages/testing/concurrency.md` | — | — | **create** | Extracted from testing/index.md §Concurrency sections. |
| `pages/testing/factories.md` | — | — | **create** | Extracted from testing/index.md §Event Factories + §Advanced + §Limitations. |
| `pages/migration/index.md` | — | — | **create** | Overview: who should migrate, what's different, what to expect. |
| `pages/migration/concepts.md` | — | — | **create** | Core concept mapping: AppDaemon philosophy vs Hassette philosophy. |
| `pages/migration/bus.md` | — | — | **create** | `listen_state` / `listen_event` → `bus.on_state_change` / `bus.on_call_service`. |
| `pages/migration/scheduler.md` | — | — | **create** | Scheduler method equivalents with side-by-side examples. |
| `pages/migration/api.md` | — | — | **create** | Home Assistant API access: sync/raw dicts → async/Pydantic models. |
| `pages/migration/configuration.md` | — | — | **create** | `apps.yaml` / `appdaemon.yaml` → `hassette.toml` / `AppConfig`. |
| `pages/migration/testing.md` | — | — | **create** | Testing AppDaemon apps is hard; testing Hassette apps uses AppTestHarness. |
| `pages/migration/checklist.md` | — | — | **create** | Concise migration checklist with links to each migration page. |

---

## Section 3: Redirect Table

The following pages are being moved or deleted. Any page with inbound links must be updated during the WP that executes the move.

| Old path | New path | Inbound links that must be updated |
|----------|----------|-------------------------------------|
| `pages/appdaemon-comparison.md` | `pages/migration/index.md` | `docs/index.md:71` — `"Migration"` link pointing to appdaemon-comparison |
| `pages/testing/index.md` (time-control section) | `pages/testing/time-control.md` | Any WP documentation that links to `#time-control` anchor on testing/index.md |
| `pages/testing/index.md` (concurrency section) | `pages/testing/concurrency.md` | Any WP documentation that links to `#concurrency` anchor on testing/index.md |
| `pages/testing/index.md` (factories section) | `pages/testing/factories.md` | Any WP documentation that links to `#event-factories` anchor on testing/index.md |

**Note:** The `pages/testing/index.md` page itself is **not** deleted — only its excess content is extracted. The original URL remains valid with reduced content covering Quick Start through Asserting API Calls.

**Inbound link inventory for `appdaemon-comparison.md`:**

| File | Line | Link text | Action |
|------|------|-----------|--------|
| `docs/index.md` | 71 | `AppDaemon Comparison` | Update to `pages/migration/index.md`, text to `Migration Guide` |

**Note on `mkdocs.yml` nav references:** The WP that executes the Migration Guide restructuring (expected to be the content WP covering that section) must update `mkdocs.yml` nav to add the `Migration Guide:` section and remove `AppDaemon Comparison`.

---

## Section 4: Theme and CSS Audit

### `extra_css:` status

`mkdocs.yml` has **no `extra_css:` entry**. The file `docs/_static/style.css` exists but is **not registered** in `mkdocs.yml`. It has never been loaded by the MkDocs build and has had no effect on any rendered page.

### `docs/_static/style.css` analysis

The file contains three rule groups:

1. `.wy-nav-content` — a Read the Docs (Sphinx) selector. Has no effect in Material theme.
2. `.rst-content a.reference code.literal` — a Sphinx Read the Docs selector. Has no effect in Material theme.
3. `.rst-content img.hero` — a Sphinx Read the Docs selector. Has no effect in Material theme.

The `index.md` line 1 uses `{.hero}` as a Material `attr_list` class on the logo image. This attribute is processed by the `attr_list` markdown extension (which is configured in `mkdocs.yml`) and renders as `<img class="hero">` in HTML. However, because the `style.css` is not registered and uses `.rst-content img.hero` (Sphinx selector), the hero image styling is silently a no-op. The logo image renders without the intended `drop-shadow`, `max-width`, and centering styles.

**Recommendations:**

1. **Delete `docs/_static/style.css`** — it contains only Sphinx selectors and has never been active. Keeping it implies it does something, which misleads future maintainers.
2. **Replace hero styling with Material-compatible CSS** — if the logo centering and shadow are desired, add a minimal `docs/_static/hassette.css` registered via `extra_css:` using the Material DOM selectors (e.g., `.md-content img[src*="hassette-logo"]` or a dedicated class). Alternatively, use `md_in_html` to wrap the image in a `<figure>` with inline styles.
3. **Suggested minimal `extra_css:` entry** for Material-compatible hero image styling:

```yaml
extra_css:
  - _static/hassette.css
```

```css
/* docs/_static/hassette.css */
img.hero {
  display: block;
  margin: 2rem auto;
  max-width: 420px;
  height: auto;
  filter: drop-shadow(0 20px 20px rgba(0, 0, 0, 0.15));
}
```

### Tabbed content and comparison tables

The current `mkdocs.yml` includes `pymdownx.tabbed` but **not** `pymdownx.tabbed: alternate_style: true`. The `alternate_style` option is required for the modern Material tabbed layout (the old style is deprecated in Material 9+). If any content WP uses `=== "Tab"` syntax, add `alternate_style: true`:

```yaml
- pymdownx.tabbed:
    alternate_style: true
```

The migration guide pages will need side-by-side code comparisons. Two valid approaches with current configuration:

- **Tabbed content** (`=== "AppDaemon"` / `=== "Hassette"`) — works after adding `alternate_style: true`.
- **Two-column table** — `attr_list` and `md_in_html` are both configured, enabling HTML tables with Markdown inside cells.

**Recommendation:** Enable `alternate_style: true` for tabbed content in the migration guide. No other theme feature gaps were found.

---

## Section 5: Snippet Dependency Map

### Cross-section shared snippets

The following snippet files are included (`--8<--`) by pages in **more than one nav section**. Any WP that modifies one of these files must note in its completion report which other pages are affected.

| Snippet file | Included by |
|---|---|
| `pages/advanced/snippets/dependency-injection/custom_type_converter.py` | `pages/advanced/type-registry.md`, `pages/advanced/dependency-injection.md` |
| `pages/core-concepts/apps/snippets/app_config_definition.py` | `pages/core-concepts/configuration/applications.md`, `pages/core-concepts/apps/configuration.md` |
| `pages/core-concepts/apps/snippets/app_config.toml` | `pages/core-concepts/configuration/applications.md`, `pages/core-concepts/apps/configuration.md` |
| `pages/core-concepts/configuration/snippets/file_discovery.md` | `pages/getting-started/index.md`, `pages/core-concepts/configuration/index.md` |

### Section-local snippet directories (single-page use, no cross-section risk)

These directories are used exclusively within their own nav section. They do not require cross-WP coordination but are listed here for completeness.

| Section | Snippet directory |
|---------|-------------------|
| Getting Started | `pages/getting-started/snippets/` |
| Getting Started / Docker | `pages/getting-started/docker/snippets/` |
| Core Concepts / Apps | `pages/core-concepts/apps/snippets/` (shared with Configuration — see above) |
| Core Concepts / Bus | `pages/core-concepts/bus/snippets/` |
| Core Concepts / Scheduler | `pages/core-concepts/scheduler/snippets/` |
| Core Concepts / API | `pages/core-concepts/api/snippets/` |
| Core Concepts / States | `pages/core-concepts/states/snippets/` |
| Core Concepts / Configuration | `pages/core-concepts/configuration/snippets/` (shared with Getting Started — see above) |
| Advanced | `pages/advanced/snippets/` (contains `dependency-injection/` shared with type-registry — see above) |

### Pages with zero snippet files (inline fenced blocks only)

These pages need all inline fenced code blocks converted to `--8<--` snippet files (per spec FR#9) during their content WP:

`pages/getting-started/docker/dependencies.md`, `pages/getting-started/docker/image-tags.md`, `pages/getting-started/docker/troubleshooting.md`, `pages/core-concepts/bus/index.md`, `pages/core-concepts/scheduler/index.md`, `pages/core-concepts/api/index.md`, `pages/core-concepts/persistent-storage.md`, `pages/core-concepts/database-telemetry.md`, `pages/advanced/log-level-tuning.md`, `pages/testing/index.md` (and its three new split pages).

---

## Section 6: mkdocstrings API Reference Scope

### Current gen-files behavior

`tools/gen_ref_pages.py` walks `src/` with no public/internal filter, emitting `::: module.path` stubs for all discovered modules. After the rewrite (WP10), it should emit stubs only for modules on the allowlist below.

### Public reference allowlist

Seeded from `hassette.__all__` (31 entries) plus curated additions for types users commonly reference via autorefs.

#### Tier A: `hassette.__all__` entries (always on allowlist)

| Symbol | Module path | Notes |
|--------|-------------|-------|
| `ANY_VALUE` | `hassette.const` | Sentinel — include; used in bus filtering examples |
| `MISSING_VALUE` | `hassette.const` | Sentinel — include |
| `NOT_PROVIDED` | `hassette.const` | Sentinel — include |
| `STATE_REGISTRY` | `hassette.conversion` | Registry instance — see Section 8 for public/internal decision |
| `TYPE_REGISTRY` | `hassette.conversion` | Registry instance — see Section 8 for public/internal decision |
| `A` (accessors) | `hassette.event_handling.accessors` | Module alias — document the module |
| `Api` | `hassette.api` | Core class — document |
| `App` | `hassette.app` | Core class — document |
| `AppConfig` | `hassette.app` | Core class — document |
| `AppSync` | `hassette.app` | Sync app base — document |
| `Bus` | `hassette.bus` | Core class — document |
| `C` (conditions) | `hassette.event_handling.conditions` | Module alias — document the module |
| `D` (dependencies) | `hassette.event_handling.dependencies` | Module alias — document the module |
| `Hassette` | `hassette.core.core` | Entrypoint class — document |
| `HassetteConfig` | `hassette.config` | Core config class — document |
| `P` (predicates) | `hassette.event_handling.predicates` | Module alias — document the module |
| `RawStateChangeEvent` | `hassette.events` | Event model — document |
| `Scheduler` | `hassette.scheduler` | Core class — document |
| `ServiceResponse` | `hassette.models.services` | Response model — document |
| `TaskBucket` | `hassette.task_bucket` | Task management — document |
| `TypeConverterEntry` | `hassette.conversion` | Entry type — see Section 8 for public/internal decision |
| `accessors` | `hassette.event_handling.accessors` | Module — document |
| `conditions` | `hassette.event_handling.conditions` | Module — document |
| `dependencies` | `hassette.event_handling.dependencies` | Module — document |
| `entities` | `hassette.models.entities` | Module — document |
| `only_app` | `hassette.app` | Decorator — document |
| `predicates` | `hassette.event_handling.predicates` | Module — document |
| `register_simple_type_converter` | `hassette.conversion` | Registration function — see Section 8 |
| `register_type_converter_fn` | `hassette.conversion` | Registration function — see Section 8 |
| `states` | `hassette.models.states` | Module — document |

#### Tier B: Curated additions beyond `__all__`

These types appear frequently in docs pages, user code, and autoref targets. Including them in the reference ensures cross-linking works correctly.

| Symbol | Module path | Justification |
|--------|-------------|---------------|
| `BaseState` | `hassette.models.states.base` | Base class for all state models; autoref target in custom-states and state-registry pages |
| `StringBaseState` | `hassette.models.states.base` | Used in custom-states examples and Advanced pages |
| `NumericBaseState` | `hassette.models.states.base` | Used in custom-states examples |
| `BoolBaseState` | `hassette.models.states.base` | Used in custom-states examples |
| `DateTimeBaseState` | `hassette.models.states.base` | Used in custom-states examples |
| `TimeBaseState` | `hassette.models.states.base` | Used in custom-states examples |
| `ScheduledJob` | `hassette.scheduler.classes` | Returned by all scheduler methods; users cancel and inspect jobs |
| `AppTestHarness` | `hassette.test_utils` | Primary test utility; Tier 1 public API |
| `RecordingApi` | `hassette.test_utils` | Returned as `harness.api_recorder`; users assert against it |
| `ApiCall` | `hassette.test_utils` | Returned by `get_calls()`; users inspect it |
| `DrainFailure` | `hassette.test_utils` | Base exception for test drain errors |
| `DrainError` | `hassette.test_utils` | Concrete drain exception |
| `DrainTimeout` | `hassette.test_utils` | Concrete drain exception |
| `AppConfigurationError` | `hassette.test_utils` | Raised on harness config validation failure |
| `make_test_config` | `hassette.test_utils` | Advanced test utility; Tier 1 public API |
| `create_state_change_event` | `hassette.test_utils` | Event factory; Tier 1 public API |
| `create_call_service_event` | `hassette.test_utils` | Event factory; Tier 1 public API |
| `make_state_dict` | `hassette.test_utils` | State factory; Tier 1 public API |
| `make_light_state_dict` | `hassette.test_utils` | State factory; Tier 1 public API |
| `make_sensor_state_dict` | `hassette.test_utils` | State factory; Tier 1 public API |
| `make_switch_state_dict` | `hassette.test_utils` | State factory; Tier 1 public API |

#### Explicit exclusions

| Symbol | Reason for exclusion |
|--------|---------------------|
| `hassette.test_utils` Tier 2 symbols (`HassetteHarness`, `create_hassette_stub`, all fixture functions, etc.) | Tier 2: backward-compatible re-exports for Hassette's own test suite; not in `test_utils.__all__`; not intended for end users |
| All `hassette.web.*` modules | Internal web server implementation; not user-facing API |
| `hassette.core.*` (except `Hassette` class itself) | Internal service classes; users never instantiate them directly |
| `hassette.resources.*` | Internal resource infrastructure |
| `hassette.models.states.*` individual state model classes (e.g., `LightState`, `SensorState`) | These auto-register via the state registry; no user-facing API surface beyond what `states` module exposes |

---

## Section 7: Docstring Gap List

For each class/function on the allowlist, this table records docstring coverage. "OK" means at least a one-line summary exists. "MISSING" means no docstring at all. "THIN" means a one-liner exists but parameter docs are absent where non-obvious types are used.

### Core framework

| Class/Function | Location | Status | What's missing |
|----------------|----------|--------|----------------|
| `App` | `app/app.py` | OK | — |
| `AppConfig` | `app/app.py` | OK | — |
| `AppSync` | `app/app.py` | OK | — |
| `only_app` | `app/app.py` | OK | — |
| `Bus` | `bus/bus.py` | OK | — |
| `Bus.Options` | `bus/bus.py:109` | MISSING | Inner config class has no docstring |
| `Bus.on_initialize` | `bus/bus.py:140` | MISSING | Internal lifecycle method; exclude from public reference |
| `Bus.unsubscribe` | `bus/bus.py:259` | MISSING | One-line summary needed |
| `Scheduler` | `scheduler/scheduler.py` | OK | — |
| `Scheduler.on_initialize` | `scheduler/scheduler.py:103` | MISSING | Internal lifecycle method; exclude from public reference |
| `Scheduler.on_shutdown` | `scheduler/scheduler.py:106` | MISSING | Internal lifecycle method; exclude from public reference |
| `ScheduledJob` | `scheduler/classes.py` | OK | — |
| `ScheduledJob.from_arguments` | `scheduler/classes.py:51` | MISSING | Factory classmethod; needs one-line summary |
| `ScheduledJob.first_run_time` | `scheduler/classes.py:60` | MISSING | Property; needs one-line summary |
| `ScheduledJob.next_run_time` | `scheduler/classes.py:65` | MISSING | Property; needs one-line summary |
| `Api` | `api/api.py` | OK | — |
| `Api.on_initialize` | `api/api.py:204` | MISSING | Internal lifecycle method; exclude from public reference |
| `Api.call_service` (overloads) | `api/api.py:393,403` | MISSING | Overloaded method; at minimum the base overload needs a docstring |
| `Api.yield_states` | `api/api.py:330` | MISSING | Generator method; needs one-line summary + yields doc |
| `Hassette` | `core/core.py` | OK | — |
| `HassetteConfig` | `config/config.py` | OK | — |
| `HassetteConfig.settings_customise_sources` | `config/config.py:62` | MISSING | Pydantic-internal override; can exclude from public reference |
| `RawStateChangeEvent` | `events/__init__.py` | OK | — |
| `TaskBucket` | `task_bucket/task_bucket.py` | OK | — |
| `ServiceResponse` | `models/services.py` | OK | — |

### State models

| Class/Function | Location | Status | What's missing |
|----------------|----------|--------|----------------|
| `BaseState` | `models/states/base.py` | OK | — |
| `StringBaseState` | `models/states/base.py` | OK | — |
| `NumericBaseState` | `models/states/base.py` | OK | — |
| `BoolBaseState` | `models/states/base.py` | OK | — |
| `DateTimeBaseState` | `models/states/base.py` | OK | — |
| `TimeBaseState` | `models/states/base.py` | OK | — |

### Conversion / registry

| Class/Function | Location | Status | What's missing |
|----------------|----------|--------|----------------|
| `STATE_REGISTRY` | `conversion/state_registry.py` | OK (module-level docstring) | — |
| `TYPE_REGISTRY` | `conversion/type_registry.py` | OK (module-level docstring) | — |
| `TypeConverterEntry` | `conversion/type_registry.py` | OK | — |
| `register_simple_type_converter` | `conversion/__init__.py` | OK | — |
| `register_type_converter_fn` | `conversion/__init__.py` | OK | — |
| `StateRegistry.register` | `conversion/state_registry.py:124` | MISSING | Public method on a public registry object; needs one-line summary |

### Event handling modules

| Class/Function | Location | Status | What's missing |
|----------------|----------|--------|----------------|
| `predicates` module | `event_handling/predicates.py` | OK (module docstring) | Many `summarize` inner methods missing docstrings — internal methods, not user-facing |
| `conditions` module | `event_handling/conditions.py` | OK | — |
| `accessors` module | `event_handling/accessors.py` | OK | — |
| `dependencies` module | `event_handling/dependencies.py` | OK | — |

### test_utils

| Class/Function | Location | Status | What's missing |
|----------------|----------|--------|----------------|
| `AppTestHarness` | `test_utils/app_harness.py` | OK | — |
| `RecordingApi` | `test_utils/recording_api.py` | OK (class) | Many methods (`turn_on`, `turn_off`, `toggle_service`, `call_service`, `set_state`, `fire_event`, `get_state`, `get_states`, `get_entity`, `get_entity_or_none`, `entity_exists`, `get_state_or_none`) have no docstrings |
| `ApiCall` | `test_utils/api_call.py` | OK | — |
| `DrainFailure` | `test_utils/exceptions.py` | OK | — |
| `DrainError` | `test_utils/exceptions.py` | OK | — |
| `DrainTimeout` | `test_utils/exceptions.py` | OK | — |
| `AppConfigurationError` | `test_utils/app_harness.py` | OK | — |
| `make_test_config` | `test_utils/config.py` | OK | — |
| `create_state_change_event` | `test_utils/helpers.py` | OK | — |
| `create_call_service_event` | `test_utils/helpers.py` | OK | — |
| `make_state_dict` | `test_utils/helpers.py` | OK | — |
| `make_light_state_dict` | `test_utils/helpers.py` | OK | — |
| `make_sensor_state_dict` | `test_utils/helpers.py` | OK | — |
| `make_switch_state_dict` | `test_utils/helpers.py` | OK | — |

### Docstring gap summary

**High-priority gaps** (public methods users call directly; WP08 should address these):

1. `Bus.unsubscribe` — missing docstring; users call this to remove listeners.
2. `Api.call_service` overloads — missing docstring on one or both overloads; core API method.
3. `Api.yield_states` — missing docstring; generator method with non-obvious return type.
4. `RecordingApi` methods (12 methods) — missing docstrings on every method; `RecordingApi` is a primary test_utils public API surface.
5. `StateRegistry.register` — public method that users call when defining custom state classes.
6. `ScheduledJob.from_arguments`, `first_run_time`, `next_run_time` — missing on a class users inspect.

**Low-priority / exclude** (internal lifecycle methods that are on the class but not user-facing):
`Bus.on_initialize`, `Scheduler.on_initialize`, `Scheduler.on_shutdown`, `Api.on_initialize`, `HassetteConfig.settings_customise_sources`.

---

## Section 8: `mkdocs build --strict` Readiness

### Build baseline

`mkdocs build` (non-strict) was run and completed successfully with **no errors**.

**Existing warnings (verbatim build output excerpt):**

```
WARNING  -  griffe: src/hassette/api/api.py:253: No type or annotation for parameter 'kwargs'
WARNING  -  griffe: src/hassette/api/api.py:266: No type or annotation for parameter 'kwargs'
WARNING  -  griffe: src/hassette/api/api.py:278: No type or annotation for parameter 'kwargs'
WARNING  -  griffe: src/hassette/api/api.py:427: No type or annotation for parameter '**data'
WARNING  -  griffe: src/hassette/api/sync.py:95: No type or annotation for parameter 'kwargs'
WARNING  -  griffe: src/hassette/api/sync.py:108: No type or annotation for parameter 'kwargs'
WARNING  -  griffe: src/hassette/api/sync.py:120: No type or annotation for parameter 'kwargs'
WARNING  -  griffe: src/hassette/api/sync.py:209: No type or annotation for parameter '**data'
WARNING  -  griffe: src/hassette/core/app_lifecycle_service.py:63: No type or annotation for received value 1
WARNING  -  griffe: src/hassette/core/websocket_service.py:299: No type or annotation for parameter '**data'
WARNING  -  griffe: src/hassette/event_handling/accessors.py:263: Failed to get 'name: description' pair from ...
WARNING  -  griffe: src/hassette/event_handling/predicates.py:489: Failed to get 'warning: description' pair from ...
WARNING  -  griffe: src/hassette/resources/base.py:201: No type or annotation for parameter '**kwargs'
WARNING  -  griffe: src/hassette/state_manager/state_manager.py:256: Failed to get 'exception: description' pair from ...
WARNING  -  griffe: src/hassette/test_utils/recording_api.py:452: No type or annotation for parameter '**kwargs'
WARNING  -  griffe: src/hassette/test_utils/helpers.py:109,142,165: No type or annotation for parameter '**kwargs'
WARNING  -  griffe: src/hassette/utils/source_capture.py:80: Confusing indentation for continuation line ...
INFO     -  Pages in docs directory not in nav: pages/core-concepts/configuration/snippets/file_discovery.md
```

Build time: 21 seconds. No link errors, no missing snippet files, no unresolved pages.

### What would fail under `--strict`

Every griffe `WARNING` above becomes a build error under `--strict`. These warnings come from:

1. **`**kwargs` without type annotations** — griffe reports these because the `google` docstring style expects typed parameters. These are in internal implementation methods and are not blockers for the public reference, but `--strict` would fail on them.

2. **Malformed docstring section headers** — `Failed to get 'name: description' pair` and similar messages indicate docstring sections that don't follow Google style precisely. WP08 should fix these.

3. **Pages not in nav** — `pages/core-concepts/configuration/snippets/file_discovery.md` is a snippet fragment that is intentionally not in the nav (it's included via `--8<--`). Under `--strict` this is a warning, not an error, so it does not block the build.

**Conclusion:** `mkdocs build --strict` would currently fail due to griffe annotation warnings. These are addressed by WP08 (docstring improvements) and WP10 (gen_ref_pages allowlist filtering, which will reduce the set of modules griffe processes). WP11 is the final `--strict` validation gate.

### Public/internal decision: `STATE_REGISTRY`, `TYPE_REGISTRY`, `TypeConverterEntry`, `register_*` functions

These four items are in `hassette.__all__` and have dedicated Advanced pages (`pages/advanced/state-registry.md`, `pages/advanced/type-registry.md`). The question (from spec FR#3) is whether to treat them as **public API** with documented reference entries or as **implementation detail** that is documented conceptually but not auto-generated.

**Decision: PUBLIC API — include in the API reference allowlist.**

Rationale:
- All four are in `hassette.__all__`, making them unambiguously public by Python convention.
- `STATE_REGISTRY` and `TYPE_REGISTRY` are module-level objects that users interact with directly when defining custom state classes (via the `register` method).
- `TypeConverterEntry` is returned by `TYPE_REGISTRY` lookup operations; users inspect its fields.
- `register_simple_type_converter` and `register_type_converter_fn` are functions users call. They are documented with examples in the Advanced pages.
- The Advanced pages provide the conceptual explanation; the API reference provides the authoritative parameter-level documentation.

**WP08** (docstring WP): fill the `StateRegistry.register` gap identified in Section 7.
**WP10** (gen_ref_pages WP): emit `::: hassette.conversion` stub that covers `STATE_REGISTRY`, `TYPE_REGISTRY`, `TypeConverterEntry`, and the `register_*` functions.

---

*End of nav audit. Awaiting author approval before content WPs begin.*
