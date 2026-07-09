import type { Signal } from "@preact/signals";

import { useSignal } from "./use-signal";

export interface UseAsyncActionResult {
  /** True while an action is in flight. */
  loading: Signal<boolean>;
  /** Error message from the most recent failed action, or null. */
  error: Signal<string | null>;
  /**
   * Runs `action`, tracking `loading`/`error`. Ignores the call if an action
   * is already in flight. Clears `error` before starting and always resets
   * `loading` when the action settles.
   */
  run: (action: () => Promise<unknown>) => Promise<void>;
}

/**
 * Shared loading/error wrapper for button-triggered async actions (start,
 * stop, reload, run-now, etc.). Guards against concurrent invocation,
 * extracts a display message from thrown errors, and resets state when the
 * action settles.
 */
export function useAsyncAction(): UseAsyncActionResult {
  const loading = useSignal(false);
  const error = useSignal<string | null>(null);

  const run = async (action: () => Promise<unknown>) => {
    if (loading.value) return;
    error.value = null;
    loading.value = true;
    try {
      await action();
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
  };

  return { loading, error, run };
}
