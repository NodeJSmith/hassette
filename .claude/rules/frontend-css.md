---
paths:
  - "frontend/**"
---

# Frontend Styling

Design direction and implementation-level visual rules both live in `design/context.md` — it is the single design reference for the frontend.

## CSS Architecture

The frontend uses Tailwind CSS v4 via `@tailwindcss/vite`. Tailwind Preflight is enabled through `@import "tailwindcss"` in `src/global.css`, which is the single CSS entry point for theme registration, token definitions, base element styles, and any rare shared component-layer rules. The only other CSS file is `src/styles/fonts.css`, imported by `global.css` for self-hosted `@font-face` declarations. There are no CSS Modules, no `ht-*` global utility classes, and no separate `tokens.css` file.

Besides the custom screens (below) and the radius scale, `@theme inline` registers only shadcn's fixed color vocabulary plus the `foreground-secondary`/`foreground-faint` text colors. Other project tokens (`--border-subtle`, `--text-body`, `--font-heading`, etc.) are deliberately not registered: they are consumed only as arbitrary values (`border-[var(--border-subtle)]`, `text-[length:var(--text-body)]`). A bare `text-body` at a call site is a bug at the call site, not a reason to register the token.

`global.css` owns both Hassette source tokens (`--bg-page`, `--ink-1`, spacing, typography, status colors, z-index values) and shadcn-compatible aliases (`--background`, `--foreground`, `--primary`, `--border`, `--muted-foreground`, etc.). New code should reference the shadcn-named tokens where possible so custom markup and shadcn/ui primitives read the same design roles. Custom Tailwind screens are registered in `@theme inline` for the project's non-standard breakpoints: `tablet` 1024px, `sidebar` 900px, `mobile` 768px, and `small-mobile` 480px.

### `--accent` means brand color, not shadcn's accent

shadcn's `--accent` is a subtle highlighted-background role (hover/active row state), a different concept from Hassette's `--accent`, which is the brand/action color. So:

- Hassette's brand color stays `--accent` and is additionally exposed to shadcn components as `--primary` (`oklch(0.5 var(--accent-chroma) var(--accent-hue))`), which shadcn's button/badge/etc. variants read.
- shadcn's highlighted-background role is exposed as `--highlight-bg` (mapped to `--bg-active`), never under the literal name `--accent`.

See the comment above the shadcn variable aliases in `global.css`'s `:root` block for the full mechanism.

### Component styling

Use Tailwind utilities directly in JSX. Compose conditional class names with `cn()` from `@/lib/utils`; do not import `clsx` directly and do not add CSS Modules.

```tsx
import { cn } from "@/lib/utils";

<div className={cn("rounded-md border border-border p-4", isActive && "bg-[var(--highlight-bg)]")}>
```

Use arbitrary values for project tokens without a named Tailwind utility, e.g. `text-[var(--handler-job)]`, `max-w-[var(--size-content-narrow)]`, `z-[var(--z-status-bar-layer)]`. Do not use `@apply`; if a pattern is too awkward for inline utilities and genuinely shared, put a small named rule in `@layer components` in `global.css`.

A module-level constant holding a Tailwind class string is named `FOO_CLASS` / `FOO_CLASSES`, never `fooClassName`/`fooClassNames`. The `no-unknown-classes` lint rule (below) finds these constants by name via `settings.tailwindcss.variablePatterns`, so a differently-named constant escapes validation; `no-restricted-syntax` in `eslint.config.js` enforces the convention.

### shadcn components

`components.json` configures the New York style with `@/components/ui` as the component directory: `button`, `badge`, `card`, `tooltip`, `dialog`, `alert-dialog`, `popover`, `command`, `drawer`, `table`. Use these instead of rebuilding standard controls with raw markup (`<Button variant="ghost" size="sm">`, `<Badge variant="danger" size="sm">`). Their tests live in `components/shared/` (e.g. `components/shared/button.test.tsx`), treating `components/ui/` as vendored primitives.

Don't hand-roll non-trivial UI primitives (form widgets, schema-driven forms, complex inputs) when a maintained library exists — the edge cases (array editing, dirty tracking, error plumbing, accessibility) are where the bugs live. The bundle-size budget (`frontend/.size-limit.json`) measures the entry chunk only, so `React.lazy` on the route or component that pulls in a large library keeps it off the budget.

### CI guards

- **`tools/frontend/check_breakpoint_drift.py`** — JS breakpoint constants in `use-media-query.ts` must match the Tailwind screens in `global.css`.
- **`tools/frontend/check_dead_tokens.py`** — flags unused CSS custom properties in `global.css`.
- **`no-unknown-classes`** (`oxlint-tailwindcss`, via `.oxlintrc.json`; prek hook `check-unknown-tailwind-classes`) — compiles `global.css`'s real `@theme` and flags any class string, literal or `FOO_CLASS` constant, that doesn't resolve to real CSS (e.g. `text-foreground-secondary` when `--foreground-secondary` was never registered).
