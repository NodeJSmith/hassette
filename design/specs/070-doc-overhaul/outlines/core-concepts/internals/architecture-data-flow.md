# System Internals — Architecture & Data Flow

**Status:** New page (content from current `internals.md` sections 1-3 + content from Architecture page)
**Voice mode:** Concept — system-as-subject, no "you", contributor/deep-dive audience
**Page type:** Concept (deep-dive, section landing)
**Reader's job:** Trace how data moves through the system — from HA WebSocket to handler invocation and back — to debug event routing issues or understand framework structure.

## What was cut (and where it goes)

The original outline mirrored the source-code structure (component ownership, then
dependencies, then data flow). The reader arriving here from the Architecture page
already knows the high-level components. Their question is "how does an event get from
HA to my handler?" — so the data flow pipeline comes first, the dependency mechanics
second.

Component ownership moves from lead section to supporting reference — it answers
"who owns what?" which matters for debugging, not for initial understanding.

## Outline

### (Opening)
Audience statement: this section is for contributors and advanced users who want to
understand the framework's internals. App authors do not need to read this section.
Brief index of the three internals pages (this page, Lifecycle, Service Details).

### H2: Event Pipeline
How events travel from HA WebSocket through the system to handler invocation:
WebsocketService (receive) -> EventStreamService (memory channel) ->
BusService (topic expand + filter) -> CommandExecutor (invoke + record) -> handler.
Outbound path: handler -> Api -> ApiResource (REST) / WebsocketService (WS send) -> HA.

Existing Mermaid diagram from internals.md section 3. Failure behavior table
(WS disconnect, auth failure, handler timeout, DB write failure).

`StateProxy` priority-100 subscription: cache is always updated before user handlers.

### H2: Service Dependencies
#### H3: `depends_on` ClassVar
How services declare startup dependencies. Code example (snippet `index_depends_on.py`,
moved from Architecture page). Scoping: direct children of `Hassette` only.

#### H3: Wave-Based Ordering
Dependency graph partitioned into topological levels. Each wave starts concurrently;
waves execute sequentially. Shutdown in reverse.

#### H3: Framework Dependency Graph
Full Mermaid diagram showing all built-in services by startup wave (moved from
Architecture page).

#### H3: Cycle Detection
`ValueError` with full cycle path at construction time.

### H2: Component Ownership
Which service owns which state. Resource tree diagram (existing Mermaid from
internals.md section 1). Per-app handles as thin wrappers — cleanup behavior on
app shutdown.

### H2: EventStreamService Constructor-Time Dependency
Structural ordering via child registration order, not `depends_on`. Brief note.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `index_depends_on.py` | Move from `core-concepts/snippets/` | `depends_on` ClassVar example |

## Cross-Links

- **Links to:** Lifecycle & Supervision, Per-Service Internals, Architecture (back-link)
- **Linked from:** Architecture (deep dive), Operating overview
