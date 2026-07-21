import { useSignalEffect } from "@preact/signals";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { toast } from "sonner";

import { getRecentLogs, type LogEntry } from "@/api/endpoints";
import { useScopedQuery } from "@/hooks/use-scoped-query";
import { queryKeys } from "@/lib/query-keys";
import { useAppState } from "@/state/context";

import { LIVE_LOG_UPDATE_INTERVAL_MS, REST_FETCH_LIMIT } from "./constants";
import { rowKey } from "./types";

interface UseLogDataParams {
  appKey?: string;
  executionId?: string | null;
}

interface UseLogDataResult {
  /** REST + WS entries combined, deduped by row key identity. */
  allEntries: LogEntry[];
  /** REST-only entries (used when live-paused to exclude WS stream). */
  restEntries: LogEntry[];
  loading: boolean;
}

function useThrottledLogVersion(): number {
  const { logs } = useAppState();
  const [version, setVersion] = useState(logs.version.value);
  const latestVersion = useRef(logs.version.value);
  const publishedVersion = useRef(logs.version.value);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useSignalEffect(() => {
    const nextVersion = logs.version.value;
    latestVersion.current = nextVersion;
    if (nextVersion === publishedVersion.current) return;
    if (timeout.current) return;

    timeout.current = setTimeout(() => {
      timeout.current = null;
      publishedVersion.current = latestVersion.current;
      setVersion(latestVersion.current);
    }, LIVE_LOG_UPDATE_INTERVAL_MS);
  });

  useEffect(
    () => () => {
      if (timeout.current) clearTimeout(timeout.current);
    },
    [],
  );

  return version;
}

export function useLogData({ appKey, executionId }: UseLogDataParams): UseLogDataResult {
  const { logs } = useAppState();
  const logsVersion = useThrottledLogVersion();

  const { data, isPending, isError, error } = useScopedQuery(
    queryKeys.recentLogs(appKey, executionId),
    (since, signal) =>
      getRecentLogs({ app_key: appKey, limit: REST_FETCH_LIMIT, execution_id: executionId, since }, signal),
  );

  useEffect(() => {
    if (isError && error) {
      toast.error(error instanceof Error ? error.message : "Failed to load recent logs");
    }
  }, [isError, error]);

  const restEntries = useMemo<LogEntry[]>(() => data ?? [], [data]);

  const restKeys = useMemo(() => new Set(restEntries.map(rowKey)), [restEntries]);

  const allEntries = useMemo(() => {
    if (!data) return [];

    const wsEntries = (logs.toArray() as LogEntry[]).filter((e) => {
      if (restKeys.has(rowKey(e))) return false;
      if (appKey && e.app_key !== appKey) return false;
      if (executionId && e.execution_id !== executionId) return false;
      return true;
    });

    return [...wsEntries.reverse(), ...restEntries];
    // eslint-disable-next-line react-hooks-configurable/exhaustive-deps -- logs is a stable ring-buffer ref; logsVersion drives recomputation
  }, [data, restEntries, restKeys, logsVersion, appKey, executionId]);

  return { allEntries, restEntries, loading: isPending };
}
