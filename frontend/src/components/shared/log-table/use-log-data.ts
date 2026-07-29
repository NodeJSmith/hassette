import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { getRecentLogs, type LogEntry } from "@/api/endpoints";
import { useScopedQuery } from "@/hooks/use-scoped-query";
import { queryKeys } from "@/lib/query-keys";
import { useAppStore } from "@/state/store";

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
  const logVersion = useAppStore((s) => s.logVersion);
  const [version, setVersion] = useState(logVersion);
  const latestVersion = useRef(logVersion);
  const publishedVersion = useRef(logVersion);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    latestVersion.current = logVersion;
    if (logVersion === publishedVersion.current) return;
    if (timeout.current) return;

    timeout.current = setTimeout(() => {
      timeout.current = null;
      publishedVersion.current = latestVersion.current;
      setVersion(latestVersion.current);
    }, LIVE_LOG_UPDATE_INTERVAL_MS);
  }, [logVersion]);

  useEffect(
    () => () => {
      if (timeout.current) clearTimeout(timeout.current);
    },
    [],
  );

  return version;
}

export function useLogData({ appKey, executionId }: UseLogDataParams): UseLogDataResult {
  const getLogEntries = useAppStore((s) => s.getLogEntries);
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

    const wsEntries = (getLogEntries() as LogEntry[]).filter((entry) => {
      if (restKeys.has(rowKey(entry))) return false;
      if (appKey && entry.app_key !== appKey) return false;
      if (executionId && entry.execution_id !== executionId) return false;
      return true;
    });

    return [...wsEntries.reverse(), ...restEntries];
    // eslint-disable-next-line react-hooks/exhaustive-deps -- getLogEntries is a stable store action; logsVersion drives recomputation
  }, [data, restEntries, restKeys, logsVersion, appKey, executionId]);

  return { allEntries, restEntries, loading: isPending };
}
