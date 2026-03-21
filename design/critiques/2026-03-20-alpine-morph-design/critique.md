# Design Critique: 010-alpine-morph-fix — 2026-03-20

Adversarial design critique of `design/specs/010-alpine-morph-fix/design.md`. Three independent critics reviewed the design proposal to replace the stats polling workaround with alpine-morph.

## Findings

### 1. Expanded Row Content Destroyed on Every Morph — CRITICAL

**What's wrong**: Alpine-morph preserves the reactive proxy (`open: true`, `loaded: true`), but reconciles child DOM against the incoming server HTML. The server always sends `#handler-N-detail` with only the "Loading invocations..." placeholder. After morph, the loaded invocation history is replaced by the placeholder. Since `loaded` stays `true`, re-expanding never re-fetches. The user sees a permanently broken expanded row.
**Why it matters**: Silent data loss on every `app_status_changed` event.
**Evidence (code)**:
- `macros/ui.html:56` — `x-data="{ open: false, loaded: false }"`
- `macros/ui.html:62` — load gate: no re-fetch once `loaded = true`
- `macros/ui.html:94-99` — `#handler-N-detail` always renders the loading placeholder
**Raised by**: Senior + Adversarial
**Better approach**: Use Alpine morph's `updating` callback to skip morphing detail div children when `loaded === true`, or reset `loaded = false` after morph.

### 2. Heading Counts Are Permanently Stale — HIGH

**What's wrong**: `Event Handlers (N registered)` heading sits OUTSIDE the morphed `#app-handlers` div. After morph, heading is frozen at page-load count.
**Evidence (code)**: `app_detail.html:111`, `app_detail.html:136`
**Raised by**: Adversarial
**Better approach**: Expand morph container to include heading, or move count into partial.

### 3. Alert Banner Rows Have No `id` — Positional State Leakage — HIGH

**What's wrong**: `alert_failed_apps.html:25` — per-app items have no `id`. Alpine morph falls back to positional matching. State leaks between rows when the list changes.
**Raised by**: Senior
**Better approach**: Add `id="alert-item-{{ app.app_key }}"`.

### 4. `data-live-swap` Is Redundant — Should Derive from `hx-ext` — HIGH

**What's wrong**: Two synchronized attributes required per container (`hx-ext` + `data-live-swap`). Divergence is silent.
**Raised by**: Architect
**Better approach**: Derive swap strategy from `hx-ext` presence: `target.getAttribute("hx-ext") === "alpine-morph" ? "morph" : "morph:innerHTML"`.

### 5. All `data-live-on-app` Elements Fire on Every App's Status Change — MEDIUM

**What's wrong**: No app_key filtering in `live-updates.js:113-118`. Every cross-app event triggers unnecessary fetches.
**Raised by**: Adversarial
**Better approach**: Filter by comparing `detail.app_key` against the target URL.

### 6. CDN Scripts Should Be Vendored — MEDIUM

**What's wrong**: Two new synchronous CDN scripts. HA runs locally; offline setups fail.
**Raised by**: Senior
**Better approach**: Vendor into `static/js/vendor/`.

## Appendix: Individual Critic Reports

- Senior Engineer: `/tmp/claude-mine-challenge-6FURoH/senior.md`
- Systems Architect: `/tmp/claude-mine-challenge-6FURoH/architect.md`
- Adversarial Reviewer: `/tmp/claude-mine-challenge-6FURoH/adversarial.md`
