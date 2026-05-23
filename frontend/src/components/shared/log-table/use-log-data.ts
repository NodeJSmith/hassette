import { useQuery } from "@tanstack/preact-query";
import { useEffect, useMemo } from "preact/hooks";
import { toast } from "sonner";

import { getRecentLogs, type LogEntry } from "../../../api/endpoints";
import { useSubscribe } from "../../../hooks/use-subscribe";
import { queryKeys } from "../../../lib/query-keys";
import { useAppState } from "../../../state/context";
import { REST_FETCH_LIMIT } from "./constants";

interface UseLogDataParams {
  appKey?: string;
  executionId?: string | null;
}

interface UseLogDataResult {
  /** REST + WS entries combined, deduped by timestamp watermark. */
  allEntries: LogEntry[];
  /** REST-only entries (used when live-paused to exclude WS stream). */
  restEntries: LogEntry[];
  loading: boolean;
}

export function useLogData({ appKey, executionId }: UseLogDataParams): UseLogDataResult {
  const { logs } = useAppState();

  useSubscribe(logs.version);

  const { data, isPending, isError, error } = useQuery({
    queryKey: queryKeys.recentLogs(appKey, executionId),
    queryFn: ({ signal }) =>
      getRecentLogs({ app_key: appKey, limit: REST_FETCH_LIMIT, execution_id: executionId }, signal),
  });

  useEffect(() => {
    if (isError && error) {
      toast.error(error instanceof Error ? error.message : "Failed to load recent logs");
    }
  }, [isError, error]);

  const restEntries: LogEntry[] = data ?? [];

  // Watermark: highest timestamp in the REST batch. WS entries must be strictly
  // above this to be included, preventing duplicates.
  const watermark = useMemo(() => restEntries.reduce((max, e) => Math.max(max, e.timestamp), 0), [restEntries]);

  const allEntries = useMemo(() => {
    if (!data) return [];

    const wsEntries = logs.toArray().filter((e) => {
      if (e.timestamp <= watermark) return false;
      if (appKey && e.app_key !== appKey) return false;
      if (executionId && e.execution_id !== executionId) return false;
      return true;
    }) as LogEntry[];

    return [...restEntries, ...wsEntries];
    // logs.version.value in dep array drives recomputation on every WS push
  }, [data, restEntries, watermark, logs.version.value, appKey, executionId]);

  return { allEntries, restEntries, loading: isPending };
}
