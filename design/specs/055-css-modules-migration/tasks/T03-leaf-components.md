---
task_id: "T03"
title: "Migrate leaf components to CSS Modules"
status: "planned"
depends_on: ["T02"]
implements: ["FR#1", "FR#2", "FR#4", "FR#11", "FR#13", "AC#2", "AC#5", "AC#6", "AC#11", "AC#12", "AC#13"]
---

## Summary
Migrate the 6 simplest components from `global.css` to co-located `.module.css` files: spinner, empty-state, show-more-button, mini-sparkline, status-shape, and app-link. These have minimal cross-references and simple CSS, making them ideal for validating the migration mechanics. Update unit tests to use `data-testid` and ARIA attributes. This is the first batch that creates actual module files.

## Prompt
For each of the 6 components below, perform the full migration:

**Components (all in `frontend/src/components/shared/`):**
1. `spinner.tsx` — class: `.ht-spinner`, keyframe: `@keyframes ht-spin` (NOTE: `ht-spin` is a shared animation used by multiple components — keep it in `global.css`. Only move `.ht-spinner` styling, reference the global animation name.)
2. `empty-state.tsx` — classes: `.ht-empty`, `.ht-empty__icon`, `.ht-empty__title`, `.ht-empty__body`
3. `show-more-button.tsx` — class: `.ht-show-more`
4. `mini-sparkline.tsx` — class: `.ht-mini-sparkline`
5. `status-shape.tsx` — scan for component-specific classes; if only global utilities are used, skip (no empty modules)
6. `app-link.tsx` — scan for component-specific classes; if only global utilities are used, skip

**Per-component migration steps:**
1. **Grep for the component's classes** in `global.css` to find all rules to extract (including responsive overrides in media query blocks — check the labeled sections from T02).
2. **Create `<component>.module.css`** next to the `.tsx` file. Copy rules from `global.css`, renaming classes to drop the `ht-` prefix and convert from BEM kebab to camelCase (e.g., `.ht-empty__icon` → `.icon`, `.ht-empty__title` → `.title`). For nested BEM elements, use short descriptive names.
3. **Delete the moved rules from `global.css`**.
4. **Update the `.tsx` file**: Add `import styles from './<component>.module.css';` and `import clsx from 'clsx';` (if conditional classes are needed). Replace `class="ht-..."` string literals with `class={styles.xxx}`. For elements mixing global + module classes, use template literals or `clsx`.
5. **Update the `.test.tsx` file**: Replace `querySelector(".ht-...")` with `querySelector("[data-testid='...']")`. Add `data-testid` attributes to the component if missing. Replace any `className.toContain("is-...")` assertions with ARIA attribute checks.
6. **Update e2e tests** if any reference this component's classes (check `grep -rn 'ht-spinner\|ht-empty\|ht-show-more\|ht-mini-sparkline\|ht-status-shape\|ht-app-link' tests/e2e/`).

**Naming convention for module classes:**
- `.ht-spinner` → `.spinner` (root class matches component concept)
- `.ht-empty__icon` → `.icon` (BEM element becomes short name — scoping prevents conflicts)
- `.ht-empty__title` → `.title`

**After all 6 components:**
Run the verification baseline:
- `cd frontend && npm run build`
- `cd frontend && npx vitest run`
- `nox -s frontend && nox -s e2e`

## Focus
- `spinner.tsx` is the simplest — one class, one element. `spinner.test.tsx:13` has `querySelector(".ht-spinner")` — needs migration.
- `empty-state.tsx` already has `data-testid={testId}` prop — use it in tests.
- `status-shape.tsx` and `app-link.tsx` may use only global utility classes — check before creating modules. If no component-specific classes exist in `global.css`, skip them.
- The `@keyframes ht-spin` animation is shared (used by spinner and potentially elsewhere). Keep it in `global.css`. In `spinner.module.css`, reference it as `animation: ht-spin 1s linear infinite;` — the animation name stays global.
- AC#12 (no naming collisions) is validated by having two components both define a `.root` or similar generic class — CSS Modules scoping ensures they don't collide.
- AC#13 (mixed global + module classes) is validated by any element using both a `styles.xxx` reference and a global class string on the same element.

## Verify
- [ ] FR#1: Each migrated component has a co-located `.module.css` file with styles extracted from `global.css`
- [ ] FR#2: Two components defining identically-named classes (e.g., both have `.root`) produce no collision in the rendered output
- [ ] FR#4: At least one element renders with both a global class and a module-scoped class, and both apply
- [ ] FR#11: No migrated component's unit tests use `querySelector(".ht-<migrated-class>")`; state assertions use ARIA attributes
- [ ] FR#13: No `.module.css` file contains the `ht-` prefix in class names
- [ ] AC#2: Each migrated component has a `.module.css` file
- [ ] AC#5: `npx vitest run` passes
- [ ] AC#6: Unit tests for migrated components use `data-testid` or ARIA, not migrated class names
- [ ] AC#11: No `ht-` prefix in any `.module.css` file
- [ ] AC#12: Two modules with same-named classes produce distinct scoped output
- [ ] AC#13: Mixed global + module class element renders both styles
