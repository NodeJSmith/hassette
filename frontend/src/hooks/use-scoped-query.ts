import { keepPreviousData, useQuery, type UseQueryResult } from "@tanstack/preact-query";

import { useAppState } from "../state/context";
import { resolveSince } from "../utils/time-window";

export interface UseScopedQueryOptions {
  placeholderData?: typeof keepPreviousData;
}

/**
 * Wraps `useQuery` with time-window scoping.
 *
 * Reads `effectiveTimePreset` and `uptimeSeconds` from AppState, computes the
 * `since` timestamp using `resolveSince`, and gates fetching via `enabled`.
 *
 * Query key strategy:
 * - For `since-restart`: `[...baseKey, preset, uptimeSeconds]` — uptime defines the window
 *   boundary and must be in the key so a new fetch fires when uptime changes.
 * - For fixed-window presets: `[...baseKey, preset]` — uptime is irrelevant; omitting it
 *   preserves cache entries across reconnects.
 *
 * @param baseKey  Stable query key prefix (e.g., `["app-listeners", appKey]`).
 * @param fetcher  Function accepting a `since` epoch-seconds timestamp.
 * @param options  Optional: `placeholderData` for stale-while-revalidate behavior.
 */
export function useScopedQuery<T>(
  baseKey: readonly unknown[],
  fetcher: (since: number, signal: AbortSignal) => Promise<T>,
  options?: UseScopedQueryOptions,
): UseQueryResult<T> {
  const { effectiveTimePreset, uptimeSeconds } = useAppState();

  const preset = effectiveTimePreset.value;
  const uptime = uptimeSeconds.value;

  // Block fetches for since-restart until the WS connected message provides uptime_seconds.
  const waitingForUptime = preset === "since-restart" && uptime === null;

  // Include uptime in the key only for since-restart (where it defines the window boundary).
  // Fixed-window presets omit uptime so cache entries survive reconnects.
  const queryKey = [...baseKey, preset, ...(preset === "since-restart" ? [uptime] : [])];

  return useQuery<T>({
    queryKey,
    queryFn: ({ signal }) => {
      const since = resolveSince(preset, uptime);
      if (since === undefined) throw new Error("queryFn called while disabled");
      return fetcher(since, signal);
    },
    enabled: !waitingForUptime,
    ...options,
  });
}
