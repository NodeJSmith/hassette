/**
 * Shared render helpers for components that read from the Zustand app store.
 *
 * Use `renderWithAppState` when testing components that call `useAppStore()`.
 * Zustand needs no context provider — this only wraps in QueryClientProvider
 * and seeds the store with `storeOverrides` before rendering.
 */

import { QueryClientProvider } from "@tanstack/preact-query";
import { render } from "@testing-library/preact";
import type { ComponentChildren } from "preact";
import { vi } from "vitest";

import type { AppStore } from "../state/store";
import { useAppStore } from "../state/store";
import { createTestQueryClient } from "./query-test-utils";

/**
 * Forces `useMediaQuery` to report mobile or desktop.
 *
 * jsdom has no `matchMedia`; `test-setup.ts` stubs it to always report desktop, so any
 * test exercising a responsive branch has to override it. Pair with
 * `afterEach(() => vi.restoreAllMocks())`.
 */
export function mockMediaQueryMatches(matches: boolean) {
  vi.spyOn(window, "matchMedia").mockImplementation((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

interface RenderWithAppStateOptions {
  storeOverrides?: Partial<AppStore>;
}

/**
 * Renders a Preact component tree wrapped in QueryClientProvider, seeding the
 * Zustand app store with `storeOverrides` beforehand.
 *
 * A fresh QueryClient is created for each call. The store is a module-level
 * singleton — `storeOverrides` is applied via `useAppStore.setState()`, and
 * the global `afterEach` hook in `test-setup.ts` resets it between tests.
 *
 * The QueryClient uses test defaults (retry: false, staleTime: 0) so existing
 * tests that don't touch queries are unaffected. Tests for components that call
 * useQuery will go through normal query lifecycle backed by MSW handlers.
 */
export function renderWithAppState(ui: ComponentChildren, { storeOverrides }: RenderWithAppStateOptions = {}) {
  if (storeOverrides) useAppStore.setState(storeOverrides);
  const queryClient = createTestQueryClient();

  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}
