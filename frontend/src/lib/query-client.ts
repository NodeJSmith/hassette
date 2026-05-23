import { QueryClient } from "@tanstack/preact-query";

import { ApiError } from "../api/client";

export const DEFAULT_STALE_TIME_MS = 30_000;
export const DEFAULT_GC_TIME_MS = 300_000;
const MAX_RETRIES = 2;
const CLIENT_ERROR_MIN = 400;
const CLIENT_ERROR_MAX = 500;

export function createQueryClient(): QueryClient {
  return new QueryClient({
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
