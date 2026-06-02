# Architecture

**Status:** Exists (245 lines), structure needs JTBD redesign
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept (landing page)
**Reader's job:** Understand how Hassette is structured so they know which parts to learn and where their code fits.

## What was cut (and where it goes)

The existing page has two audiences fighting each other. App authors want to know
"what objects do I interact with?" and "how do they connect?" Framework contributors
want `depends_on` mechanics, wave ordering, cycle detection, and the full dependency
graph. The contributor content now lives in System Internals (internals/index.md).

Removed from this page:
- `depends_on` code example, wave-based ordering explanation, cycle detection,
  framework dependency graph Mermaid diagram, `EventStreamService` note, coordinator
  gate vs service dependency. All moved to internals/index.md.
- `index_depends_on.py` snippet — moves to internals/index.md.

What stays: the three Mermaid diagrams (high-level flow, core services, per-app
handles) — these answer the reader's actual question. The internal services list
stays as a collapsible section since it helps when reading debug logs.

## Outline

### H2: Hassette Architecture
Opening paragraph: what Hassette is and what it connects to. One sentence each for
apps, events, and resources — the three concepts from the current opening.

### H2: What Each App Gets
The four handles (Api, Bus, Scheduler, States) as a bulleted list with one-line
descriptions. This is the most important content on the page — it tells the reader
what objects they interact with. Mermaid diagram 3 (per-app handles) goes here,
directly after the list.

### H2: How It Fits Together
Mermaid diagram 1 (HA <-> Hassette <-> Apps) and diagram 2 (core services). Brief
prose connecting them. The internal services collapsible section goes under diagram 2.

### H2: Startup
One sentence: Hassette starts services in dependency order — the four handles are
ready by the time `on_initialize` runs. Link to System Internals for the full
dependency graph and wave ordering.

### H2: Deep Dive
Links to each core concept page and to System Internals. Collapsible section for
advanced topics (DI, type registry, state registry, custom states).

## Snippet Inventory

No code snippets — diagrams are inline Mermaid. The `index_depends_on.py` snippet
moves to internals/index.md.

## Cross-Links

- **Links to:** Apps, Bus, Scheduler, API, States, Configuration, Web UI, System Internals, API Reference
- **Linked from:** Home page, Getting Started (next steps)
