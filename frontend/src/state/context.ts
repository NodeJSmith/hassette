import { createContext } from "preact";
import { useContext } from "preact/hooks";
import type { AppState } from "./create-app-state";

export const AppStateContext = createContext<AppState>(null!);

export function useAppState(): AppState {
  const state = useContext(AppStateContext);
  if (!state) {
    throw new Error("useAppState must be used within an AppStateContext.Provider");
  }
  return state;
}
