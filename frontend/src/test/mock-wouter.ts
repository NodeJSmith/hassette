import { h } from "preact";

// Some callers only need the current path and omit the navigate function, so the tuple only
// pins the first element.
type LocationTuple = readonly [string, ...unknown[]];
type LinkProps = Record<string, unknown> & { href?: string; children?: unknown };

function defaultLink({ href, children, class: cls, ...rest }: LinkProps) {
  return h("a", { href, class: cls, ...rest }, children as never);
}

interface CreateWouterMockOptions {
  useLocation?: () => LocationTuple;
  useSearch?: () => string;
  Link?: (props: LinkProps) => unknown;
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
 */
export function createWouterMock(overrides: CreateWouterMockOptions = {}) {
  return {
    Link: overrides.Link ?? defaultLink,
    ...(overrides.useLocation ? { useLocation: overrides.useLocation } : {}),
    ...(overrides.useSearch ? { useSearch: overrides.useSearch } : {}),
  };
}
