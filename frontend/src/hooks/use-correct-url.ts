/**
 * Centralized URL correction hook.
 *
 * When a page detects invalid URL state (unknown handler ID, out-of-range
 * instance, unrecognized filter value), it calls the function returned by
 * this hook with the corrected URL.
 *
 * The correction is applied via navigate(correctedUrl, { replace: true })
 * so the browser history does not accumulate invalid entries.
 *
 * Usage:
 *   const correctUrl = useCorrectUrl();
 *   // After data load confirms handler doesn't exist:
 *   correctUrl("/apps/foo/handlers");
 */

import { useCallback } from "preact/hooks";
import { useLocation } from "wouter";

export function useCorrectUrl(): (correctedUrl: string) => void {
  const [, navigate] = useLocation();

  return useCallback((correctedUrl: string): void => {
    navigate(correctedUrl, { replace: true });
  }, [navigate]);
}
