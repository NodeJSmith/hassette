import { useEffect, useState } from "preact/hooks";

/** Must match CSS `@media (max-width: 768px)` breakpoints in global.css */
export const BREAKPOINT_MOBILE = 768;

/**
 * Returns true when the viewport width is at or below `maxWidth`.
 * Uses `window.matchMedia` and cleans up the listener on unmount.
 */
export function useMediaQuery(maxWidth: number): boolean {
  const query = `(max-width: ${maxWidth}px)`;
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const mql = window.matchMedia(query);
    setMatches(mql.matches);

    const handler = (e: MediaQueryListEvent | { matches: boolean }) => {
      setMatches(e.matches);
    };

    mql.addEventListener("change", handler);
    return () => {
      mql.removeEventListener("change", handler);
    };
  }, [query]);

  return matches;
}
