/**
 * Time-window-scoped data-fetching hook.
 *
 * Wraps `useApi` and resolves the effective `since` timestamp based on
 * the current time-preset signal and the server's uptime_seconds. The
 * fetcher receives a Unix epoch seconds value (float) as its argument.
 *
 * Loading gate: if `uptimeSeconds` is still null (WS connected message
 * not yet received), the hook returns a loading state without firing any
 * fetch. This prevents the first fetch from firing with `since=NaN`.
 *
 * Changes to `effectiveTimePreset` (URL override or localStorage-backed global
 * preference) or `uptimeSeconds` automatically trigger a refetch by including
 * their values in the deps array.
 */

import { useRef } from "preact/hooks";
import { useApi, type UseApiOptions, type UseApiResult } from "./use-api";
import { useAppState } from "../state/context";
import type { TimePreset } from "../state/create-app-state";

export interface UseScopedApiOptions extends UseApiOptions {
  /** Extra deps beyond scope signals (e.g., route params). */
  deps?: unknown[];
}

/** Window sizes in seconds for the fixed-window presets. */
export const PRESET_WINDOW_SECONDS: Record<Exclude<TimePreset, "since-restart">, number> = {
  "1h": 3600,
  "24h": 86400,
  "7d": 604800,
};

/**
 * Compute the `since` timestamp (Unix epoch seconds) for the given preset.
 *
 * Returns undefined only for "since-restart" when uptimeSeconds is null
 * (WS connected message not yet received). Fixed-window presets (1h, 24h, 7d)
 * are independent of uptime and never block.
 */
function resolveSince(preset: TimePreset, uptimeSeconds: number | null): number | undefined {
  if (preset === "since-restart") {
    if (uptimeSeconds === null) return undefined;
    return Date.now() / 1000 - uptimeSeconds;
  }

  return Date.now() / 1000 - PRESET_WINDOW_SECONDS[preset];
}

/**
 * Time-window-scoped variant of `useApi`.
 *
 * @param fetcher - Function that accepts a `since` epoch-seconds timestamp and returns a promise.
 * @param options - Additional options (extra deps, lazy mode).
 */
export function useScopedApi<T>(
  fetcher: (since: number) => Promise<T>,
  options: UseScopedApiOptions = {},
): UseApiResult<T> {
  const { deps: extraDeps = [], ...apiOptions } = options;
  const { effectiveTimePreset, uptimeSeconds } = useAppState();

  const preset = effectiveTimePreset.value;
  const uptime = uptimeSeconds.value;
  const since = resolveSince(preset, uptime);

  // Block fetches until the WS connected message has arrived and we have uptime_seconds.
  const waitingForUptime = since === undefined;

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  // Include scope signals in deps so useApi detects changes and triggers refetches.
  const allDeps = [preset, uptime, ...extraDeps];

  return useApi(
    () => fetcherRef.current(since as number),
    allDeps,
    { ...apiOptions, enabled: !waitingForUptime },
  );
}
