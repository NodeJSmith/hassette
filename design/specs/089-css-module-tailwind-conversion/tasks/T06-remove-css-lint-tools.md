---
task_id: "T06"
title: "Remove CSS lint tools and update CI"
status: "planned"
depends_on: ["T05"]
implements: ["FR#10", "FR#11", "AC#9", "AC#13"]
---

## Summary

Remove the 4 CSS-Module-specific lint tools that guarded conventions that no longer exist (CSS Modules and `ht-*` global classes). Update `check_dead_tokens.py` to scan `global.css` instead of `tokens.css`. Evaluate whether `check_breakpoint_drift.py` still applies. Remove the corresponding prek hook definitions and CI references.

## Target Files

- delete: `tools/frontend/check_css_module_globals.py`
- delete: `tools/frontend/check_dead_global_css.py`
- delete: `tools/frontend/check_global_css_allowlist.py`
- delete: `tools/frontend/check_undefined_css_refs.py`
- modify: `tools/frontend/check_dead_tokens.py`
- modify: `prek.toml`
- modify: `.github/workflows/lint.yml`
- read: `tools/frontend/check_breakpoint_drift.py`
- read: `design/specs/089-css-module-tailwind-conversion/design.md`

## Prompt

Remove the 4 CSS-Module-specific lint tools and update supporting configuration.

**Step 1 — Delete the 4 lint tool scripts:**

Delete these files:
- `tools/frontend/check_css_module_globals.py` — guarded `:global()` usage in `.module.css` files (no module files exist)
- `tools/frontend/check_dead_global_css.py` — found unreferenced selectors in `styles/*.css` (no style files exist except fonts.css)
- `tools/frontend/check_global_css_allowlist.py` — blocked new `.ht-*` selectors (no `.ht-*` classes exist)
- `tools/frontend/check_undefined_css_refs.py` — found raw `ht-*` refs in TSX with no CSS definition (no `ht-*` refs exist)

**Step 2 — Remove prek hook definitions:**

In `prek.toml`, remove the hook definition blocks for:
- `check-css-module-globals`
- `check-dead-global-css`
- `check-global-css-allowlist`
- `check-undefined-css-refs`

**Step 3 — Update CI:**

In `.github/workflows/lint.yml`, remove the smoke test step:
```yaml
- name: Smoke test CSS allowlist logic
  run: uv run python tools/frontend/check_global_css_allowlist.py --smoke-test
```

Also check whether the `prek run --group frontend --all-files` step references any of the removed hooks — if it uses prek's group mechanism, removing the hook definitions from `prek.toml` is sufficient.

**Step 4 — Update check_dead_tokens.py:**

`check_dead_tokens.py` currently scans `tokens.css` for unused token definitions. Update it to scan `global.css` instead (the new single source of token definitions). The scan logic should look for CSS custom property definitions in `:root` and `[data-theme="dark"]` blocks, then check for references in TSX/CSS files.

**Step 5 — Evaluate check_breakpoint_drift.py:**

Read `tools/frontend/check_breakpoint_drift.py`. This tool checks that JS breakpoint constants (`BREAKPOINT_SIDEBAR`, `BREAKPOINT_MOBILE`, `BREAKPOINT_SMALL_MOBILE` in `use-media-query.ts`) match CSS breakpoint values. After T01 registered custom Tailwind screens (`--breakpoint-sidebar`, `--breakpoint-mobile`, `--breakpoint-small-mobile` in `@theme`), the tool should verify JS constants match the `@theme` screen registrations. If the tool already supports this pattern, keep it. If it only scanned `.module.css` or `styles/*.css` files, update it to scan `global.css`'s `@theme inline` block.

**Step 6 — Verify prek passes:**

Run `prek -a` to confirm all remaining hooks pass after the removals.

## Focus

- `prek.toml` has 6 CSS-related hooks: `check-breakpoint-drift`, `check-css-module-globals`, `check-dead-global-css`, `check-dead-tokens`, `check-global-css-allowlist`, `check-undefined-css-refs`. We remove 4, update 1 (`check-dead-tokens`), and evaluate 1 (`check-breakpoint-drift`).
- The CI `lint.yml` step `prek run --group frontend --all-files --show-diff-on-failure` runs all hooks in the `frontend` group. Removing hooks from `prek.toml` is sufficient — prek will no longer discover them. But verify the `--group frontend` filter doesn't hard-code hook names.
- The `check_global_css_allowlist.py` has a `--smoke-test` flag that CI runs separately before the prek group. This step must be removed from `lint.yml`.

## Verify

- [ ] FR#10: `ls tools/frontend/check_css_module_globals.py tools/frontend/check_dead_global_css.py tools/frontend/check_global_css_allowlist.py tools/frontend/check_undefined_css_refs.py 2>/dev/null | wc -l` returns 0.
- [ ] FR#11: `check_dead_tokens.py` references `global.css` instead of `tokens.css`. `check_breakpoint_drift.py` is either updated or confirmed still valid.
- [ ] AC#9: Same as FR#10 — the 4 files do not exist.
- [ ] AC#13: `prek -a` exits 0 with no errors from removed or misconfigured hooks.
