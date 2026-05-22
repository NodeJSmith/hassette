import { QueryClient } from "@tanstack/preact-query";

import { ApiError } from "../api/client";

/**
 * Creates a QueryClient with project-wide defaults.
 *
 * - staleTime: 30s — WebSocket event invalidation handles real-time freshness;
 *   the 30s window covers navigate-away-and-back without re-fetching.
 * - gcTime: 5min — cache entries are kept in memory for 5 minutes after their
 *   last observer unmounts.
 * - refetchOnWindowFocus / refetchOnReconnect: false — a monitoring dashboard
 *   should not refetch on every alt-tab; browser reconnects are handled by the
 *   WebSocket reconnect invalidation path.
 * - retry: up to 2 attempts for transient errors; never retry 4xx (permanent).
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 300_000,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        retry: (failureCount, error) => {
          // Don't retry 4xx errors — they're permanent failures
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
            return false;
          }
          return failureCount < 2;
        },
      },
    },
  });
}
