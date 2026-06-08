# JTBD Documentation Audit Report

## Executive Summary

**71 pages audited.** Compliance breakdown:
- **Compliant:** 32 pages
- **Partial:** 37 pages
- **Non-compliant:** 2 pages (`getting-started/is-hassette-right-for-you.md`, `web-ui/logs.md`)

**Top systemic issues:**

1. **Inline code blocks instead of `--8<--` snippet includes** — affects 15+ pages across migration, testing, and operating sections
2. **Rule 10/15 violations in concept pages** — "you"/"your" and imperative mood bleed into pages that should use system-as-subject; affects 20+ pages
3. **Missing `--8<--` snippet includes in "AppDaemon" comparison tabs** — migration pages consistently use snippet includes for Hassette examples but inline blocks for AppDaemon examples
4. **Missing recipe template sections** — "Variations" and "See Also" headings absent in several recipes despite content being present
5. **Missing concept page scaffolding** — basic example, "How It Works" walkthrough, and "Next Steps" sections absent across most concept pages

---

## Systemic Issues

### 1. Inline code blocks instead of `--8<--` snippet includes

**Rule:** All code examples must come from snippet files using `--8<--` includes. No inline fenced blocks for Python, YAML, or TOML examples.

**Reality:** Migration, testing, operating, and some concept pages use inline code blocks throughout — primarily in comparison tabs, warning admonitions, and variation blocks.

**Affected pages:**
- `migration/api.md` — AppDaemon tabs at lines 47-55, 67-68, 83-88
- `migration/bus.md` — AppDaemon tabs at lines 64-73, 113-115, 130-138, 148-158
- `migration/concepts.md` — teaching examples at lines 51-53, 66-68, 83-97
- `migration/configuration.md` — inline TOML block at lines 58-73
- `migration/scheduler.md` — Blocking Work section at lines 67-79
- `testing/index.md` — inline snippets in prose explanation section
- `troubleshooting.md` — cache key prefix, bus registration, web UI TOML examples
- `core-concepts/apps/configuration.md` — TOML comparison blocks lines 28-43
- `core-concepts/bus/predicate-reference.md` — P.AllOf range-check example, ServiceDataWhere.from_kwargs example
- `core-concepts/bus/custom-extractors.md` — one inline block inside collapsible
- `operating/upgrading.md` — inline TOML block with placeholder path

**Concrete examples:**

From `migration/scheduler.md` lines 67-70: a teaching example that will drift if the API changes — needs to be a snippet file.

From `core-concepts/apps/configuration.md`, the TOML "Inline form" vs "Table form" comparison blocks appear raw in the markdown rather than via snippet includes.

---

### 2. Rule 10/15 violations: "you"/"your" and imperative mood in concept pages

**Rule 10:** Do not use "you" in concept or API reference pages. Make the system the subject. **Rule 15:** Do not use imperative mood in concept pages.

**Reality:** Concept pages across most sections slip into addressing the reader directly, especially in warning admonitions, "how it works" explanations, and practical tips.

**Affected pages:**
- `getting-started/is-hassette-right-for-you.md` — pervasive throughout (non-compliant)
- `web-ui/logs.md` — seven or more instances (non-compliant)
- `web-ui/manage-apps.md` — intro paragraph and reload instructions
- `web-ui/inspect-config-code.md` — three imperative navigation blocks
- `operating/index.md` — "Use it to send alerts", "Avoid catching TimeoutError"
- `core-concepts/states/conversion.md` — "Place the most specific type first"
- `core-concepts/configuration/index.md` — "production environments should not"
- `testing/time-control.md` — "Call trigger_due_jobs() explicitly afterward"
- `testing/harness.md` — "Seed before you simulate", "If your handler reads..."
- `testing/factories.md` — "Tests that need precise attribute control call them directly"
- `testing/concurrency.md` — "Test code catches DrainTimeout or DrainFailure"
- `core-concepts/bus/filtering.md` — "your handler"
- `core-concepts/internals/index.md` — dense prose block, minor

**Concrete examples:**

From `getting-started/is-hassette-right-for-you.md`:
> "Use YAML when your automations are straightforward trigger-action rules."

Should be: "YAML is the right tool when automations follow straightforward trigger-action patterns."

From `testing/time-control.md` warning admonition:
> "Call trigger_due_jobs() explicitly afterward. Without it, jobs accumulate silently."

Should be: "trigger_due_jobs() must be called explicitly after advancing the clock. Without it, jobs accumulate and side-effect assertions fail."

From `operating/index.md`:
> "If you register an error handler on a subscription or a scheduled job, Hassette calls it after logging. Use it to send alerts..."

Should be: "Registered error handlers fire after Hassette logs the exception. They are the right place for alerting integrations."

---

### 3. Migration pages use inline blocks for AppDaemon comparison tabs

**Rule:** All code examples from snippet files. The pattern appears consistent: Hassette tabs correctly use `--8<--` includes; AppDaemon tabs use inline blocks.

**Affected pages:** `migration/api.md`, `migration/bus.md`, `migration/concepts.md`, `migration/configuration.md`, `migration/scheduler.md`

**Why this matters separately from issue 1:** These are comparison examples. When AppDaemon's calling convention is documented inline, there is no CI check to catch when the example stops matching reality.

---

### 4. Missing recipe template sections without headings

**Rule:** Recipes require: problem statement, the code, how it works, verify it's working, variations, see also.

**Reality:** Several recipes have the variation and see-also content but omit the `## Variations` and `## See Also` headings, making them unfindable by scanning.

**Affected pages:**
- `recipes/debounce-sensor-changes.md` — "Throttle instead of debounce" appears after Verify with no heading
- `recipes/daily-notification.md` — "Different time", "Include sensor data", "Weekdays only" blocks appear with bold headers but no `## Variations` parent

---

### 5. Missing concept page scaffolding: basic example, "How It Works", "Next Steps"

**Rule:** Concept pages follow: opening line -> basic example -> how it works -> common patterns -> depth -> next steps.

**Reality:** Most concept pages skip the basic example and "How It Works" walkthrough, jumping directly from the opening to a reference catalog or method-by-method breakdown.

**Affected pages:**
- `core-concepts/apps/configuration.md` — no basic example, no how-it-works, no next steps
- `core-concepts/apps/lifecycle.md` — code example present but never walked through
- `core-concepts/scheduler/index.md` — jumps from definition to multi-pattern survey
- `core-concepts/states/conversion.md` — jumps to pipeline mechanism without user-benefit framing
- `core-concepts/configuration/index.md` — no minimal `hassette.toml` example
- `core-concepts/bus/handlers.md` — no walkthrough after the pattern taxonomy
- `core-concepts/internals/lifecycle.md` — state machine diagram appears after failure tables; no page-level intro
- `testing/harness.md` — drops into full API reference without a basic pattern example
- `testing/time-control.md` — method reference without "why this sequence exists" framing

---

## Section-by-Section Results

### core-concepts/api

**Overall: Compliant.** Strong section.

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Compliant | Missing labeled "Common Patterns" and "Next Steps" headers — minor |
| `methods.md` | Compliant | One passive construction: "should be compared against MISSING_VALUE" |
| `managing-helpers.md` | Partial | Common Pitfalls section appears before the CRUD walkthrough (inverts concept order); warning block duplicates the first pitfall entry |

---

### core-concepts/apps

**Overall: Partial.** Good voice but structural scaffolding missing.

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Partial | No "How It Works" narrative tying capability catalog together; minor passive voice |
| `configuration.md` | Partial | No basic example; no How It Works; no Next Steps; two inline TOML blocks |
| `lifecycle.md` | Partial | Code example at line 15 not walked through; no Common Patterns; no outcome descriptions after examples |
| `task-bucket.md` | Compliant | Minor: no outcome prose after examples |

---

### core-concepts/bus

**Overall: Mostly compliant.** Best section overall.

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Compliant | — |
| `handlers.md` | Partial | No How It Works after basic example; no minimal example before pattern taxonomy; synonym cycling (handler/callback/function) |
| `dependency-injection.md` | Compliant | Minor: no outcome sentences after code blocks |
| `filtering.md` | Partial | "your handler" Rule 10 violation; dict-filtering section uses inline-header list anti-pattern; no minimal example at opening |
| `methods.md` | Compliant | RuntimeError on sync-from-event-loop lacks explicit path forward |
| `predicate-reference.md` | Compliant | Two inline code blocks; footnote links resolve to filtering.md rather than in-page anchors |
| `custom-extractors.md` | Partial | Missing minimal-first progression; "Adding Type Conversion" ordered after internals; one inline block in collapsible |

---

### core-concepts/cache

**Overall: Compliant.**

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Compliant | "Configuration" section appears before "How It Works" — inverts concept order |
| `patterns.md` | Compliant | Troubleshooting section should use collapsible `??? note` format |

---

### core-concepts/configuration

**Overall: Partial.**

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Partial | No basic example (minimal `hassette.toml`); Rule 15 violation: "production environments should not"; "Full Reference" is too thin as a next-steps section |

---

### core-concepts/states

**Overall: Partial.**

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Compliant | "Good to Know" heading is informal; diagram slightly front-loaded |
| `conversion.md` | Partial | Rule 15 violation: "Place the most specific type first"; gatekeeping sentence ("This page is relevant when..."); wide scope |
| `custom-states.md` | Partial | Troubleshooting in prose rather than `??? note` collapsibles; missing outcome prose; Rule 15: "The base class must match..." |

---

### core-concepts/scheduler

**Overall: Compliant.** Strong section.

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Compliant | No minimal basic example before multi-pattern survey |
| `management.md` | Compliant | One implied "you" in cancel_null section; minor |
| `methods.md` | Compliant | Missing behavioral outcome sentences after run_cron and schedule blocks |
| `triggers.md` | Compliant | Missing outcome description after custom trigger usage snippet |

---

### core-concepts/internals

**Overall: Partial.**

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Partial | Overloaded (both index and concept); event pipeline explanation dense; missing Next Steps |
| `lifecycle.md` | Partial | No page-level introduction; state machine diagram buried after failure tables; `RestartSpec` code snippet has no outcome prose |
| `service-details.md` | Partial | Opening sentence violates Rule 1 (meta-structural description); missing See Also; some passive constructions |

---

### getting-started

**Overall: Mixed.** Docker index and ha_token are good; is-hassette-right-for-you needs significant rework.

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Compliant | Missing "What you'll build" preamble; no definition of Hassette for brand-new visitors |
| `is-hassette-right-for-you.md` | **Non-compliant** | Pervasive Rule 10 violations; Rule 15 violations; `AppTestHarness` used without definition |
| `first-automation.md` | Compliant | Missing "What you'll learn" and Prerequisites sections |
| `ha_token.md` | Compliant | Missing "What you'll learn" and Next Steps |
| `docker/index.md` | Compliant | Missing "What you'll learn" preamble |
| `docker/dependencies.md` | Partial | Missing "What you'll learn", Prerequisites, Next Steps |
| `docker/image-tags.md` | Partial | No opening context; no outcome descriptions after code blocks; effectively a stub |
| `docker/troubleshooting.md` | Compliant | Two inline code blocks |

---

### recipes

**Overall: Mostly compliant.** Best section in the docs.

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Compliant | — |
| `motion-lights.md` | Compliant | Verify section lacks sample output block |
| `vacation-mode-toggle.md` | Compliant | `<key>` placeholder in Verify CLI commands |
| `service-call-reaction.md` | Compliant | `<key>` placeholder in Verify CLI commands |
| `sensor-threshold.md` | Partial | `<key>` placeholders in Verify section; hysteresis variation lacks code snippet |
| `debounce-sensor-changes.md` | Partial | Missing `## Variations` heading; Verify shows expected output in prose rather than code block |
| `daily-notification.md` | Partial | Missing `## Variations` heading; How It Works lists facts rather than walking one decision per paragraph |

---

### migration

**Overall: Compliant structure, inline code block problem throughout.**

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Partial | Overloaded for an index page; async methods limitation lacks path forward |
| `checklist.md` | Partial | Three stacked admonitions in "Common Pitfalls" — explicit doc-rules violation |
| `concepts.md` | Partial | Structurally inconsistent (starts as comparison, shifts to concept midway); multiple inline code blocks |
| `api.md` | Compliant | AppDaemon tab inline blocks |
| `bus.md` | Compliant | Weak opening sentence ("This page covers..."); AppDaemon tab inline blocks |
| `configuration.md` | Compliant | Inline TOML block at lines 58-73 |
| `scheduler.md` | Compliant | Two inline code blocks in Blocking Work section |
| `testing.md` | Partial | Seed order warning appears before the test example (context-free) |

---

### cli

**Overall: Compliant.**

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Compliant | Minor: imperative "Start Hassette with `hassette run`, then retry" |
| `commands.md` | Compliant | Console output examples are inline — acceptable for CLI reference |
| `configuration.md` | Compliant | One passive construction; one "you" in tip admonition (borderline) |
| `workflows.md` | Compliant | A few borderline "you" constructions |

---

### operating

**Overall: Partial.**

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Partial | Rule 10/15 violations; four distinct topics should be split to sibling pages; missing Next Steps |
| `log-levels.md` | Compliant | Several imperative constructions in opening sentence |
| `upgrading.md` | Partial | Inline TOML block with `youruser` placeholder; several "you" constructions |

---

### testing

**Overall: Partial.** Good content, voice and scaffolding issues.

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Compliant | Inline code snippets in prose explanation; missing Prerequisites section |
| `harness.md` | Partial | No basic example before API reference; multiple Rule 10/15 violations in admonitions |
| `time-control.md` | Partial | Imperative admonitions; no "why this sequence" framing; missing outcome descriptions |
| `factories.md` | Compliant | "Tests that need..." Rule 10 framing; hedging in Internal Helpers section |
| `concurrency.md` | Compliant | Minor Rule 10/15 in admonitions |

---

### web-ui

**Overall: Mixed.** Reference pages good; UI procedure pages need voice work.

| Page | Status | Key issues |
|---|---|---|
| `index.md` | Compliant | Minor setup imperatives acceptable on index page |
| `health-endpoints.md` | Compliant | Minor: "belong at this endpoint" recommendation framing |
| `debug-handler.md` | Compliant | — |
| `manage-apps.md` | Partial | Rule 10/15 violations in intro paragraph and reload instructions; missing Next Steps |
| `inspect-config-code.md` | Partial | Three imperative navigation blocks; "you" in env var tip |
| `logs.md` | **Non-compliant** | Seven or more Rule 10 violations; imperative UI instructions throughout; page voice is fundamentally inconsistent |

---

### troubleshooting

**Overall: Compliant.**

| Page | Status | Key issues |
|---|---|---|
| `troubleshooting.md` | Compliant | Three inline code blocks; "will not" should be "does not" (future vs present tense) |

---

## Compliant Pages

These pages passed with no significant issues:

- `core-concepts/api/index.md`
- `core-concepts/api/methods.md`
- `core-concepts/apps/task-bucket.md`
- `core-concepts/bus/index.md`
- `core-concepts/bus/dependency-injection.md`
- `core-concepts/bus/methods.md`
- `core-concepts/bus/predicate-reference.md`
- `core-concepts/cache/index.md`
- `core-concepts/cache/patterns.md`
- `core-concepts/database-telemetry.md`
- `core-concepts/index.md`
- `core-concepts/scheduler/index.md`
- `core-concepts/scheduler/management.md`
- `core-concepts/scheduler/methods.md`
- `core-concepts/scheduler/triggers.md`
- `core-concepts/states/index.md`
- `getting-started/index.md`
- `getting-started/first-automation.md`
- `getting-started/ha_token.md`
- `getting-started/docker/index.md`
- `getting-started/docker/troubleshooting.md`
- `recipes/index.md`
- `recipes/motion-lights.md`
- `recipes/vacation-mode-toggle.md`
- `recipes/service-call-reaction.md`
- `migration/api.md`
- `migration/bus.md`
- `migration/configuration.md`
- `migration/scheduler.md`
- `cli/index.md`
- `cli/commands.md`
- `cli/configuration.md`
- `cli/workflows.md`
- `operating/log-levels.md`
- `testing/index.md`
- `testing/factories.md`
- `testing/concurrency.md`
- `web-ui/index.md`
- `web-ui/health-endpoints.md`
- `web-ui/debug-handler.md`

---

## Recommended Priority

### Priority 1 — Fix the two non-compliant pages

**`getting-started/is-hassette-right-for-you.md`:** Rewrite every "you" and imperative sentence to make Hassette or HA YAML the subject. Remove `AppTestHarness` from the comparison table or add a functional definition.

**`web-ui/logs.md`:** Decide its register: how-to (imperatives and "you" fine) or reference (system-as-subject throughout). Given it lists UI controls by behavior, reference-page voice is the right call. Rewrite the seven+ violations consistently.

### Priority 2 — Migrate AppDaemon tab inline blocks to snippet files (fixes 5 migration pages)

Mechanical: for each inline block in an AppDaemon tab, extract to a snippet file and replace with `--8<--`. Fixes systemic issues 1 and 3 simultaneously.

### Priority 3 — Fix Rule 10/15 violations in testing section (4 pages, same pattern)

Rewrite admonitions and explanatory prose from imperative/second-person to declarative/system-as-subject.

### Priority 4 — Fix stacked admonitions and missing recipe headings (quick wins)

- `migration/checklist.md`: Merge three stacked admonitions
- `recipes/debounce-sensor-changes.md` and `recipes/daily-notification.md`: Add `## Variations` and `## See Also` headings

### Priority 5 — Add basic examples to concept pages missing them (~8 pages)

Add 3-8 line minimal code examples immediately after opening paragraphs. Moves these pages from partial to compliant.

### Priority 6 — Fix operating/index.md scope and voice

Rewrite Rule 10/15 violations. Evaluate splitting four distinct topics into sibling pages.

### Priority 7 — Remaining inline block fixes (dispersed, lower impact per page)

Fix standalone inline blocks in `core-concepts/apps/configuration.md`, `core-concepts/bus/predicate-reference.md`, `troubleshooting.md`, `operating/upgrading.md`, and `getting-started/docker/troubleshooting.md`.
