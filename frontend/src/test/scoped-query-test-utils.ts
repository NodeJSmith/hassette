/**
 * Test utilities for `useScopedQuery` hook tests.
 *
 * `renderScopedQuery()` renders the hook behind a fresh QueryClientProvider with the given base
 * key, fetcher, and store/hook options — the render shape every `useScopedQuery` test starts
 * from. `renderAndWaitForFirstFetch()` additionally waits for the first fetch to land, which most
 * refetch-behavior tests need before mutating the store and asserting on a subsequent fetch.
 * `expectFetchSince()` combines an internal "called" wait with the `since` argument assertion
 * every fixed-window-preset test makes. Call-count waiting itself is `query-test-utils.tsx`'s
 * generic `waitForCallCount()` — import it directly rather than re-declaring it here.
 */

import type { Mock } from "vitest";
import { expect } from "vitest";

import type { UseScopedQueryOptions } from "../hooks/use-scoped-query";
import { useScopedQuery } from "../hooks/use-scoped-query";
import type { AppStore } from "../state/store";
import { renderHookWithProviders, waitForCallCount } from "./query-test-utils";

interface RenderScopedQueryOptions {
  storeOverrides?: Partial<AppStore>;
  hookOptions?: UseScopedQueryOptions;
}

/** A `vi.fn()`-created fetcher mock matching `useScopedQuery`'s fetcher signature — every test in
 * this file creates one of these and passes it straight to the helpers below. */
type ScopedFetcherMock<T> = Mock<(since: number, signal: AbortSignal) => Promise<T>>;

/**
 * Renders `useScopedQuery` behind a fresh QueryClientProvider, seeding the app store with
 * `storeOverrides` — the render shape every `useScopedQuery` test starts from.
 */
export function renderScopedQuery<T>(
  key: string,
  fetcher: ScopedFetcherMock<T>,
  { storeOverrides, hookOptions }: RenderScopedQueryOptions = {},
) {
  return renderHookWithProviders(() => useScopedQuery([key], fetcher, hookOptions), { storeOverrides });
}

/**
 * Renders `useScopedQuery` and waits for its first fetch to land — the combination every
 * refetch-behavior test needs before mutating the store and asserting on a subsequent fetch.
 */
export async function renderAndWaitForFirstFetch<T>(
  key: string,
  fetcher: ScopedFetcherMock<T>,
  options: RenderScopedQueryOptions = {},
) {
  renderScopedQuery(key, fetcher, options);
  await waitForCallCount(fetcher, 1);
}

/**
 * Waits for the fetcher to be called, then asserts it received `expectedSince` — the pattern
 * shared by every fixed-window-preset test (1h/24h/7d/url-override), which differ only in preset
 * and expected `since` value.
 *
 * Waits for exactly one call (`waitForCallCount(fetcher, 1)`), not "at least one" — call this
 * right after render, before the fetcher could plausibly have fired a second time.
 */
export async function expectFetchSince(fetcher: ScopedFetcherMock<unknown>, expectedSince: number) {
  await waitForCallCount(fetcher, 1);
  expect(fetcher).toHaveBeenCalledWith(expectedSince, expect.any(AbortSignal));
}
