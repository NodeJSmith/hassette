/**
 * Shared render helpers for components that require AppStateContext.
 *
 * Use `renderWithAppState` when testing components that call `useAppState()`.
 * Components that do not use context can use `render` from @testing-library/preact
 * directly.
 */

import { QueryClientProvider } from "@tanstack/preact-query";
import { render } from "@testing-library/preact";
import type { ComponentChildren } from "preact";

import { AppStateContext } from "../state/context";
import { type AppState, createAppState } from "../state/create-app-state";
import { createTestQueryClient } from "./query-test-utils";

interface RenderWithAppStateOptions {
  stateOverrides?: Partial<AppState>;
}

/**
 * Renders a Preact component tree wrapped in QueryClientProvider and
 * AppStateContext.Provider.
 *
 * A fresh AppState and QueryClient are created for each call. Pass
 * `stateOverrides` to replace individual signals or methods on the default
 * state.
 *
 * The QueryClient uses test defaults (retry: false, staleTime: 0) so existing
 * tests that don't touch queries are unaffected. Tests for components that call
 * useQuery will go through normal query lifecycle backed by MSW handlers.
 */
export function renderWithAppState(ui: ComponentChildren, { stateOverrides }: RenderWithAppStateOptions = {}) {
  const state: AppState = { ...createAppState(), ...stateOverrides };
  const queryClient = createTestQueryClient();

  return render(
    <QueryClientProvider client={queryClient}>
      <AppStateContext.Provider value={state}>{ui}</AppStateContext.Provider>
    </QueryClientProvider>,
  );
}
