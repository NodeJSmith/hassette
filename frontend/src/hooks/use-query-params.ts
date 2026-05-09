/**
 * Thin hook wrapping wouter's useSearch() and useLocation() to provide
 * typed read/write access to URL query parameters.
 *
 * Contract:
 * - get(key): returns decoded value or null (empty string treated as absent)
 * - set(updates, options?): merges updates into current params and navigates;
 *   null/"" values remove the param; push: false (default) replaces history
 * - No-op guard: set() does nothing when the resulting param set equals the
 *   current one, preventing spurious navigation and re-render cascades.
 *
 * Encoding: values are written with encodeURIComponent (%20 for spaces, not +)
 * and read back with decodeURIComponent.
 */

import { useSearch, useLocation } from "wouter";

export interface QueryParamOptions {
  /** When true, pushes a new history entry. Default false = replace. */
  push?: boolean;
}

export interface UseQueryParamsResult {
  get(key: string): string | null;
  set(updates: Record<string, string | null>, options?: QueryParamOptions): void;
}

/**
 * Build a sorted, encoded query string from a plain object.
 * Keys with null/empty values are excluded.
 * Values are encoded with encodeURIComponent (%20 for spaces).
 */
function buildQueryString(entries: Map<string, string>): string {
  const parts: string[] = [];
  // Sort keys for stable comparison
  const sorted = Array.from(entries.entries()).sort(([a], [b]) => a.localeCompare(b));
  for (const [key, value] of sorted) {
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
  }
  return parts.join("&");
}

/**
 * Parse a raw query string (without leading ?) into a Map of decoded key→value pairs.
 * Empty values are excluded.
 */
function parseQueryString(raw: string): Map<string, string> {
  const map = new Map<string, string>();
  if (!raw) return map;
  for (const part of raw.split("&")) {
    const eqIdx = part.indexOf("=");
    if (eqIdx === -1) {
      const key = decodeURIComponent(part);
      if (key) map.set(key, "");
    } else {
      const key = decodeURIComponent(part.slice(0, eqIdx));
      const value = decodeURIComponent(part.slice(eqIdx + 1));
      if (key && value) map.set(key, value);
    }
  }
  return map;
}

export function useQueryParams(): UseQueryParamsResult {
  const rawSearch = useSearch();
  const [location, navigate] = useLocation();

  function get(key: string): string | null {
    const params = parseQueryString(rawSearch);
    return params.get(key) ?? null;
  }

  function set(updates: Record<string, string | null>, options: QueryParamOptions = {}): void {
    const { push = false } = options;

    // Build the new param set from current state
    const current = parseQueryString(rawSearch);

    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === "") {
        current.delete(key);
      } else {
        current.set(key, value);
      }
    }

    // Serialize both for comparison (both are sorted)
    const newSearch = buildQueryString(current);
    const currentSearch = buildQueryString(parseQueryString(rawSearch));

    if (newSearch === currentSearch) {
      // No-op: params haven't changed — avoid spurious navigation
      return;
    }

    // Build the new URL (preserve pathname from location, apply new search)
    const pathname = location.split("?")[0];
    const newUrl = newSearch ? `${pathname}?${newSearch}` : pathname;

    navigate(newUrl, { replace: !push });
  }

  return { get, set };
}
