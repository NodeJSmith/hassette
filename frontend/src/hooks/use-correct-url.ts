/**
 * Centralized URL correction hook.
 *
 * When a page detects invalid URL state (unknown handler ID, out-of-range
 * instance, unrecognized filter value), it calls the function returned by
 * this hook with the corrected URL and a reason string.
 *
 * The correction is applied via navigate(correctedUrl, { replace: true })
 * so the browser history does not accumulate invalid entries.
 *
 * The reason string is appended to the module-level `correctionReasons`
 * array. This is the future hook point for toast notifications — when that
 * feature is added, `correctUrl` can emit the reason as a toast without
 * requiring changes to any page-level callers.
 *
 * Usage:
 *   const correctUrl = useCorrectUrl();
 *   // After data load confirms handler doesn't exist:
 *   correctUrl("/apps/foo/handlers", "handler h-999 not found");
 */

import { useLocation } from "wouter";

/**
 * Module-level log of all URL corrections applied during the session.
 * Exported for testability and future toast integration.
 */
const MAX_CORRECTION_REASONS = 100;
export const correctionReasons: string[] = [];

/**
 * Returns a function that navigates to a corrected URL (replace) and
 * records the reason string for future notification support.
 */
export function useCorrectUrl(): (correctedUrl: string, reason: string) => void {
  const [, navigate] = useLocation();

  return function correctUrl(correctedUrl: string, reason: string): void {
    if (correctionReasons.length >= MAX_CORRECTION_REASONS) correctionReasons.shift();
    correctionReasons.push(reason);
    navigate(correctedUrl, { replace: true });
  };
}
