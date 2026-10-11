import { QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError, unauthorizedOutcome } from "../api/client";
import { useAppStore } from "../state/store";
import { LOGIN_PATH } from "../utils/app-routes";
import { resolveAppUrl } from "./base-path";

export const DEFAULT_STALE_TIME_MS = 30_000;
export const DEFAULT_GC_TIME_MS = 300_000;
const MAX_RETRIES = 2;
const CLIENT_ERROR_MIN = 400;
const CLIENT_ERROR_MAX = 500;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      // A 401 means a session is missing or expired — no amount of retrying or cache
      // invalidation recovers from that. Hassette's own 401 sends the operator to log in; any
      // other (Supervisor's, when an HA ingress session expires) can only be fixed by reloading
      // from Home Assistant, so it shows that view. This is the one cross-cutting place that
      // handles a REST 401; apiFetch itself never does (see client.ts).
      onError: (error) => {
        const outcome = unauthorizedOutcome(error);
        if (outcome === "login") window.location.assign(resolveAppUrl(LOGIN_PATH));
        if (outcome === "session-expired") useAppStore.getState().setSessionExpired();
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
