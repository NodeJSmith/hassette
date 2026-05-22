import { useQuery } from "@tanstack/preact-query";

import { type AppManifest, getManifests } from "../api/endpoints";

/**
 * Fetches app manifests from the server and returns AppManifest[] directly
 * (unwrapped from the ManifestListResponse wrapper).
 *
 * Uses the factory default staleTime (30s). Reconnect invalidation is handled
 * globally by useWebSocket calling queryClient.invalidateQueries().
 *
 * Multiple components calling useManifests() share a single network request
 * via TanStack Query's built-in deduplication.
 */
export function useManifests() {
  return useQuery({
    queryKey: ["manifests"],
    queryFn: getManifests,
    select: (data): AppManifest[] => data.manifests,
  });
}
