import { useEffect } from "preact/hooks";
import { useSignal } from "../../hooks/use-signal";
import type { LogEntry, LogsByExecutionResponse } from "../../api/endpoints";
import { getLogsByExecution } from "../../api/endpoints";
import { LogTable } from "./log-table";
import styles from "./execution-logs.module.css";

type LogFetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "retention_expired" }
  | { status: "empty" }
  | { status: "error" }
  | { status: "loaded"; records: LogEntry[]; truncated: boolean };

interface Props {
  executionId: string;
}

export function ExecutionLogs({ executionId }: Props) {
  const fetchState = useSignal<LogFetchState>({ status: "idle" });

  useEffect(() => {
    let cancelled = false;
    fetchState.value = { status: "loading" };
    getLogsByExecution(executionId)
      .then((resp: LogsByExecutionResponse) => {
        if (cancelled) return;
        if (resp.retention_expired) {
          fetchState.value = { status: "retention_expired" };
        } else if (resp.records.length === 0) {
          fetchState.value = { status: "empty" };
        } else {
          fetchState.value = { status: "loaded", records: resp.records, truncated: resp.truncated };
        }
      })
      .catch(() => {
        if (cancelled) return;
        fetchState.value = { status: "error" };
      });
    return () => { cancelled = true; };
  }, [executionId]);

  const state = fetchState.value;
  const viewAllHref = `/logs?execution_id=${encodeURIComponent(executionId)}`;

  return (
    <div class={styles.section} data-testid="execution-logs-section">
      <span class={styles.label}>logs</span>

      {state.status === "loading" && (
        <p class={styles.message}>Loading logs…</p>
      )}

      {state.status === "retention_expired" && (
        <p class={styles.message}>
          Logs for this execution were deleted by retention policy.{" "}
          <a href={viewAllHref} data-testid="view-all-logs-link">View all logs</a>
        </p>
      )}

      {state.status === "empty" && (
        <p class={styles.message}>No logs recorded for this execution.</p>
      )}

      {state.status === "error" && (
        <p class={styles.message}>Failed to load logs.</p>
      )}

      {state.status === "loaded" && (
        <>
          <LogTable
            mode="historical"
            useLocalState={true}
            hideExecutionId={true}
            hideTitle={true}
            showAppColumn={false}
            fetcher={() => Promise.resolve(state.records)}
          />
          {state.truncated && (
            <p class={styles.message}>
              Showing first {state.records.length} of more records.{" "}
              <a href={viewAllHref} data-testid="view-all-logs-link">View all logs</a>
            </p>
          )}
          {!state.truncated && (
            <p class={styles.viewAll}>
              <a href={viewAllHref} data-testid="view-all-logs-link">View all logs</a>
            </p>
          )}
        </>
      )}
    </div>
  );
}
