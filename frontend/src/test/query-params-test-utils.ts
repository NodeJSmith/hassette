/**
 * Test utilities for `useQueryParams` hook tests.
 *
 * `renderAndSet()` renders `useQueryParams()` and fires `set(updates, options)` inside `act()` —
 * the shared shape every "useQueryParams.set" test starts with. The caller assigns the mocked
 * `mockSearch` value beforehand: that variable is declared per test file and closed over by that
 * file's own `vi.mock("wouter", ...)` factory, so it can't move into this shared helper.
 */

import { act, renderHook } from "@testing-library/react";

import type { QueryParamOptions } from "../hooks/use-query-params";
import { useQueryParams } from "../hooks/use-query-params";

/** Renders `useQueryParams()` and calls `set(updates, options)` inside `act()`, returning the
 * render result for tests that need to inspect state beyond the resulting navigate call. */
export function renderAndSet(updates: Record<string, string | null>, options?: QueryParamOptions) {
  const { result } = renderHook(() => useQueryParams());
  act(() => {
    result.current.set(updates, options);
  });
  return result;
}
