import { QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError, handleUnauthorized } from "../api/client";

export const DEFAULT_STALE_TIME_MS = 30_000;
export const DEFAULT_GC_TIME_MS = 300_000;
const MAX_RETRIES = 2;
const CLIENT_ERROR_MIN = 400;
const CLIENT_ERROR_MAX = 500;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      // A 401 means a session is missing or expired — no amount of retrying or cache
      // invalidation recovers from that, so every failed query goes through handleUnauthorized.
      // Non-query calls (action POSTs) reach the same handler via apiPost; apiFetch itself never does.
      // Wrapped, not passed bare: QueryCache calls onError(error, query), and `query` would bind to navigate.
      onError: (error) => {
        handleUnauthorized(error);
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: DEFAULT_STALE_TIME_MS,
        gcTime: DEFAULT_GC_TIME_MS,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= CLIENT_ERROR_MIN && error.status < CLIENT_ERROR_MAX) {
            return false;
          }
          return failureCount < MAX_RETRIES;
        },
      },
    },
  });
}
