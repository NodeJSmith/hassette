import { QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "../api/client";
import { LOGIN_PATH } from "../utils/app-routes";

export const DEFAULT_STALE_TIME_MS = 30_000;
export const DEFAULT_GC_TIME_MS = 300_000;
const MAX_RETRIES = 2;
const CLIENT_ERROR_MIN = 400;
const CLIENT_ERROR_MAX = 500;
const UNAUTHORIZED = 401;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      // A 401 means the session cookie is missing or expired — no amount of retrying or
      // cache invalidation recovers from that, so send the operator to log in. This is the
      // one cross-cutting place that redirects; apiFetch itself never does (see client.ts).
      onError: (error) => {
        if (error instanceof ApiError && error.status === UNAUTHORIZED) {
          window.location.assign(LOGIN_PATH);
        }
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
