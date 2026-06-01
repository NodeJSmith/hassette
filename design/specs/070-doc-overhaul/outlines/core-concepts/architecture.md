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

### H2: Service Dependency Graph
How `depends_on` works, initialization/shutdown order, cycle detection. Framework dependency graph diagram.

### H2: Deep Dive
Links to each core concept page.

## Snippet Inventory

No code snippets — diagrams are inline Mermaid.

## Cross-Links

- **Links to:** All core concept subsection overviews, System Internals
- **Linked from:** Home page, Getting Started (next steps)
