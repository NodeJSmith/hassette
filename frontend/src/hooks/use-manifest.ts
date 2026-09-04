import { useQuery } from "@tanstack/react-query";

import { getAppManifest } from "../api/endpoints";
import { queryKeys } from "../lib/query-keys";

export function useManifest(appKey: string) {
  return useQuery({
    queryKey: queryKeys.manifest.base(appKey),
    queryFn: () => getAppManifest(appKey),
  });
}
