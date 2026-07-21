---
proposal: "Simplify HandlersTab render branching by replacing scattered boolean conditions with a single derived discriminant"
date: 2026-07-21
status: Draft
flexibility: Exploring
motivation: "Readability and extensibility risk from four mutually exclusive render modes controlled by scattered booleans; amplified by the recent addition of the execution-detail mode"
constraints: "Preact frontend using CSS Modules and project design system tokens. No stated timeline constraints."
non-goals: "none stated"
depth: deep
---

# Research Brief: Simplify HandlersTab Render Branching

**Initiated by**: Issue #1376 — "Simplify HandlersTab render branching"

## Context

### What prompted this

A readability review during the execution-detail page work (PR #1375) surfaced that `HandlersTab` branches on four mutually exclusive render modes via scattered boolean conditions. The finding predates the execution-detail feature but was amplified by adding a fourth top-level render branch. The concern is twofold: bug risk from conditions that interact in non-obvious ways, and extensibility friction when adding new modes.

### Current state

`HandlersTab` (`frontend/src/components/app-detail/handlers-tab.tsx`, 184 lines) is a thin orchestrator that receives URL-derived props from `AppDetailPage` and decides what to render. It does not fetch its own data — `listeners` and `jobs` come from the parent page, which queries the API and passes them down.

**The four render modes**, evaluated via sequential early returns and then inline booleans:

| Mode | Condition | Lines | What renders |
|------|-----------|-------|-------------|
| Execution detail | `selectedExecId && parsed` | 115-132 | `ExecutionDetailFetcher` full-width, no master list |
| Empty state | `!hasItems` | 134-140 | `EmptyState` "no handlers or scheduled jobs" |
| Mobile list-only | `isMobile && !selectedHandler` | 148-181 (subset) | `HandlerList` only, no detail pane |
| Mobile detail-only | `isMobile && selectedHandler` | 148-181 (subset) | Detail pane + back button, no list |
| Desktop split | `!isMobile` | 148-181 (subset) | Master list + detail pane side by side |

The last three modes are not separate branches — they share a single JSX return (lines 148-183) gated by three derived booleans:

```
showMobileDetail = isMobile.value && selectedHandler !== null
showMasterList   = !isMobile.value || selectedHandler === null
showDetailPane   = !isMobile.value || selectedHandler !== null
```

A reader must hold `parsed`, `selectedExecId`, `hasItems`, `isMobile.value`, `selectedHandler`, `showMobileDetail`, `showMasterList`, and `showDetailPane` in their head to trace which branch fires for a given URL. The early returns (execution detail, empty state) are clean enough on their own — the reader-load problem concentrates in the mobile/desktop sub-branching within the final return.

**URL mapping**: All three URL-driven states (`/handlers`, `/handlers/:kind/:id`, `/handlers/:kind/:id/exec/:execId`) are already separate `<Route>` entries in `app.tsx` (lines 125-146), but they all render `AppDetailPage` with different params, which passes them to `HandlersTab` as `selectedHandler` and `selectedExecId` props. The mobile/desktop distinction is purely client-side (a `ResizeObserver` on the container div, not a URL param).

**Data derivation chain**: `selectedHandler` (a raw string like `"listener/123"`) is regex-parsed into `parsed: {kind, id} | null`, which is used to look up `selectedListener`/`selectedJob` from the arrays. A `useEffect` auto-corrects the URL when the parsed ID doesn't match any item in the data. This derivation logic is inline in the component body, interleaved with the render branching.

### Key constraints

- **Single consumer**: Only `AppDetailPage` renders `HandlersTab` (confirmed via grep). Blast radius for prop interface changes is minimal.
- **Behavior-based tests**: The 29 tests assert via `data-testid` queries and navigation mock calls, not internal DOM structure. They are resilient to structural refactors that preserve the same rendered output.
- **CSS isolation**: `handlers-tab.module.css` is imported only by this component. Class names are scoped and safe to rename.
- **No route-level code splitting**: All tab components are statically imported — no lazy loading. This is consistent across the app.
- **Container-based breakpoint**: HandlersTab is the only component in the frontend using `ResizeObserver` for mobile detection (every other component uses the viewport-based `useMediaQuery` hook). The comment at line 72 explains why: the tab panel's width varies with sidebar state, independent of viewport width.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| ViewMode derivation + render switch | `handlers-tab.tsx` | Low | Low — pure refactor, same outputs |
| CSS module | `handlers-tab.module.css` | None | None — no structural CSS change needed |
| Tests | `handlers-tab.test.tsx` | Low | Low — behavioral assertions survive structural changes |
| Parent page | `app-detail.tsx` | None | None — prop interface unchanged |

### What already supports this

- **The early-return pattern is half the answer already.** The execution-detail and empty-state branches are clean early returns — the problem is only the last 35 lines where mobile/desktop sub-branching happens via three entangled booleans.
- **`parseSelectedHandler` is already extracted** as a standalone pure function (lines 20-27). The same pattern can be applied to mode derivation.
- **Tests are behavior-based.** The test suite mocks `ExecutionDetailFetcher` and `ExecutionTable` at module boundaries, then asserts on testids and navigation calls. A structural refactor that produces identical rendered output will not break tests.
- **`DetailContent` is already a private helper** (lines 39-58) that selects between listener/job/placeholder rendering. This component-within-a-component pattern can be extended.

### What works against this

- **The component is only 184 lines.** The "scattered boolean" problem, while real, is concentrated in a small region (~35 lines). Any restructuring must earn its diff against the current simplicity.
- **No established multi-mode pattern in the codebase.** Other components use early returns for loading/error/success ladders and inline ternaries for layout variants. No component uses a discriminated union or `switch` for mode selection — adopting one here would be a local convention, not following an existing one.
- **The mobile/desktop split is not a "mode" in the same sense as the others.** Execution detail and empty state are URL-driven, data-driven states. Mobile/desktop is a responsive layout concern. Flattening them into a single discriminant mixes concerns — the container width dimension is orthogonal to the URL-state dimension.

## Options Evaluated

### Option A: ViewMode discriminant (from the issue)

**How it works**: Extract a `deriveViewMode()` function that examines `selectedExecId`, `parsed`, `hasItems`, `isMobile`, and `selectedHandler` and returns a discriminated value from a five-member union type:

```ts
type ViewMode =
  | { mode: "execution-detail"; parsed: ParsedHandler; execId: string }
  | { mode: "empty" }
  | { mode: "mobile-list" }
  | { mode: "mobile-detail"; parsed: ParsedHandler }
  | { mode: "split"; parsed: ParsedHandler | null }
```

The render body becomes a `switch` on `viewMode.mode`, with each case returning its JSX. The derivation is a pure function, independently testable, and self-documenting: the type itself enumerates all possible states.

**Pros**:
- Directly addresses the issue: replaces scattered `if`/boolean chains with a single discriminant
- The type serves as living documentation of all render modes — a reader sees the five cases in one place
- Adding a future mode (e.g., auto-selected handler from #1246) means adding a union member + a switch case, not threading another boolean through existing conditions
- The derivation function is independently unit-testable: `expect(deriveViewMode({...})).toEqual({mode: "split", parsed: null})`
- Existing behavioral tests pass unchanged — the rendered output is identical

**Cons**:
- Mixes two orthogonal concerns (URL-driven state and responsive layout) into one discriminant. "Mobile-list" and "split" are not the same kind of state as "execution-detail"
- Introduces a pattern (discriminated union switch) not used elsewhere in this frontend. Other tabs use early-return ladders and inline ternaries
- The current code is 184 lines and the problematic region is ~35 lines. The `switch` version may be longer (each case duplicates some wrapper JSX like `<div ref={containerRef}>`)
- The `containerRef` for `ResizeObserver` must be attached to a wrapper in every case (currently it is attached at different places in different branches — the execution-detail branch attaches it to its wrapper, the main branch to the container), adding some repetition

**Effort estimate**: Small. The refactor is mechanical — extract derivation, rewrite render as switch, verify tests pass.

**Dependencies**: None.

### Option B: Component decomposition (separate files per mode)

**How it works**: Split into separate components — `ExecutionDetailMode`, `EmptyHandlersMode`, `MasterDetailMode` — each in its own file. `HandlersTab` becomes a thin switch that selects the right component. The `MasterDetailMode` component internally handles the mobile/desktop layout toggle.

**Pros**:
- Each file has a single concern and is independently testable
- Adding a new mode means adding a new file, not modifying existing render logic
- Follows the decomposition pattern that already shaped this component's history (the original 507-line component was decomposed into `handler-list.tsx`, `listener-detail.tsx`, `job-detail.tsx`)

**Cons**:
- Over-decomposition for the current scale. The execution-detail branch is 15 lines of JSX (a `<div>` wrapping `<ExecutionDetailFetcher>`). The empty-state branch is 5 lines. Putting these in separate files adds import/export ceremony with no reduction in reader load
- Creates 3-4 new files with trivial content — the thinnest would be 10-15 lines including imports
- Splits state that is currently local: the `containerRef` and `isMobile` signal are shared between the ResizeObserver setup and the render branches. Decomposing into files means either passing `isMobile` as a prop (threading responsive state through component boundaries) or duplicating the ResizeObserver setup
- The existing tests render `HandlersTab` as the entry point for all 29 tests. Decomposing into sub-components would either require rewriting tests to target sub-components, or keeping the existing test structure (which still works, but now tests a thin wrapper rather than the logic)
- Does not match codebase conventions — no other tab decomposes into mode-specific sub-components

**Effort estimate**: Medium. Creating files is cheap, but wiring up shared state (ResizeObserver, containerRef) across component boundaries adds friction, and test restructuring adds scope.

**Dependencies**: None.

### Option C: Two-layer separation (URL state + layout)

**How it works**: Separate the two orthogonal concerns rather than flattening them. First, derive the URL-driven content mode (a three-member discriminant):

```ts
type ContentMode =
  | { mode: "execution-detail"; parsed: ParsedHandler; execId: string }
  | { mode: "empty" }
  | { mode: "master-detail"; parsed: ParsedHandler | null }
```

Then, within the "master-detail" case, handle the mobile/desktop layout as it is today — via `showMasterList`/`showDetailPane` booleans or a simpler `isMobile ? "stacked" : "split"` check. This keeps the two concerns visually separate: the content switch decides *what* to show; the layout logic decides *how* to arrange it.

**Pros**:
- Respects the fact that mobile/desktop is a different kind of concern than URL-driven mode selection — does not force-flatten orthogonal axes into one discriminant
- The content-mode derivation is a clean three-way switch. The mobile layout branching stays as conditional CSS classes + one `showMasterList`/`showDetailPane` toggle, which is the simpler part of the current code
- Closest to the current code structure — the two early returns already implement the first two content modes. The refactor just makes the third case (master-detail) explicit and names the overall pattern
- Minimal diff: extract a `deriveContentMode()` function, replace the two early returns with a switch, keep the master-detail body as-is but now inside a named case
- Mobile layout booleans (`showMasterList`, `showDetailPane`) can be simplified to a single `isMobile ? ... : ...` ternary within the master-detail case, since that is the only place they are used

**Cons**:
- Does not fully eliminate the boolean sub-branching within master-detail — the mobile layout toggle is still 3 booleans (or a simplified ternary). The issue specifically asked for "no scattered guards"
- Two layers of branching (content mode switch, then layout toggle) may feel like the same complexity repackaged rather than reduced
- The payoff is modest given the component is already 184 lines — this saves perhaps 5-10 lines of mental overhead

**Effort estimate**: Small. Slightly less work than Option A because the mobile layout logic stays as-is.

**Dependencies**: None.

### Option D: Route-level splitting (execution detail as separate route component)

**How it works**: Instead of `HandlersTab` internally branching on `selectedExecId`, make the execution-detail URL (`/apps/:key/handlers/:kind/:id/exec/:execId`) render a different component entirely — an `ExecutionDetailPage` that lives alongside (or inside) `AppDetailPage` but bypasses `HandlersTab`. This removes the most complex early return from the component.

**Pros**:
- Execution detail is conceptually a different "page" — it shows completely different content (no master list, no handler selection, just a single execution record with logs)
- Aligns with the URL structure: the route is already distinct in `app.tsx` (lines 126-137)
- Reduces HandlersTab to two modes (empty + master-detail), which is trivial

**Cons**:
- The execution-detail branch in HandlersTab is only 15 lines — removing it does not significantly reduce complexity
- `ExecutionDetailFetcher` needs `handlerName`, which it currently derives from `selectedListener.handler_method` or `selectedJob.job_name`. These come from the `listeners`/`jobs` arrays fetched by `AppDetailPage`. A separate route component would either need to re-fetch this data, receive it from a shared parent, or drop the name (showing just "handler" as the back-link label)
- Restructuring `app.tsx` routing to render a different component for exec URLs would break the tab-panel chrome (header, tab bar, sidebar state) unless the new component also wraps in `AppDetailPage` — which means it is not really a separate route, just a different child of the same page
- The execution-detail URL must still highlight the "handlers" tab in the tab bar, since the back-link goes to the handler detail. A truly separate route component would need to coordinate this
- Highest-effort option for the least return. The real complexity is in the mobile layout branching, which this does not address

**Effort estimate**: Large. Requires routing changes, data-flow restructuring, and careful handling of the app-detail chrome (tab bar, header, sidebar).

**Dependencies**: None, but touches `app.tsx` routing which is a shared concern.

## Concerns

### Technical risks

- **ResizeObserver + containerRef sharing**: Any option that decomposes the component must handle the fact that `containerRef` is used by the ResizeObserver effect AND must be attached to the rendered output in every branch (including execution-detail, which wraps its content in `<div ref={containerRef}>`). Options A and C handle this naturally (single component, single ref); Options B and D require ref-forwarding or prop-threading.

- **Execution-detail + empty data edge case**: When `selectedExecId && parsed` is true, the execution-detail branch fires even if `hasItems` is false (e.g., navigating to an execution URL for an app with no registered handlers). This is correct behavior (test at line 702-709 confirms it), but a viewMode derivation function must preserve this ordering — execution-detail must take priority over empty-state. Both Options A and C handle this correctly if the derivation checks `selectedExecId` first.

### Complexity risks

- **Introducing a codebase-first pattern**: No other component in this frontend uses a discriminated union for render-mode selection. Adopting one here creates a local convention that future developers may or may not follow. This is a one-time cost, not a scaling risk, and the pattern is well-understood in the TypeScript ecosystem.

### Maintenance risks

- **Future mode addition (#1246)**: Issue #1246 proposes auto-selecting the highest-priority handler when no handler is selected (failing first, most recently active otherwise). This would add a new implicit selection state: "no handler selected in URL, but auto-selected by priority logic." A viewMode discriminant (Options A, C) accommodates this naturally — add a union member. The current scattered-boolean approach would require adding yet another conditional.

## Open Questions

- [ ] Should the mobile/desktop layout toggle be treated as a "mode" (flattened into the discriminant, Option A) or as an orthogonal layout concern (kept separate, Option C)? This is a design-taste question, not a technical one.
- [ ] Does the auto-selection feature (#1246) change the mode model enough to warrant designing for it now, or should the viewMode discriminant be kept minimal and extended later? The issue is open but unassigned.

## Recommendation

**Option C (two-layer separation)** is the best fit for this codebase, with Option A as a close and acceptable alternative.

The reasoning: the current code has two separable problems, and conflating them produces a less truthful model. The URL-driven content modes (execution detail, empty, master-detail) are genuinely mutually exclusive states that should be a discriminant. The mobile/desktop layout toggle is a responsive concern that only applies within one of those modes. Option C names both layers explicitly, producing code that a reader can follow top-down: "first, what content are we showing? then, how is it laid out?"

That said, Option A is also a fine outcome. The five-member union is small enough that flattening the two concerns into one discriminant does not create real confusion. If the implementer finds that collapsing into a single switch produces cleaner JSX (avoiding the nested ternary within the master-detail case), Option A is the right call. The difference between A and C is small — both are improvements over the status quo, and both accommodate the auto-selection feature from #1246.

Option B (decomposition into files) is over-engineering for a 184-line component. Option D (route-level splitting) has a high effort-to-benefit ratio and does not address the core problem.

Confidence: **Supported** — grounded in the actual code structure, codebase conventions, and open issue trajectory. No single source prescribes the right answer, but the evidence converges on a lightweight discriminant refactor.

### Suggested next steps

1. Implement the refactor directly — this is a small, well-scoped change that does not need a design doc. Extract `deriveContentMode()` (or `deriveViewMode()`), add unit tests for the derivation function, replace the render body with a switch, verify all 29 existing tests pass.
2. When implementing #1246 (auto-selection), extend the discriminant with the new state rather than adding another boolean.
3. Consider whether the `ResizeObserver` container-query approach (unique to this component) should be extracted into a reusable `useContainerBreakpoint` hook, since the mobile layout toggle would benefit from clearer encapsulation. This is optional polish, not a prerequisite.
