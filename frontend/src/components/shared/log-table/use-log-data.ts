import { computed, type ReadonlySignal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { toast } from "sonner";

import { getRecentLogs, type LogEntry } from "../../../api/endpoints";
import { useSignal } from "../../../hooks/use-signal";
import { useSubscribe } from "../../../hooks/use-subscribe";
import { useAppState } from "../../../state/context";
import { REST_FETCH_LIMIT } from "./constants";

interface UseLogDataParams {
  appKey?: string;
  executionId?: string | null;
}

interface UseLogDataResult {
  /** REST + WS entries combined, deduped by timestamp watermark. */
  allEntries: ReadonlySignal<LogEntry[]>;
  /** REST-only entries (used when live-paused to exclude WS stream). */
  restEntries: ReadonlySignal<LogEntry[]>;
  loading: ReadonlySignal<boolean>;
}

export function useLogData({ appKey, executionId }: UseLogDataParams): UseLogDataResult {
  const { logs, reconnectVersion } = useAppState();

  useSubscribe(logs.version);

  const initialEntries = useSignal<LogEntry[]>([]);
  const loading = useSignal(true);
  const watermarkRef = useRef(0);

  const rv = reconnectVersion.value;
  useEffect(() => {
    let cancelled = false;
    loading.value = true;
    watermarkRef.current = 0;

    getRecentLogs({
      app_key: appKey,
      limit: REST_FETCH_LIMIT,
      execution_id: executionId,
    })
      .then((entries) => {
        if (cancelled) return;
        initialEntries.value = entries;
        watermarkRef.current = entries.reduce((max, e) => Math.max(max, e.timestamp), 0);
        loading.value = false;
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        toast.error(err instanceof Error ? err.message : "Failed to load recent logs");
        loading.value = false;
      });

    return () => {
      cancelled = true;
    };
  }, [appKey, rv, executionId]);

  const restEntries = computed<LogEntry[]>(() => [...initialEntries.value]);

  const allEntries = computed<LogEntry[]>(() => {
    const initial = initialEntries.value;
    void logs.version.value;
    const wsEntries = logs.toArray().filter((e) => {
      if (e.timestamp <= watermarkRef.current) return false;
      if (appKey && e.app_key !== appKey) return false;
      if (executionId && e.execution_id !== executionId) return false;
      return true;
    }) as LogEntry[];

    return [...initial, ...wsEntries];
  });

  return { allEntries, restEntries, loading: loading as ReadonlySignal<boolean> };
}
