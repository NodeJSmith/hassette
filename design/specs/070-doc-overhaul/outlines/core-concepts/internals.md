# System Internals

**Status:** Exists (574 lines), splitting into 2-3 pages per user decision
**Voice mode:** Concept — system-as-subject, no "you", contributor/deep-dive audience

## Proposed Split

The current single page covers 10 numbered sections. Split into:

### Page 1: `internals/index.md` — Architecture & Data Flow
Sections 1-3 from current page, plus content moving from Architecture:
- Component Ownership (which service owns which state)
- Service Dependencies (depends_on, initialization order, cycle detection, framework dependency graph Mermaid diagram)
- Event and Data Flow (how events travel through the system)
- Wave-based startup/shutdown ordering
- EventStreamService constructor-time dependency note

The `depends_on` code snippet (`index_depends_on.py`) moves here from Architecture.

### Page 2: `internals/service-details.md` — Per-Service Internals
Sections 4-9 from current page:
- Bus Internals (dispatch, matching, handler invocation)
- Scheduler Internals (trigger evaluation, job execution)
- Database Internals (schema, migrations, unified executions table, sync registration)
- Api Internals (REST/WS interface, connection management)
- StateManager and StateProxy (proxy pattern, domain routing)
- Web/UI Layer (endpoint registration, SSE, static serving)

### Page 3: `internals/lifecycle.md` — Resource Lifecycle & Supervision
Section 10 from current page:
- State Transitions (resource state machine)
- Readiness vs Running
- Wave Startup and Shutdown
- Service Supervision (RestartSpec, RestartType, sliding-window budget, error routing, new statuses)

**Nav update needed:** Change `System Internals: pages/core-concepts/internals.md` to a subsection with 3 entries.

## Snippet Inventory

No code snippets — diagrams and tables. Some Mermaid diagrams may exist inline.

## Cross-Links

- **Links to:** Architecture, each core concept's overview page
- **Linked from:** Architecture (deep dive)
