# Research Brief: Live-Updating Counts Without Destroying Alpine.js State

**Date**: 2026-03-19
**Status**: Ready for Decision
**Proposal**: Replace the current full-section morph refresh with a targeted update strategy that keeps counts/badges fresh without collapsing expanded Alpine.js rows.
**Initiated by**: User investigating correct approach for live counts in htmx + Alpine.js server-rendered app.

## Context

### What prompted this

The app detail page (`app_detail.html`) has expandable handler rows managed by Alpine.js (`x-data="{ open: false, loaded: false }"`). When a WebSocket `app_status_changed` event fires, `live-updates.js` calls `htmx.ajax("GET", url, { target: el, swap: "morph:innerHTML" })` which replaces the entire `#app-handlers` div. Idiomorph cannot preserve Alpine's `x-data` state (it was not designed to -- it morphs DOM structure but does not understand Alpine's reactive proxy layer). This collapses any expanded row.

A previous attempt to work around this exists: a hidden `#app-handler-stats` div that polls every 5 seconds via `hx-get` and receives `data-*` attributes with fresh counts. However, no JavaScript reads those attributes -- it is a dead partial. The comment in the template confirms the intent: "keeps invocation counts fresh without morphing expanded rows." The approach was started but never completed.

### Current state

**Live update flow:**
1. Backend `RuntimeQueryService._on_app_state_changed()` broadcasts `{ type: "app_status_changed", data: ... }` to all WS clients.
2. `ws-handler.js` (Alpine store `$store.ws`) dispatches `ht:ws-message` and `ht:refresh` custom events on `document`.
3. `live-updates.js` listens for `ht:ws-message` where `type === "app_status_changed"`, finds all `[data-live-on-app]` elements, and debounces (500ms) a full `htmx.ajax("GET", url, { target, swap: "morph:innerHTML" })`.
4. This replaces the entire handler list (`#app-handlers`), which contains the Alpine `x-data` expand/collapse state.

**What needs updating per the user's requirements:**
- Invocation counts (`listener.total_invocations`, `listener.failed`)
- Status dot color (success/danger/neutral based on counts)
- Average duration display
- Same for scheduled jobs (`job.total_executions`, `job.failed`, etc.)
- Health strip cards (already in a separate `data-live-on-app` element, works fine)

**What does NOT need live updating:**
- Handler list structure (new/removed handlers only appear on page reload)
- Expanded detail content (loaded on demand, can be stale)

### Key constraints

- Stack is negotiable but migration cost matters -- existing app is ~15 templates, ~280 lines of JS
- Only counts and badges need to stay fresh; structure can be stale
- Expand state must survive live updates
- The WebSocket infrastructure already exists and works well
- The dead `app_handler_stats` partial already has the backend route and data model

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Alpine store for handler stats | `ws-handler.js` (new store) | Low | Low -- Alpine stores are well-understood in this codebase |
| Handler row template | `macros/ui.html` (handler_row, job_row) | Low | Low -- add `x-text` bindings alongside static values |
| Live-updates.js | `live-updates.js` | Low | Low -- remove handler list from morph targets |
| Stats endpoint | `partials.py` (existing route) | Low | Low -- route exists, just change response format |
| Dead stats partial | `app_handler_stats.html` | Low | Low -- replace or remove |
| App detail page | `app_detail.html` | Low | Low -- remove dead polling div |

### What already supports this

1. **WebSocket + Alpine store pattern is established.** The `$store.ws` store already exists and dispatches typed events. Adding a `$store.handlerStats` store follows the exact same pattern.
2. **The backend route exists.** `/ui/partials/app-handler-stats/{app_key}` already queries `telemetry.get_listener_summary()` and returns per-listener data. It just needs to return JSON instead of (or in addition to) HTML.
3. **Handler rows have stable IDs.** Each row has `id="handler-{{ listener.listener_id }}"` which makes targeted DOM updates trivial.
4. **Alpine `x-data` already wraps each row.** Adding reactive bindings (`x-text`, `:class`) to the existing `x-data` scope is natural.
5. **The health strip already works.** It is a separate `data-live-on-app` element that morphs independently -- this pattern works because health cards have no interactive state.

### What works against this

1. **Counts are currently rendered server-side in Jinja.** Switching to `x-text` means the initial render must either: (a) also populate an Alpine store from server data, or (b) accept a flash of "0" before the first WS update. Option (a) is straightforward with an inline `x-init`.
2. **No JSON API exists yet for handler stats.** The current partial returns HTML. A new JSON endpoint (or adding `Accept: application/json` handling) is needed for the Alpine store approach.

## Options Evaluated

### Option A: Alpine `$store` for Counts (Pure Client-Side Reactivity)

**How it works**: Create an `Alpine.store("stats", { handlers: {}, jobs: {} })` that holds per-listener and per-job counters. On `app_status_changed` WS events, fetch a JSON endpoint (`/api/handler-stats/{app_key}`) and merge the response into the store. Handler row templates use `x-text="$store.stats.handlers[listenerId]?.total ?? initialValue"` and `:class` bindings for the status dot. The Alpine `x-data` for expand/collapse is completely untouched -- only `x-text` and `:class` read from the store.

No htmx involvement for count updates at all. The morph-based refresh of `#app-handlers` is removed (or kept only for structural changes like app start/stop, using `Alpine.morph()` if needed in the future).

**Pros**:
- Zero DOM replacement -- Alpine reactivity updates only the text nodes that changed
- Expand/collapse state is inherently preserved (no morph, no swap, no re-render)
- Leverages the existing WS event flow (`ht:ws-message` -> store update)
- Simplest mental model: WS pushes event, store updates, bindings react
- The dead `app-handler-stats` polling div can be removed entirely
- Works with the existing 500ms debounce in `live-updates.js` (or can use its own debounce)

**Cons**:
- Initial page load must seed the store (small `x-init` block or inline `<script>` in the page template)
- Duplicates the "source of truth" -- server renders initial values, store holds live values
- If the JSON endpoint returns data for handlers that don't exist in the DOM (new handler registered), the store has data but no row to display it in (acceptable per requirements -- structure is stale until reload)
- Requires a new JSON API endpoint (trivial -- 10 lines of FastAPI)

**Effort estimate**: Small. New JSON endpoint + Alpine store + template `x-text` bindings. ~2-3 files changed, ~50 lines of new code.

**Dependencies**: None. Uses existing Alpine.js and WebSocket infrastructure.

### Option B: htmx `hx-swap-oob` (Out-of-Band Swaps)

**How it works**: Instead of morphing the entire handler list, the server returns HTML fragments with `hx-swap-oob="innerHTML:#handler-{id}-stats"` for each handler's stats span. A single fetch returns the primary target content (could be empty/no-op) plus OOB fragments that update individual stat elements by ID.

The current `htmx.ajax()` call in `live-updates.js` would target a throwaway element, and the real updates happen via OOB. Each handler row would need a dedicated `<span id="handler-{id}-stats">` wrapper around its stats.

**Pros**:
- Pure htmx pattern -- no Alpine store needed for data
- Server retains full control of rendered HTML (no client-side data transformation)
- OOB swaps are a well-documented htmx feature

**Cons**:
- `htmx.ajax()` support for OOB is indirect -- OOB elements must be at the top level of the response HTML, and the response is processed through htmx's normal swap pipeline. The `selectOOB` parameter in `htmx.ajax()` exists but selects from the response rather than triggering `hx-swap-oob` attributes.
- Every handler row needs unique stat IDs (already have `handler-{id}`, so `handler-{id}-stats` is easy)
- Scaling concern: if 20 handlers are registered, the response contains 20 OOB fragments. Not a real performance issue at this scale, but it is more bytes over the wire than a JSON object.
- Still performs a server fetch + HTML rendering per update -- more server work than Option A's JSON endpoint
- The existing `morph:innerHTML` swap strategy does NOT process OOB elements in the response (idiomorph extension does not handle OOB). Would need to switch to a non-morph swap for the OOB response.

**Effort estimate**: Small-Medium. Template changes for stat IDs, new partial template for OOB response, changes to `live-updates.js` swap strategy.

**Dependencies**: None. Uses existing htmx.

### Option C: `Alpine.morph()` Direct Call (Preserve State During Full Morph)

**How it works**: Instead of `htmx.ajax("GET", url, { swap: "morph:innerHTML" })`, fetch the handler list HTML via `fetch()`, then call `Alpine.morph(el, html, { updating(el, toEl, childrenOnly, skip) { ... } })` with lifecycle hooks that skip elements where `el._x_dataStack` indicates `open === true`.

**Pros**:
- Preserves the current server-rendered-HTML-replacement pattern
- Alpine.morph is specifically designed to preserve Alpine state during DOM morphing
- Can handle both count updates AND structural changes (new/removed handlers)
- The `updating` hook with `skip()` gives fine-grained control

**Cons**:
- Requires adding the Alpine morph plugin (~3KB) -- currently not loaded
- The `updating` hook logic is subtle: you need to detect which elements have interactive state and skip their children while still updating their text content. The `childrenOnly()` escape hatch helps but adds complexity.
- Still replaces the entire section HTML on every update -- more DOM work than Option A
- Debugging morph issues is notoriously difficult (silent state loss when hooks are wrong)
- Does not solve the core over-fetching problem: still GETs the full handler list HTML when only counts changed

**Effort estimate**: Medium. Add Alpine morph plugin, rewrite swap logic in `live-updates.js`, write and test morph lifecycle hooks.

**Dependencies**: `@alpinejs/morph` plugin (CDN or vendored).

### Option D: htmx `alpine-morph` Extension

**How it works**: Replace `idiomorph` with the `htmx-alpine-morph` extension. Configure htmx to use `swap: "morph:innerHTML"` via the alpine-morph extension instead of idiomorph. This makes htmx use `Alpine.morph()` under the hood, preserving Alpine state during swaps.

**Pros**:
- Drop-in replacement for idiomorph in the htmx swap pipeline
- All existing `htmx.ajax()` calls continue to work with the same swap syntax
- Alpine state preservation is automatic (no manual lifecycle hooks)

**Cons**:
- The alpine-morph extension has known issues with `htmx.process()` -- after a morph, new htmx attributes in the morphed content may not be properly initialized (documented in [htmx discussion #3225](https://github.com/bigskysoftware/htmx/discussions/3225))
- Replaces idiomorph globally -- all htmx swaps now use Alpine.morph(). If any swap intentionally wants to destroy and rebuild Alpine state (e.g., page navigation), this could cause stale-state bugs.
- Still fetches the full handler list HTML on every update (same over-fetching as Option C)
- Less community adoption than idiomorph -- fewer production battle scars
- Requires both Alpine morph plugin AND the htmx extension

**Effort estimate**: Medium. Replace idiomorph with alpine-morph extension, test all existing swap behaviors for regressions.

**Dependencies**: `@alpinejs/morph` plugin + `htmx-alpine-morph` extension.

### Option E: Datastar (Full Framework Replacement)

**How it works**: Replace htmx + Alpine.js + idiomorph with Datastar, a single ~14KB framework that combines server-driven HTML updates (via SSE) with client-side reactive signals. The existing WebSocket would be replaced with SSE endpoints. Signals replace Alpine stores. DOM morphing is built-in and signal-aware.

**Pros**:
- Eliminates the htmx/Alpine seam entirely -- one framework, one mental model
- SSE is a natural fit for the push-based update pattern already in use
- Built-in signal reactivity + DOM morphing means no state loss during updates
- Smaller total bundle than htmx + Alpine + idiomorph

**Cons**:
- Full rewrite of all 15 templates, 3 JS files, and the WebSocket backend
- Datastar is young (< 2 years, small community). Production battle-testing is limited.
- No established Python/FastAPI integration patterns (most examples are Go or Node)
- SSE requires different server infrastructure than WebSocket (though FastAPI supports both via `EventSourceResponse`)
- The existing WebSocket infrastructure (bidirectional: subscribe to logs, ping/pong) would need to be rearchitected -- SSE is server-to-client only
- Learning curve for the entire team

**Effort estimate**: Large. Full UI rewrite + backend SSE endpoints. Weeks of work.

**Dependencies**: Datastar framework. Removes htmx, Alpine.js, idiomorph.

## Concerns

### Technical risks

- **Option A (Alpine store)**: The main risk is SSR/client divergence. If the initial server render says "5 calls" and the store is seeded with the same value, there is no divergence. But if a WS message arrives between the server render and Alpine initialization, the user sees stale data for ~100ms until the store hydrates. This is cosmetically acceptable for a monitoring dashboard.

- **Option B (OOB)**: The interaction between `htmx.ajax()` programmatic calls and OOB processing is not clearly documented for htmx 2.x. The `selectOOB` parameter exists but its behavior with idiomorph is untested in this codebase. There is a real risk of spending time debugging htmx internals.

### Complexity risks

- **Option A** adds one new concept (Alpine store for stats) but removes the problematic morph behavior. Net complexity is roughly neutral or slightly reduced.
- **Options C/D** add morph configuration complexity while keeping the full-section-replacement pattern that caused the original problem.
- **Option E** replaces all complexity with different complexity. Net risk is high during transition.

### Maintenance risks

- **Option A**: The JSON stats endpoint is a thin wrapper around `telemetry.get_listener_summary()` which already exists. Maintenance cost is near zero.
- **Option B**: OOB templates are a parallel representation of the same data as the handler row template. Changes to the stats display must be made in two places.
- **Option E**: Datastar's ecosystem churn could require template rewrites as the framework matures.

## Open Questions

- [ ] Does the `app_status_changed` WS message fire on every handler invocation, or only on app lifecycle events (start/stop/fail)? If only lifecycle events, the Alpine store approach needs a separate trigger for count updates (e.g., a new `handler_invoked` WS message type, or keep the 5s poll but hitting the JSON endpoint).
- [ ] Should the health strip also move to the Alpine store approach for consistency, or is its current morph-based refresh acceptable since it has no interactive state?
- [ ] Are there other pages (dashboard app grid, apps list) that have the same morph-destroys-state problem, or is this isolated to the app detail page?

## Recommendation

**Option A (Alpine `$store` for counts)** is the clear winner for this scope.

The requirements explicitly state that only counts and badges need to stay fresh, and that the handler list structure can be stale until page reload. This means the problem is fundamentally a data-binding problem, not a DOM-morphing problem. Alpine's reactive store is purpose-built for exactly this: bind UI elements to a data source and let the framework handle updates.

Option A is the smallest change, introduces no new dependencies, follows patterns already established in the codebase (`$store.ws`), and completely eliminates the state-destruction problem by not touching the DOM structure at all. It also removes the dead `app-handler-stats` polling partial, simplifying the existing code.

Options C and D (morph-based) solve the wrong problem -- they try to make full-section replacement work when full-section replacement is not needed. Option B (OOB) is a reasonable htmx-native alternative but adds more complexity for the same result. Option E (Datastar) is interesting for a future full rewrite but wildly disproportionate to the current problem.

### Suggested next steps

1. **Verify the `app_status_changed` trigger frequency** -- check whether handler invocations trigger this WS event, or whether a new event type is needed for count freshness.
2. **Write a design doc via `/mine.design`** covering: the Alpine stats store structure, the JSON API endpoint, the template binding changes, and the removal of the dead polling partial.
3. **Prototype in a branch** -- the implementation is small enough (~50 lines) that a working prototype can validate the approach in under an hour.

## Sources

- [htmx hx-swap-oob documentation](https://htmx.org/attributes/hx-swap-oob/)
- [htmx JavaScript API (htmx.ajax)](https://htmx.org/api/)
- [htmx Examples: Updating Other Content](https://htmx.org/examples/update-other-content/)
- [Alpine.js Morph Plugin documentation](https://alpinejs.dev/plugins/morph)
- [htmx alpine-morph extension](https://github.com/bigskysoftware/htmx-extensions/blob/main/src/alpine-morph/README.md)
- [htmx.process() with alpine-morph discussion #3225](https://github.com/bigskysoftware/htmx/discussions/3225)
- [Alpine.js morph skip-children PR #4568](https://github.com/alpinejs/alpine/pull/4568)
- [Alpine.js $store and WebSocket discussion](https://github.com/alpinejs/alpine/discussions/2242)
- [Why I'm migrating from HTMX + Alpine to Datastar](https://rogerstringer.com/blog/why-im-migrating-from-htmx-alpine-to-datastar)
- [Datastar framework](https://data-star.dev/)
- [Datastar Basics (Jeff Hui)](https://www.jeffhui.net/writings/2025/datastar/)
