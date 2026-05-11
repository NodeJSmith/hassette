---
task_id: "T09"
title: "Finalize migration and activate CI guards"
status: "planned"
depends_on: ["T08"]
implements: ["FR#9", "FR#10", "AC#1", "AC#7", "AC#8"]
---

## Summary
Audit the remaining `global.css` content, activate CI guards in blocking mode, update CLAUDE.md with the new CSS architecture documentation, and do a final verification pass across all viewports and themes.

## Prompt
1. **Audit `global.css`**: Run `wc -l frontend/src/global.css` — should be under 500 lines. If over, scan for any component-specific classes that were missed during batches T03-T08. Move any remaining component-specific classes to their modules.

2. **Activate lint guard in full-file mode**: Update `tools/check_global_css_allowlist.py` to remove the `--diff-only` default and run against the full file. Update the `lint.yml` step to call without `--diff-only`. This catches any future additions.

3. **Activate dead CSS detection as blocking**: Update the `lint.yml` step from `|| true` (warning) to a normal exit (blocking). Any unreferenced selector in `global.css` now fails CI.

4. **Remove orphaned CSS**: Run `tools/check_dead_global_css.py` and remove any selectors it reports (outside the exemption list). These are classes that survived the migration but are no longer referenced.

5. **Update CLAUDE.md**: Add a "CSS Architecture" section after the existing "Code Style" section:
   - Component styles use CSS Modules (`.module.css` co-located with components)
   - `import styles from './component.module.css'` + `class={styles.foo}` pattern
   - Global classes (`ht-btn`, `ht-card`, etc.) used as plain strings alongside module classes
   - `clsx` for conditional class composition: `class={clsx(styles.foo, isActive && styles.active, "ht-btn")}`
   - `:global()` for state modifiers: `.item:global(.is-active) { ... }`
   - `:global()` for cross-component rules: `:global(.ht-drawer) .sidebar { ... }`
   - `:global([data-theme="dark"])` for theme overrides in modules
   - New component styles go in `.module.css` — never in `global.css`
   - CI enforces: allowlist guard, dead CSS detection, `:global()` correctness

6. **Final verification**: Run the full verification baseline one last time:
   - `cd frontend && npm run build`
   - `cd frontend && npx vitest run`
   - `nox -s frontend && nox -s e2e`

7. **Report final metrics**: `wc -l frontend/src/global.css`, count of `.module.css` files, count of remaining `.ht-` selectors in global.css.

## Focus
- The 500-line target is a sanity check, not a hard gate. If `global.css` is 510 lines because more shared utilities are legitimately cross-cutting, that's fine. The real constraint is "only genuinely shared classes stay."
- The CLAUDE.md update is important for future Claude sessions — it establishes the convention so new code follows the module pattern.
- Dead CSS detection becoming blocking means the exemption list in `check_dead_global_css.py` must be correct — review it against the current dynamic class families.
- Check that `tokens.css` is still byte-identical: `git diff frontend/src/tokens.css` should show no changes.

## Verify
- [ ] FR#9: `tools/check_global_css_allowlist.py` (full-file mode) exits 0 on current `global.css`; exits 1 when a fake component selector is added
- [ ] FR#10: `tools/check_dead_global_css.py` runs without false positives on the final `global.css`
- [ ] AC#1: `global.css` is under 500 lines (report exact count)
- [ ] AC#7: The allowlist script in full-file blocking mode is wired into `lint.yml`
- [ ] AC#8: The dead CSS script in blocking mode is wired into `lint.yml`
