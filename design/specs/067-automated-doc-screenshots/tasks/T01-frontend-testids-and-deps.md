---
task_id: "T01"
title: "Add screenshot data-testid attributes and shot-scraper dependency"
status: "planned"
depends_on: []
implements: ["FR#4", "AC#3"]
---

## Summary
Add the missing `data-testid` attributes to three frontend components so they can be targeted by shot-scraper's CSS selector-based element capture. Also add `shot-scraper` to the dev dependency group and reduce the demo stimulator's failure interval so error data appears quickly during screenshot capture.

These are prerequisites for the manifest and wrapper script — without the testids, element-level screenshots cannot be captured; without the dependency, shot-scraper cannot run.

## Prompt
Make five small changes across the codebase:

1. **`frontend/src/components/shared/log-table/log-detail-drawer.tsx`** — Add `data-testid="log-detail-drawer"` to the root `<aside>` element at line 120. The element currently has `ref={drawerRef}`, `class={clsx(...)}`, `role="complementary"`, and `aria-label="Log entry detail"`. Add the testid alongside these attributes.

2. **`frontend/src/components/shared/column-filter-popover/index.tsx`** — Add `data-testid="column-picker-popover"` to the root `<div>` element at line 135. The element currently has `ref={popoverRef}`, `class={styles.popover}`, `role="dialog"`, `aria-label={label ?? "Column filter"}`, and `tabIndex={-1}`. Add the testid alongside these attributes.

3. **`frontend/src/components/app-detail/unified-handler-row.tsx`** — Add `data-testid="handler-failed-count"` to the `<span class={styles.statsErr}>` element at line 147. This span renders the "{N} failed" text for handlers with errors.

4. **`pyproject.toml`** — Add `"shot-scraper>=1.5"` to the `[dependency-groups] dev` list (line 78-83).

5. **`examples/demo_stimulator.py`** — Change `failure_interval: float = 60.0` (line 29) to `failure_interval: float = 5.0`.

## Focus
- The `<aside>` in `log-detail-drawer.tsx` returns `null` when no log entry is selected — the testid only appears when the drawer is open. This is correct behavior for shot-scraper: the manifest JS clicks a log row first, then `wait_for` ensures the element exists before capture.
- `ColumnFilterPopover` returns `null` when `open` is false (line 132). Same pattern — the testid only exists when open.
- The `statsErr` span in `unified-handler-row.tsx` only renders when `failed > 0` (line 147: `{failed > 0 && <span ...>}`). The manifest JS must navigate to the right page and wait for error data before this element exists.
- `ColumnFilterPopover` is also used by `sort-header.tsx` (line 153). The added testid appears on all popover instances, but only the column picker instance is targeted by the screenshot manifest (via clicking the column-picker trigger button first).
- The `pyproject.toml` uses `[dependency-groups]` (PEP 735), not `[project.optional-dependencies]` for the dev group.

## Verify
- [ ] FR#4: `data-testid="log-detail-drawer"` exists on the `<aside>` in `log-detail-drawer.tsx`; `data-testid="column-picker-popover"` exists on the popover `<div>` in `column-filter-popover/index.tsx`; `data-testid="handler-failed-count"` exists on the failed-count `<span>` in `unified-handler-row.tsx`
- [ ] AC#3: `grep 'shot-scraper' pyproject.toml` matches the dev dependency group; `grep 'failure_interval.*5.0' examples/demo_stimulator.py` matches the reduced interval
