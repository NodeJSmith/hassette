# Architecture

**Status:** Exists (245 lines), structure solid, voice polish needed
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Hassette Architecture
Opening: what Hassette is and what it connects to. One paragraph.

### H2: Diagrams
Three Mermaid diagrams (existing, keep):
1. High-level flow (HA ↔ Hassette ↔ Apps)
2. Core services inside Hassette
3. What each app gets (the five handles: Bus, Scheduler, Api, StateManager, Cache)

### H2: Startup
One sentence: "Hassette starts services in dependency order — your handles are ready by the time `on_initialize` runs." Links to System Internals for the full dependency graph, wave ordering, and cycle detection.

**Removed from this page (moved to Internals):** `depends_on` code example, wave-based ordering explanation, cycle detection, framework dependency graph Mermaid diagram, EventStreamService note. These are framework plumbing, not app-author concerns.

### H2: Deep Dive
Links to each core concept page.

## Snippet Inventory

No code snippets — diagrams are inline Mermaid. The `index_depends_on.py` snippet moves to System Internals.

## Cross-Links

- **Links to:** All core concept subsection overviews, System Internals
- **Linked from:** Home page, Getting Started (next steps)
