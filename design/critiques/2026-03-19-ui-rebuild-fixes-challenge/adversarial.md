# Adversarial Review: Design 009-ui-rebuild-fixes

**Date:** 2026-03-19
**Reviewer role:** Adversarial — design is wrong until proven otherwise
**Design under review:** `design/specs/009-ui-rebuild-fixes/design.md`

---

## Verdict Summary

Three of the six fixes are sound. Two contain hidden traps that will bite in production. One finding (#7, the manifest partial) misidentifies its own root cause and proposes a solution that cannot work as described. The hybrid morph strategy is technically overengineered but defensible if the alpine-morph extension behaves as advertised — the design does not verify this.

---

## Finding A — The `alpine-morph` Extension Claim Is Unverified and Probably Wrong

**Severity: CRITICAL**

### What the design claims

Design §2 says: add `hx-ext="alpine-morph"` to handler/job list containers; this uses Alpine's `@alpinejs/morph` plugin to preserve `x-data` reactive state across morphs.

### Why this is suspect

The `alpine-morph` htmx extension (`https://htmx.org/extensions/alpine-morph/`) is one of htmx's official community extensions. It swaps content using Alpine's morph plugin as the diff algorithm. The key question is: does it preserve `x-data` state on child elements during a `morph:innerHTML` swap?

The answer is: **only for the elements that already exist in the DOM**. Alpine morph preserves state on elements it can match by identity. The morph algorithm matches elements using `id` attributes or positional equivalence.

Look at `ui.html:62`:
```
x-data="{ open: false, loaded: false }"
```
and `ui.html:59`:
```html
<div id="handler-{{ listener.listener_id }}"
```

Each handler row has a stable `id`. This means Alpine morph CAN match them. So for rows that persist across the morph, `open` and `loaded` will survive. This part of the design is technically correct.

**But the design then says in §3**: "With alpine-morph preserving state, the full handler list morph on `app_status_changed` updates both structure (new/removed handlers) AND counts."

Here's the trap: the stats (`total_invocations`, `avg_duration_ms`) inside each `handler-{{ id }}` row are **server-rendered Jinja2 text**, not Alpine reactive state. Alpine morph preserves `x-data` (JS objects), not DOM text content. When a morph occurs, the new HTML from the server contains updated counts. Alpine morph will update those text nodes — it's a DOM diff, so it WILL change the text. But it will also try to morph the `x-show="open"` detail div.

The real problem: if a row is **expanded** (`open: true`) and a morph arrives, the new HTML from the server renders the detail div with its initial loading placeholder (`<div class="ht-item-detail__loading">Loading invocations...</div>`). Alpine morph will morph the DOM content of that detail div to match the server HTML, **destroying the loaded invocation data** even though `open` state is preserved.

So: the collapse state (`open`) survives. The loaded content does NOT survive. Users debugging an incident will see their expanded row flash back to "Loading invocations..." on every `app_status_changed` event. The design claims to fix finding #2 but actually only partially fixes it — the most painful part (losing loaded detail content) remains.

**Evidence:**
- `ui.html:62` — `x-data="{ open: false, loaded: false }"` — `loaded` flag is JS state that survives morph
- `ui.html:68` — `if (open && !loaded)` — the loaded detail won't reload because `loaded=true` is preserved
- `ui.html:91-96` — the `#handler-id-detail` div's innerHTML is server-rendered placeholder text, not Alpine state

Wait — actually this partially redeems the design. The `loaded` flag being preserved means `htmx.ajax` won't re-fire. But the morph will still diff the DOM content of the expanded detail div against the server HTML (which contains only the loading placeholder). Idiomorph/Alpine morph will see a mismatch and clobber the loaded invocations table.

**The fix the design missed:** The detail div needs to be excluded from morphing. One approach: add `id` to the detail div and use `hx-preserve` on it, so morph skips it entirely. Another approach: store the loaded state in Alpine and re-render from JS data, not from server HTML. The simplest approach is `data-morph-preserve` or htmx's `hx-preserve` attribute on `#handler-{{ id }}-detail`.

**Design question:** Has anyone verified that Alpine morph (not idiomorph) handles `hx-preserve` on child elements? The htmx docs note this is extension-specific behavior.

---

## Finding B — The `manifest_list.html` Alpine Directive Approach Has a Scope Problem

**Severity: HIGH**

### What the design claims

Design §6 says: rewrite `manifest_list.html` to include `x-show="activeTab === 'all' || activeTab === '{{ manifest.status }}'"`. When used as an HTMX partial swap, "the receiving `<tbody>` already has Alpine scope from the page's `x-data`". Alpine morph preserves parent scope.

### Why this cannot work as described

Look at `apps.html:22`:
```html
<div class="ht-card"
     x-data="{ activeTab: 'all', expanded: {} }">
```

The `x-data` is on a `<div>` wrapping the card. The `<tbody id="manifest-list">` is a descendant. When HTMX swaps the `<tbody>` innerHTML, it replaces the tbody's children. The children are now new DOM nodes created by the HTMX swap.

**Alpine does NOT automatically initialize new DOM nodes inserted by HTMX.** You need `Alpine.initTree(el)` or htmx's `htmx:afterSwap` to trigger Alpine initialization on the new nodes. Alpine's `x-data` scoping is applied at initialization time when `Alpine.start()` processes the tree.

The design says "the `activeTab` variable is defined on the parent `x-data` scope, which survives the `<tbody>` morph (Alpine morph preserves parent scope)." This is only true if:

1. Alpine morph is used for the swap (not idiomorph)
2. The swap target is the `<tbody>` itself, not its innerHTML

But look at `live-updates.js:91`:
```js
htmx.ajax("GET", refreshUrl, { target: target, swap: "morph:innerHTML" });
```

The swap is `morph:innerHTML` — it morphs the *children* of the target. The target is `<tbody id="manifest-list">`. New `<tr>` elements land in the tbody. These new nodes have `x-show` directives that reference `activeTab`. Since these nodes are new (not morphed from existing), Alpine must initialize them.

With idiomorph (`morph:innerHTML`), Alpine initialization of new elements happens via `htmx:afterSettle` → `Alpine.initTree()`. This works IF htmx is configured to call `Alpine.initTree()` after swaps. Alpine's htmx integration (`alpinejs/morph`) does handle this — but only when the swap extension is `alpine-morph`, not vanilla idiomorph.

**The design's proposed solution for #7 (use `manifest_list.html` as an HTMX partial with Alpine directives) requires the `<tbody>` swap to use `alpine-morph` extension**, but:
- The design only puts `hx-ext="alpine-morph"` on handler/job list containers (`app_detail.html`), not on the apps page `<tbody>`
- The apps page uses `data-live-on-app` → `live-updates.js` → `htmx.ajax(..., { swap: "morph:innerHTML" })` which uses idiomorph

So the new rows will land in the DOM without Alpine initialization of their `x-show` directives. Every row will be visible regardless of the active tab because Alpine won't evaluate `x-show`. The filter tabs will appear to be broken.

**The actual root cause of finding #7** is not "the partial lacks `x-show` directives." It's that the live-update mechanism replaces server-rendered Alpine-annotated HTML with fresh server-rendered HTML, and the Alpine initialization lifecycle isn't threaded through. The correct fix is either:

1. Don't use Alpine `x-show` in the partial at all — keep filtering client-side in Alpine, make the partial only fire when the filter is "all", or
2. Use server-side filtering: the partial route already accepts a `?status=` param (`partials.py:43`), so trigger the refresh with `?status=` matching `activeTab` — pass `activeTab` as a query param from Alpine — and emit only matching rows

Option 2 is already almost implemented (`manifest_list_partial` filters by `status` at `partials.py:43`). The design ignores this existing filter capability entirely.

**Evidence:**
- `partials.py:43` — `manifests = [m for m in manifests if m.status == status]` — server-side filtering already exists
- `apps.html:48` — `data-live-on-app="/ui/partials/manifest-list"` — no `?status=` param passed
- `live-updates.js:91` — swap is `morph:innerHTML`, not `alpine-morph`

**Design question:** If server-side filtering already exists via `?status=` on the partial route, why not thread the active Alpine tab state into the HTMX request URL? Something like `data-live-on-app` dynamically computed from Alpine state, or an `hx-params` approach?

---

## Finding C — The `live-updates.js` Modification Is Underspecified to the Point of Unimplementable

**Severity: HIGH**

### What the design says

Design §2, step 4: "Update `live-updates.js` to detect which morph extension an element uses and set the correct swap strategy."

### Why this is a problem

`live-updates.js:91` hardcodes the swap strategy:
```js
htmx.ajax("GET", refreshUrl, { target: target, swap: "morph:innerHTML" });
```

The design says we should detect `hx-ext="alpine-morph"` on an element and use a different swap string. But:

1. `hx-ext` is an htmx attribute for declarative extensions on static HTMX elements. When `live-updates.js` issues `htmx.ajax(...)` programmatically, it bypasses the declarative htmx pipeline entirely. The swap strategy is set in the JS call, not read from the element's `hx-ext`.

2. For `alpine-morph` to work, the htmx extension must be active. Extensions are registered via `<script src="...alpine-morph.js">` and activated per-element via `hx-ext="alpine-morph"` **on declarative htmx elements**. Programmatic `htmx.ajax()` calls do not consult `hx-ext` on the target element.

3. The correct swap string for Alpine morph is not documented as `morph:innerHTML` — it's typically just `innerHTML` with the extension handling the diff. The design doesn't specify what swap string to use.

The design is describing something that doesn't map to how `htmx.ajax()` and htmx extensions actually interact. The JS change would need to be: when an element has `data-live-on-app` AND `hx-ext="alpine-morph"`, change the programmatic ajax call's swap value. But this is cargo-culting the htmx extension system into a non-extension code path.

**The simpler design**: Don't use programmatic `htmx.ajax()` for alpine-morph elements. Instead, annotate the container with declarative htmx attributes (`hx-get`, `hx-trigger`, `hx-swap`, `hx-ext`) and fire an htmx event to trigger them. The WS event handler in `live-updates.js` would dispatch an htmx event that the container listens for, instead of calling `htmx.ajax()` directly. This keeps the extension system in the declarative htmx path where `hx-ext` is actually consulted.

**Evidence:**
- `live-updates.js:91` — `htmx.ajax("GET", refreshUrl, { target: target, swap: "morph:innerHTML" })` — programmatic, bypasses extension system
- Design §2 step 4 — "detect which morph extension an element uses" — no code example, no swap string specified

**Design question:** Has the implementer verified that `htmx.ajax()` with a custom swap string actually invokes the `alpine-morph` extension? The htmx source would need to be checked.

---

## Finding D — Batch Query Design Has a Multi-Instance Gap

**Severity: MEDIUM**

### What the design says

Design §1: `get_all_app_summaries()` uses `GROUP BY app_key` across two queries to return per-app health metrics.

### The gap

`context.py:123` shows the current code only uses the first instance's data:
```python
instance_index = manifest.instances[0].index if manifest.instances else 0
```

A multi-instance app (e.g., 3 instances of `lights_controller`) has listeners and jobs registered under each `instance_index`. The proposed `GROUP BY app_key` query would aggregate across ALL instances — which is actually the right behavior for the dashboard grid. But the new `AppHealthSummary` model's field name `handler_count` is ambiguous: is it listeners across all instances, or just instance 0?

The design says nothing about how multi-instance apps are handled. If `GROUP BY app_key` sums across instances, then an app with 3 instances and 5 listeners each will show `handler_count=15`. This is wrong for the dashboard grid, which currently shows per-instance counts. If `GROUP BY app_key` only looks at `instance_index=0`, the fix is incomplete for multi-instance apps — the original N+1 per-instance-index bug would reappear.

The design also doesn't address whether `session_id` filtering (present in both current query methods) is included in the batch query. Dashboard uses session-scoped data implicitly (via the current `compute_app_grid_health` which calls `get_listener_summary` without session_id).

**Evidence:**
- `context.py:123` — hardcodes `instance_index = manifest.instances[0].index`
- `telemetry_query_service.py:50-54` — `get_listener_summary` takes `instance_index` as a required param; the batch query elides this

**Design question:** Does the `AppHealthSummary` represent one instance or all instances of an app? If all instances, how should the dashboard grid present a 3-instance app — aggregate health or per-instance breakdown?

---

## Finding E — Findings #4 and #5 Are Genuinely Simple and Well-Specified

**Severity: Not a flaw — these are correct**

Wiring `GlobalSummary` and `SessionSummary` (design §4) is a mechanical change with clear before/after: `dict | None` → typed model, `.get()` → attribute access. No hidden traps.

`classify_error_rate()` and `classify_health_bar()` (design §5) are pure functions with clear thresholds. Passing them as Jinja2 globals via `templates.env.globals` is the right mechanism. The design doesn't specify this mechanism, but it's the obvious implementation.

Both are justified, scoped correctly, and not trying to solve the wrong problem.

---

## Finding F — Deleting the Dead Polling Div Is Correct, But the Justification Is Circular

**Severity: LOW — correctness concern, not a blocking issue**

Design §3 says the stats-only polling div is safe to delete because "alpine-morph preserving state makes it redundant."

But Finding A above shows that alpine-morph does NOT fully preserve loaded state — the detail div content will still be morphed. If the polling div deletion is predicated on alpine-morph solving the problem it doesn't fully solve, then deleting it might remove a partial mitigation.

However, the polling div was also identified as broken dead code (critique §3: "renders `data-*` attributes that nothing reads"). It should be deleted regardless of whether alpine-morph works, because it never worked in the first place. The justification should say "delete because it was never effective, not because alpine-morph replaces it."

---

## What the Simplest Design Looks Like

The design is solving six real problems but introduces two new technical risks (Finding A, B) and leaves one underspecified (Finding C). Here's the simpler path:

**For finding #2 (Alpine state preservation):** Don't morph the handler/job lists at all on `app_status_changed`. Instead, update only the stats in-place. Each `handler_row` already has `id="handler-{{ listener.listener_id }}"`. A targeted partial that returns only a stats fragment swapped into `.ht-item-row__stats` within each row would update counts without touching `open`/`loaded` state or the detail div. This is more surgical than alpine-morph and requires no new CDN script.

**For finding #7 (manifest partial):** Thread `activeTab` into the refresh URL. In `apps.html`, change `data-live-on-app` to a dynamic value computed from Alpine: `:data-live-on-app="'/ui/partials/manifest-list?status=' + (activeTab === 'all' ? '' : activeTab)"`. Then `live-updates.js` reads the attribute at refresh time — the URL already has the filter param. The partial's existing `?status=` filtering (`partials.py:43`) does the work server-side. No Alpine directives needed in the partial, no scope propagation problem.

**For finding #3 (dead polling):** Delete unconditionally — the code never worked.

**For findings #1, #4, #5:** The design's approach is correct. Implement as specified.

---

## Summary Table

| Finding | Design Status | Risk |
|---------|--------------|------|
| #1 Batch queries | Correct — implement | Multi-instance gap (Finding D) |
| #2 Alpine morph | Partial fix — loaded detail still clobbered | HIGH — users will still lose expanded content |
| #3 Delete polling | Correct, wrong justification | LOW |
| #4 Wire typed models | Correct | None |
| #5 Centralize thresholds | Correct | None |
| #7 Manifest partial | Wrong approach — scope propagation won't work | HIGH — tab filter will break on live update |
| JS update (#2 impl) | Underspecified — `htmx.ajax()` bypasses extensions | HIGH — may not be implementable as described |
