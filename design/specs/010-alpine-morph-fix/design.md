# Design: Replace Stats Polling Workaround with Alpine-Morph

**Date:** 2026-03-20
**Status:** draft
**Critique:** `design/critiques/2026-03-20-ui-rebuild-pr/critique.md` (Finding #2)

## Problem

The app detail page uses a hidden polling div + 70 lines of manual DOM patching JavaScript to update handler row stats without destroying Alpine.js expand/collapse state. This workaround exists because idiomorph (the current morph engine) does not understand Alpine.js component state — it overwrites `x-data` attributes during morph, resetting state to defaults.

**However, the workaround is solving a problem that doesn't currently exist for handler rows.** The `#app-handlers` div is never morphed — it has no `data-live-on-app` attribute. The workaround was built preemptively. The actual exposure point is the alert banner (`alert_failed_apps.html`), which IS morphed via `data-live-on-app` and contains `x-data="{ detailsOpen: false }"` and nested `x-data="{ tbOpen: false }"` — a real bug.

The workaround is also brittle: it finds DOM elements by CSS class names (`.ht-meta-item[title='Total invocations']`, `.ht-meta-item--strong.ht-text-danger`) and text content substrings (`indexOf("avg")`), creating invisible coupling between `live-updates.js` and `macros/ui.html`. Any template restructuring silently breaks live stat updates.

The canonical solution is the `htmx-ext-alpine-morph` extension, which uses Alpine.js's own morph algorithm instead of idiomorph for containers with Alpine state. This preserves `x-data` component state through swaps.

## Non-Goals

- **Not redesigning the live-update architecture.** The `data-live-on-app` + WebSocket event + debounced HTMX fetch pattern stays. We're fixing the morph engine, not the update trigger.
- **Not moving to WebSocket-pushed stat deltas.** That's a future enhancement (backlog finding #9). This design keeps HTMX partial fetches as the update mechanism.
- **Not touching idiomorph usage on non-Alpine containers.** Dashboard KPI strip, health strip, dashboard errors — these have no Alpine state and continue using idiomorph.
- **Not vendoring CDN scripts.** The existing stack (htmx, idiomorph, Alpine.js) already relies on CDN delivery. Vendoring all scripts is a separate concern tracked in the backlog.

## Architecture

### Morph strategy: two engines, clear convention

The project will use two morph engines:

1. **idiomorph** (existing) — for containers whose partials have no Alpine.js `x-data` state. This is the majority: health strip, KPI strip, dashboard errors, dashboard app grid, manifest list.

2. **alpine-morph** (new) — for containers whose partials contain Alpine.js `x-data` components. Currently: handler list, job list, alert banner.

**Convention:** If a morphed partial contains `x-data` with state (not bare `x-data`), its container must use alpine-morph. Document in `web/CLAUDE.md`.

### Script loading order

Alpine.js morph plugin must load BEFORE Alpine.js core. The htmx alpine-morph extension must load AFTER htmx.

Current `base.html` load order:
```
htmx 2.0.4
idiomorph 0.3.0
ws-handler.js (defer)
live-updates.js (defer)
log-table.js (defer)
alpinejs 3.14.8 (defer)
```

New load order:
```
htmx 2.0.4
idiomorph 0.3.0
htmx-ext-alpine-morph           ← NEW (after htmx, before Alpine)
@alpinejs/morph plugin           ← NEW (before Alpine core)
ws-handler.js (defer)
live-updates.js (defer)
log-table.js (defer)
alpinejs 3.14.8 (defer)
```

The two new scripts are NOT `defer` — they must load synchronously before Alpine.js initializes.

### Preserving expanded row content through morphs

**Problem:** Alpine-morph preserves the reactive proxy (`open: true`, `loaded: true`) on handler/job rows, but reconciles child DOM against the incoming server HTML. The server always renders `#handler-N-detail` with the "Loading invocations..." placeholder. After morph, any previously-loaded invocation history is replaced by the placeholder. Since `loaded` stays `true`, the click handler's `if (open && !loaded)` gate never re-fetches. The user sees a permanently broken expanded row.

**Solution:** Replace the `@click` load gate with an `x-effect` watcher. After every morph, Alpine-morph resets `loaded` to `false` (since the server HTML emits `loaded: false`). Wait — Alpine-morph preserves the *proxy*, not the attribute. So we need a different approach.

The correct fix: after each morph of the handler list, reset `loaded = false` on all handler rows so the `x-effect` watcher re-fetches for any row that is `open`. This uses Alpine's `htmx:afterSettle` lifecycle:

**In `handler_row` macro (`macros/ui.html`):**

Change from:
```html
x-data="{ open: false, loaded: false }"
...
@click="open = !open; if (open && !loaded) { htmx.ajax(...); loaded = true; }"
```

Change to:
```html
x-data="{ open: false, loaded: false }"
x-effect="if (open && !loaded) { htmx.ajax('GET', '...', { target: '...', swap: 'innerHTML' }); loaded = true; }"
...
@click="open = !open"
```

Then in `live-updates.js`, after a morph completes on an alpine-morph container, dispatch a reset:

```javascript
// After morph settles, reset loaded flags so x-effect re-fetches for open rows
document.body.addEventListener("htmx:afterSettle", function (e) {
  var target = e.detail.target;
  if (!target || !target.hasAttribute("hx-ext")) return;
  target.querySelectorAll("[x-data]").forEach(function (el) {
    if (el._x_dataStack && el._x_dataStack[0] && el._x_dataStack[0].loaded === true) {
      el._x_dataStack[0].loaded = false;
      // x-effect will fire and re-fetch if open === true
    }
  });
});
```

**Tradeoff:** An expanded row briefly shows "Loading invocations..." then re-fetches fresh data. This is acceptable — the data is fresher anyway, and morphs only happen on status change events (not continuous polling).

Apply the same pattern to `job_row`.

### What changes in `live-updates.js`

The `scheduleRefresh` function (line 89-103) currently always uses `morph:innerHTML` as the swap strategy:

```javascript
htmx.ajax("GET", refreshUrl, { target: target, swap: "morph:innerHTML" });
```

It will derive the swap strategy from whether `hx-ext="alpine-morph"` is present on the target element:

```javascript
var swapStrategy = target.getAttribute("hx-ext") === "alpine-morph" ? "morph" : "morph:innerHTML";
htmx.ajax("GET", refreshUrl, { target: target, swap: swapStrategy });
```

This eliminates the need for a separate `data-live-swap` attribute. One attribute (`hx-ext`) controls both the extension activation and the swap strategy selection. No two-attribute sync required.

**Delete entirely:** Lines 146-218 (the stats poll updater `htmx:afterSwap` handler for `#app-handler-stats`). This is the 70-line workaround.

**Add:** The `htmx:afterSettle` handler for resetting `loaded` flags after morph (described above).

**Add:** App-key filtering for `app_status_changed` events. Currently `live-updates.js:113-118` triggers ALL `[data-live-on-app]` elements on every `app_status_changed`, regardless of which app changed. With handler/job lists now morphing, this causes unnecessary fetches for other apps' events:

```javascript
if (detail && detail.type === "app_status_changed") {
  var changedApp = detail.app_key || "";
  document.querySelectorAll("[data-live-on-app]").forEach(function (el) {
    var url = el.getAttribute("data-live-on-app") || "";
    // Skip elements whose URL targets a different app
    if (changedApp && url.indexOf("/apps/") !== -1 && url.indexOf(changedApp) === -1) return;
    scheduleRefresh(el, "data-live-on-app");
  });
}
```

Dashboard-level elements (no `/apps/` in URL) always refresh. App-specific elements only refresh when their app changes.

### What changes in templates

**`app_detail.html`:**

1. Expand the morph container to include the heading, so the count stays fresh:
   ```html
   <div id="app-handlers-section"
        class="ht-card ht-mb-4"
        hx-ext="alpine-morph"
        data-live-on-app="/ui/partials/app-handlers/{{ app_key }}?instance_index={{ instance_index }}">
     <h2 class="ht-heading-5" data-testid="handlers-heading">
       ...
       Event Handlers ({{ listeners|length }} registered)
     </h2>
     <div id="app-handlers" data-testid="handler-list">
       {% include "partials/app_handlers.html" %}
     </div>
   </div>
   ```

   The partial endpoint needs to return both the heading and the list. Either expand `app_handlers_partial` to include the heading, or create a new partial that wraps both. The simpler approach: include the count in the `app_handlers.html` partial itself and move the heading inside.

2. Same pattern for jobs — wrap heading + list in a single morphable container with `hx-ext="alpine-morph"`.

3. **Delete** the hidden `#app-handler-stats` div (lines 114-122) entirely.

**`alert_banner.html`:**

Add `hx-ext="alpine-morph"` to the `#alert-failed-apps` div:
```html
<div id="alert-failed-apps"
     hx-ext="alpine-morph"
     data-live-on-app="/ui/partials/alert-failed-apps">
```

**`alert_failed_apps.html`:**

Add stable `id` attributes to per-app items so Alpine-morph matches by identity, not position:
```html
<div class="ht-alert-item"
     id="alert-item-{{ app.app_key }}"
     x-data="{ tbOpen: false }">
```

Without this, positional matching causes `tbOpen` state to leak between rows when the failed-app list changes.

### What gets deleted

| File | What | Lines |
|------|------|-------|
| `live-updates.js` | Stats poll updater block | 146-218 (73 lines) |
| `app_detail.html` | Hidden `#app-handler-stats` div | 114-122 (9 lines) |
| `partials/app_handler_stats.html` | Entire file | all (8 lines) |
| `partials.py` | `app_handler_stats_partial` endpoint | 160-170 (11 lines) |

Total removal: ~100 lines of workaround code, 1 template file, 1 HTTP endpoint.

### What gets added

| File | What | Lines |
|------|------|-------|
| `base.html` | 2 CDN script tags | +2 |
| `live-updates.js` | Swap strategy derivation from `hx-ext` | +1 (modify existing) |
| `live-updates.js` | `htmx:afterSettle` handler for loaded reset | +10 |
| `live-updates.js` | App-key filtering for `app_status_changed` | +5 |
| `macros/ui.html` | `x-effect` on handler_row and job_row | +2 (modify existing) |
| `app_detail.html` | `hx-ext` + `data-live-on-app` on section wrappers | +4 attrs |
| `alert_banner.html` | `hx-ext` on alert div | +1 attr |
| `alert_failed_apps.html` | `id` on per-app items | +1 attr per item |
| `web/CLAUDE.md` | Convention note | +5 |

### Alpine-morph swap mechanics

When `hx-ext="alpine-morph"` is on an element, htmx uses `Alpine.morph()` instead of idiomorph for swaps targeting that element. Alpine's morph:

- Matches nodes by `id` attribute (handler rows have `id="handler-{{ listener.listener_id }}"`)
- Preserves Alpine reactive proxies on matched nodes (expand/collapse state survives)
- Initializes Alpine on new nodes (new handler appears → component auto-initializes)
- Cleans up removed nodes (handler removed → no orphaned state)

**Important:** Alpine-morph preserves the reactive proxy but reconciles child DOM against incoming HTML. For lazy-loaded content (invocation history inside expanded rows), the morph replaces loaded content with the server's placeholder. The `loaded` reset mechanism (described above) handles this by triggering a re-fetch via `x-effect`.

### Dashboard app grid — no change needed

The dashboard app grid (`dashboard_app_grid.html`) uses bare `x-data` (no state) on `<time>` elements for locale formatting. Idiomorph handles this correctly because there's no meaningful Alpine state to preserve. No change needed.

## Alternatives Considered

### Keep the workaround, fix only the alert banner

Add alpine-morph only to the alert banner. Leave the 70-line DOM patching for handler stats.

**Rejected because:** The workaround is 100 lines of code solving a problem that alpine-morph eliminates. It also can't handle structural changes (new handler added, handler removed) — only count updates. Alpine-morph gives us full partial replacement for free.

### Move Alpine state to the server

Track expand/collapse state via URL hash or session. Server renders rows pre-expanded.

**Rejected because:** Expand/collapse is fundamentally client-side state. This would require a server round-trip for every click, defeat the purpose of Alpine.js, and make the alert banner's nested expand state awkward.

### Drop Alpine.js entirely, use only HTMX

Replace expand/collapse with HTMX-driven disclosure (fetch expanded content on click, no client state).

**Rejected because:** Alpine.js is used for more than expand/collapse — log table filters, theme toggle, WebSocket store. Removing it would require rewriting those features. The stack combination is sound; only the morph engine needs the fix.

### Use `data-live-swap` attribute instead of deriving from `hx-ext`

Have templates declare the swap strategy via a separate `data-live-swap` attribute that `live-updates.js` reads.

**Rejected because:** This requires two synchronized attributes per container (`hx-ext` + `data-live-swap`). When they diverge, the failure is silent. Deriving the swap strategy from `hx-ext` is one attribute, one source of truth.

## Open Questions

- Verify that `htmx-ext-alpine-morph` works with htmx 2.0.4 specifically. The extension targets htmx 2.x generally but should be tested in a quick spike before implementation.
- Verify that `hx-ext="alpine-morph"` on a parent container does NOT intercept `htmx.ajax()` calls targeting descendant elements (the lazy-load calls in `handler_row` and `job_row`). If it does, the `swap: 'innerHTML'` on those calls may be overridden. Test this in the spike.

## Impact

**Files modified:** 6 (`base.html`, `live-updates.js`, `macros/ui.html`, `app_detail.html`, `alert_banner.html`, `alert_failed_apps.html`, `web/CLAUDE.md`)
**Files deleted:** 1 (`partials/app_handler_stats.html`)
**Endpoints removed:** 1 (`/partials/app-handler-stats/{app_key}`)
**Net lines:** ~-70 (100 removed, ~30 added)
**Dependencies added:** 2 CDN scripts (`@alpinejs/morph`, `htmx-ext-alpine-morph`)
**Test impact:** E2E tests for handler stats polling will need updating to verify morph-based updates instead. Add E2E test verifying Alpine state preservation through a morph swap (expand row → trigger morph → verify row stays expanded and content reloads). Add E2E test for alert banner state preservation.
**Blast radius:** Low — changes are confined to the frontend layer. No Python backend changes except removing one endpoint. The handler/job partial endpoints are unchanged.
