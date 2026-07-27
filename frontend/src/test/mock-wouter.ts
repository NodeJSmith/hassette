import { createElement, type ReactNode } from "react";

// Some callers only need the current path and omit the navigate function, so the tuple only
// pins the first element.
type LocationTuple = readonly [string, ...unknown[]];
type LinkProps = Record<string, unknown> & { href?: string; children?: ReactNode };

function defaultLink({ href, children, className, ...rest }: LinkProps) {
  return createElement("a", { href, className, ...rest }, children);
}

interface CreateWouterMockOptions {
  useLocation?: () => LocationTuple;
  useSearch?: () => string;
}

/**
 * Builds the module shape for `vi.mock("wouter", () => createWouterMock(...))`.
 *
 * Every test file still needs its own literal `vi.mock("wouter", ...)` call — vitest hoists
 * `vi.mock` by scanning each test file's own source, so the call can't move into a shared
 * function. This helper only dedupes the factory body (the standard `<a>` Link stub), so most
 * call sites shrink to one line:
 *
 * ```ts
 * import { createWouterMock } from "../test/mock-wouter";
 *
 * vi.mock("wouter", () => createWouterMock());
 * // or, for pages/hooks that also read location/search:
 * vi.mock("wouter", () => createWouterMock({ useLocation: () => ["/apps", mockNavigate] }));
 * ```
 *
 * `useLocation`/`useSearch` are only added to the mocked module when passed — omit them for
 * components that never call them, matching how `wouter` behaves when unused.
 *
 * Import-order hazard: a plain top-level `import { createWouterMock } from "../test/mock-wouter"`
 * is only safe when that import path sorts (via eslint's import-sorter) *before* the test's
 * import of the component under test — otherwise, if the component transitively imports
 * "wouter" and its import runs first, this factory can execute before `createWouterMock`'s own
 * import has finished initializing, throwing "Cannot access before initialization". In practice
 * this only bites test files where the component-under-test import shares the same relative
 * depth as this module's import path (e.g. `src/app.test.tsx`, where both `./app` and
 * `./test/mock-wouter` are direct children of `src/` and can sort either way) — every test file
 * one directory deeper reaches this module via a parent-relative `../test/mock-wouter`, which
 * always sorts ahead of a same-directory `./component` import. If you hit that error, switch to
 * a dynamic import inside the factory instead (see `src/app.test.tsx` for the pattern).
 */
export function createWouterMock(overrides: CreateWouterMockOptions = {}) {
  return {
    Link: defaultLink,
    ...(overrides.useLocation ? { useLocation: overrides.useLocation } : {}),
    ...(overrides.useSearch ? { useSearch: overrides.useSearch } : {}),
  };
}
