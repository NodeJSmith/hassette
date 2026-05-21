import { type Signal, signal } from "@preact/signals";
import { useRef } from "preact/hooks";

/**
 * Creates a component-local signal that persists across re-renders.
 * Equivalent to `useRef(signal(init)).current` but communicates intent.
 */
export function useSignal<T>(initialValue: T): Signal<T> {
  return useRef(signal(initialValue)).current;
}
