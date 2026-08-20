/**
 * Test utilities for `useScopedQuery` hook tests.
 *
 * `renderScopedQuery()` renders the hook behind a fresh QueryClientProvider with the given base
 * key, fetcher, and store/hook options — the render shape every `useScopedQuery` test starts
 * from. `renderAndWaitForFirstFetch()` additionally waits for the first fetch to land, which most
 * refetch-behavior tests need before mutating the store and asserting on a subsequent fetch.
 * `waitForFetchCalled()` / `waitForFetchCount()` wait on the fetcher mock directly, and
 * `expectFetchSince()` combines a "called" wait with the `since` argument assertion every
 * fixed-window-preset test makes.
 */

import type { Mock } from "vitest";
import { expect, vi } from "vitest";

import type { UseScopedQueryOptions } from "../hooks/use-scoped-query";
import { useScopedQuery } from "../hooks/use-scoped-query";
import type { AppStore } from "../state/store";
import { renderHookWithProviders } from "./query-test-utils";

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

/** Waits for the fetcher to have been called at least once — the "fetch has fired" check every
 * fixed-window-preset test makes before asserting the exact `since` argument. */
export async function waitForFetchCalled(fetcher: ScopedFetcherMock<unknown>) {
  await vi.waitFor(() => {
    expect(fetcher).toHaveBeenCalled();
  });
}

/** Waits for the fetcher to have been called exactly `times` times — the refetch-count check most
 * tests make after a store change that should (or shouldn't) trigger a new fetch. */
export async function waitForFetchCount(fetcher: ScopedFetcherMock<unknown>, times: number) {
  await vi.waitFor(() => {
    expect(fetcher).toHaveBeenCalledTimes(times);
  });
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
  await waitForFetchCount(fetcher, 1);
}

/**
 * Waits for the fetcher to be called, then asserts it received `expectedSince` — the pattern
 * shared by every fixed-window-preset test (1h/24h/7d/url-override), which differ only in preset
 * and expected `since` value.
 */
export async function expectFetchSince(fetcher: ScopedFetcherMock<unknown>, expectedSince: number) {
  await waitForFetchCalled(fetcher);
  expect(fetcher).toHaveBeenCalledWith(expectedSince, expect.any(AbortSignal));
}
