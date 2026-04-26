/**
 * Shared render helpers for components that require AppStateContext.
 *
 * Use `renderWithAppState` when testing components that call `useAppState()`.
 * Components that do not use context can use `render` from @testing-library/preact
 * directly.
 */

import type { ComponentChildren } from "preact";
import { render } from "@testing-library/preact";
import { AppStateContext } from "../state/context";
import { createAppState, type AppState } from "../state/create-app-state";

interface RenderWithAppStateOptions {
  stateOverrides?: Partial<AppState>;
}

/**
 * Renders a Preact component tree wrapped in AppStateContext.Provider.
 *
 * A fresh AppState is created for each call. Pass `stateOverrides` to replace
 * individual signals or methods on the default state.
 */
export function renderWithAppState(
  ui: ComponentChildren,
  { stateOverrides }: RenderWithAppStateOptions = {},
) {
  const state: AppState = { ...createAppState(), ...stateOverrides };

  return render(
    <AppStateContext.Provider value={state}>
      {ui}
    </AppStateContext.Provider>,
  );
}
