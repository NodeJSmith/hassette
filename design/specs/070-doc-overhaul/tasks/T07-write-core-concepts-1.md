---
task_id: "T07"
title: "Write Core Concepts — Apps, Bus, Architecture, Internals"
status: "planned"
depends_on: ["T04"]
implements: ["FR#2", "FR#5", "FR#11", "FR#12", "AC#9", "AC#14", "AC#15"]
---

## Summary

Writes the first half of Core Concepts from blank: Architecture overview (the "five handles" model, app-author only), Apps subsection (overview, lifecycle, configuration, task-bucket), Bus subsection (overview, handlers, filtering, dependency-injection), Internals page, and database-telemetry page. The Bus subsection is critical because it contains the DI canonical page — the single authoritative source for dependency injection documentation. Architecture is scoped strictly to app-authors; contributor/maintainer content goes to Internals.

## Prompt

Work on the `docs/overhaul` branch. Before writing, read:
- `design/specs/070-doc-overhaul/docs-context.md` (calibration artifact)
- `design/specs/070-doc-overhaul/outlines/core-concepts/` (Phase 2 outlines for each page)
- The concept exemplar page from T03 (voice reference for system-as-subject)
- `.claude/rules/voice-guide.md` and `.claude/rules/doc-rules.md`

### Pages to write (~12):

**Architecture (1 page):**
- `core-concepts/index.md` — The "five handles" model: Bus, Scheduler, Api, StateManager, Cache. How apps work. App-author audience ONLY (FR#11).
- **Must NOT contain:** dependency graphs, wave ordering, cycle detection, internal service names (AC#14). These go in Internals.

**Apps (4 pages):**
- `core-concepts/apps/index.md` — What an App is, the five handles available via `self.*`, how to create one
- `core-concepts/apps/lifecycle.md` — `on_initialize`, `on_ready`, `on_shutdown` hooks
- `core-concepts/apps/configuration.md` — `AppConfig`, `SettingsConfigDict`, env prefix
- `core-concepts/apps/task-bucket.md` — Background task management

**Bus (4 pages):**
- `core-concepts/bus/index.md` — Event pub/sub overview, subscription methods, what fires when
- `core-concepts/bus/handlers.md` — Handler signatures, async handlers, error handling
- `core-concepts/bus/filtering.md` — Predicates (P), Conditions (C), Accessors (A), glob patterns, debounce, throttle
- `core-concepts/bus/dependency-injection.md` — THE canonical DI page (FR#5). Full explanation of `D.*` annotations, typed state injection, how Hassette resolves parameters. All other pages that mention DI compress to one sentence + link to this page.

**Internals (1 page):**
- `core-concepts/internals.md` — Dependency graphs, wave ordering, cycle detection, internal service names, Resource hierarchy (FR#12, AC#15). Contributor/maintainer audience.

**Database-telemetry (1 page):**
- `core-concepts/database-telemetry.md` — Telemetry DB schema, retention, what's tracked

### Voice for this section:

- **System-as-subject** — no "you" (voice-guide rule #10). "The bus delivers events" not "you receive events."
- **No imperative mood** in concept pages (rule #15). Use declarative statements.
- **Name → define → show → constrain** for introducing concepts (rule #16).
- **10–18 words per explanatory sentence** (rule #2).

### DI canonical page (FR#5):

This page is the single source of truth for DI in Hassette docs. It must cover:
- What DI is and how Hassette implements it (brief)
- All `D.*` annotations with examples
- How Hassette resolves handler parameters
- Typed state injection (`D.StateNew[states.SunState]`)
- Common patterns and gotchas

After writing this page, grep all other pages for DI references. Each should be compressed to one sentence + link. Example: "Hassette injects typed state objects into handler parameters — see [Dependency Injection](../bus/dependency-injection.md)."

## Focus

**Current Bus snippets:** 53 files in `docs/pages/core-concepts/bus/snippets/`. Many will be rewritten. The Phase 2 outline (T04) has the keep/rewrite/new mapping.

**Current Apps snippets:** 15 files. Includes `apps_cache_counter.py` (cache example).

**Architecture page currently mixes audiences** — has both app-author content (five handles) and maintainer content (dependency graphs, wave ordering). The split is: Architecture gets the five handles model, Internals gets everything else.

**DI is currently explained in:** `core-concepts/bus/dependency-injection.md` (detailed), various getting-started pages (introductory), and scattered references elsewhere. After this task, only the canonical page has the full explanation.

## Verify

- [ ] FR#2: All concept pages use system-as-subject voice — no "you" outside getting-started/recipe content
- [ ] FR#5: `core-concepts/bus/dependency-injection.md` contains the full DI explanation; grep other pages for DI references and confirm each is one sentence + link
- [ ] FR#11: Architecture page covers the five handles model for app-authors only
- [ ] FR#12: Internals page contains dependency graphs, wave ordering, cycle detection, and internal service names
- [ ] AC#9: `core-concepts/bus/dependency-injection.md` is the only page with a full DI explanation
- [ ] AC#14: Architecture page does not mention dependency graphs, wave ordering, cycle detection, or internal service names
- [ ] AC#15: `internals.md` contains dependency graphs, wave ordering, cycle detection, and internal service names
