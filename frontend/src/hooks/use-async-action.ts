import { useState } from "react";

export interface UseAsyncActionResult {
  /** True while an action is in flight. */
  loading: boolean;
  /** Error message from the most recent failed action, or null. */
  error: string | null;
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<unknown>) => {
    if (loading) return;
    setError(null);
    setLoading(true);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return { loading, error, run };
}
