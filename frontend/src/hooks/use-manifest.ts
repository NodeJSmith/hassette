import { useQuery } from "@tanstack/preact-query";

import { getAppManifest } from "../api/endpoints";
import { queryKeys } from "../lib/query-keys";

export function useManifest(appKey: string) {
  return useQuery({
    queryKey: queryKeys.manifest(appKey),
    queryFn: () => getAppManifest(appKey),
  });
}
