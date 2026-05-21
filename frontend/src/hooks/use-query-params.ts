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

import { useRef } from "preact/hooks";
import { useLocation, useSearch } from "wouter";

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

  // Keep a stable ref to the latest rawSearch and location so that event handlers
  // (e.g., handleSort called twice in rapid succession) always see the most recent
  // URL state even if a re-render hasn't been flushed between calls. In production,
  // wouter triggers a re-render on URL change before the next event; this ref is
  // a safety net for test environments where batching differs.
  const rawSearchRef = useRef(rawSearch);
  rawSearchRef.current = rawSearch;
  const locationRef = useRef(location);
  locationRef.current = location;

  function get(key: string): string | null {
    const params = parseQueryString(rawSearchRef.current);
    return params.get(key) ?? null;
  }

  function set(updates: Record<string, string | null>, options: QueryParamOptions = {}): void {
    const { push = false } = options;

    // Capture baseline before mutating — the guard compares against this snapshot
    const currentSearch = buildQueryString(parseQueryString(rawSearchRef.current));

    // Build the new param set from current state
    const next = parseQueryString(rawSearchRef.current);
    for (const [key, value] of Object.entries(updates)) {
      if (value === null || value === "") {
        next.delete(key);
      } else {
        next.set(key, value);
      }
    }

    const newSearch = buildQueryString(next);

    if (newSearch === currentSearch) {
      // No-op: params haven't changed — avoid spurious navigation
      return;
    }

    // Build the new URL (preserve pathname from location, apply new search)
    const pathname = locationRef.current.split("?")[0];
    const newUrl = newSearch ? `${pathname}?${newSearch}` : pathname;

    // Update the ref immediately so the next set() call (before re-render) sees
    // the new search string and merges correctly.
    rawSearchRef.current = newSearch;

    navigate(newUrl, { replace: !push });
  }

  return { get, set };
}
