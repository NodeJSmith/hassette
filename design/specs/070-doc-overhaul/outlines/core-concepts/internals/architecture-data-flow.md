# System Internals — Architecture & Data Flow

**Status:** New page (content from current `internals.md` sections 1-3 + content from Architecture page)
**Voice mode:** Concept — system-as-subject, no "you", contributor/deep-dive audience

## Outline

### (Opening — absorbed from internals/overview.md)
Audience declaration: "This section is for contributors to Hassette's core and for advanced users who want to understand the framework's internal architecture. App authors do not need to read this section." Brief index of the three internals pages (Architecture & Data Flow, Lifecycle, Service Details).

### H2: Component Ownership
Which service owns which state. Map of services to the resources they manage.

### H2: Service Dependencies
#### H3: `depends_on` ClassVar
How services declare startup dependencies. Code example (snippet `index_depends_on.py` moving from Architecture).
#### H3: Wave-Based Ordering
Dependency graph partitioned into levels. Each wave starts/shuts down concurrently; waves execute sequentially.
#### H3: Cycle Detection
`ValueError` with full cycle path at construction time.
#### H3: Framework Dependency Graph
Mermaid diagram showing all built-in services by startup wave (moving from Architecture page).

### H2: Event and Data Flow
How events travel from HA WebSocket → EventStreamService → BusService → listener dispatch → handler invocation.

### H2: EventStreamService Constructor-Time Dependency
Structural ordering via child registration order, not `depends_on`.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `index_depends_on.py` | Move from `core-concepts/snippets/` | `depends_on` ClassVar example |

## Cross-Links

- **Links to:** Per-Service Internals, Lifecycle & Supervision, Architecture (back-link)
- **Linked from:** Architecture (deep dive), each core concept overview
