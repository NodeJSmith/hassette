---
task_id: "T08"
title: "Write Core Concepts — Scheduler, States, API, Cache, Config"
status: "planned"
depends_on: ["T04"]
implements: ["FR#1", "FR#2", "FR#9", "AC#1", "AC#11"]
---

## Summary

Writes the second half of Core Concepts from blank: Scheduler (overview, methods, management), States (overview plus depth pages rehomed from Advanced — no DomainStates Reference page, killed in audit), API (overview, entities, services, utilities, managing-helpers), Cache (overview, patterns), and Configuration (overview, applications — auth absorbed into overview, global replaced by auto-generated reference). The States subsection is the most structurally changed — it gains depth pages matching the Bus pattern and absorbs Custom States, State Registry, and Type Registry from the eliminated Advanced section.

## Prompt

Work on the `docs/overhaul` branch. Before writing, read:
- `design/specs/070-doc-overhaul/docs-context.md` (calibration artifact)
- `design/specs/070-doc-overhaul/outlines/core-concepts/` (Phase 2 outlines — each contains H2/H3 headings with descriptions, named snippet inventory with keep/rewrite/new status, and cross-links)
- The concept exemplar page from T03 (voice reference)
- `.claude/rules/voice-guide.md` and `.claude/rules/doc-rules.md`

### Pages to write (~15):

**Scheduler (3 pages):**
- `core-concepts/scheduler/index.md` — Task scheduling overview, trigger types, the `schedule()` entry point
- `core-concepts/scheduler/methods.md` — `run_in()`, `run_once()`, `run_every()`, `run_daily()`, `run_cron()`, custom triggers
- `core-concepts/scheduler/management.md` — Job groups, `cancel_group()`, `list_jobs()`, jitter

**States (5 pages):**
- `core-concepts/states/index.md` — State access overview, domain access, type conversion. Opens with prose then diagram (not diagram-first). Built-in State Types section shows 2-3 examples and links to auto-generated API reference (no hand-written reference table).
- `core-concepts/states/subscribing.md` (new) — "Subscribing to State Changes" depth page
- `core-concepts/states/custom-states.md` (from advanced/) — Custom state classes
- `core-concepts/states/state-registry.md` (from advanced/) — STATE_REGISTRY
- `core-concepts/states/type-registry.md` (from advanced/) — TYPE_REGISTRY
- ~~`domain-states.md`~~ — **Killed in outline audit.** Auto-generated API reference (`hassette.models.states` in `PUBLIC_MODULES`) serves as the authoritative domain state reference.

**API (5 pages):**
- `core-concepts/api/index.md` — REST/WebSocket interface overview
- `core-concepts/api/entities.md` — Entity access, get_state, get_states
- `core-concepts/api/services.md` — call_service, fire_event
- `core-concepts/api/utilities.md` — set_state, utility methods
- `core-concepts/api/managing-helpers.md` (moved from advanced/) — Creating and managing HA helpers

**Cache (2 pages):**
- `core-concepts/cache/index.md` — Persistent disk-based storage, basic usage
- `core-concepts/cache/patterns.md` — Rate limiting, counters, complex data, expiry

**Configuration (2 pages):**
- `core-concepts/configuration/index.md` — Configuration overview: sources, file locations, authentication (absorbed from former `auth.md`), section map, and brief field design notes for 7 topics (data dir, app discovery, event filtering, dev/debug, web API, cache, state proxy polling). Field-level reference deferred to auto-generated `HassetteConfig` docs. WebSocket resilience and timeout tuning moved to Operating/overview.
- `core-concepts/configuration/applications.md` — App registration in hassette.toml, manifests, multi-instance
- ~~`global.md`~~ — **Replaced by auto-generated reference.** Teaching content absorbed into overview's field notes.
- ~~`auth.md`~~ — **Absorbed into overview** Authentication section.

### Voice: same as T07

System-as-subject, no "you," declarative, 10–18 words per sentence. See T07 for the full voice reference.

### States subsection (FR#9):

This subsection gains the most structure. The new depth pages must match the Bus pattern:
- Overview page introduces the concept and links to depth pages
- Each depth page goes deep on one aspect
- Custom States, State Registry, and Type Registry are rehomed from Advanced — rewrite the content, don't just move the files. The Advanced voice may not match the concept page standard.

### Snippet migration:

The 60 advanced snippets include files for custom-states, state-registry, and type-registry. These move to `core-concepts/states/snippets/`. The Phase 2 outline (T04) has the specific mapping. Ensure `--8<--` include paths are updated.

## Focus

**Scheduler snippets:** 22 files in `docs/pages/core-concepts/scheduler/snippets/`.

**States currently has 1 page and 4 snippets.** This task expands it to 4–5 pages with significant new content. The 60 advanced snippets are the main source of reusable code — but they need rewriting to match concept-page voice.

**API snippets:** 14 files. Managing-helpers moves from advanced to API — its snippets move too.

**Cache snippets:** 9 files including basic usage, rate limiting, counters, complex data, expiry, performance.

**Configuration has a .md snippet** (`file_discovery.md`) in its snippets directory — this is excluded from rendering by `exclude_docs` but is referenced by the configuration page as an include.

## Verify

- [ ] FR#1: All pages pass every item on the voice audit checklist (in `docs-context.md`)
- [ ] FR#2: All concept pages use system-as-subject voice — no "you" outside getting-started/recipe content
- [ ] FR#9: States subsection has overview page, "Subscribing to State Changes" depth page, plus Custom States, State Registry, and Type Registry. No DomainStates Reference page — auto-generated API reference covers this.
- [ ] AC#1: Voice audit checklist applied and all items pass
- [ ] AC#11: States subsection in `mkdocs.yml` matches the required structure with overview + depth pages + extension pages
