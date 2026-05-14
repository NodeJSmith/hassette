import clsx from "clsx";
import { useSignal } from "../../hooks/use-signal";
import { ShowMoreButton } from "./show-more-button";
import { DetailPanel } from "./detail-panel";
import { formatDuration, formatTimestamp } from "../../utils/format";
import { executionStatusKind } from "../../utils/status";
import { EmptyState } from "./empty-state";
import { StatusShape } from "./status-shape";
import styles from "./execution-table.module.css";

const INITIAL_ROWS = 5;
const COL_COUNT = 5; // Status, Timestamp, Duration, Execution ID, arrow

interface ExecutionRecord {
  execution_start_ts: number;
  duration_ms: number;
  status: string;
  error_type: string | null;
  error_message: string | null;
  error_traceback?: string | null;
  execution_id?: string | null;
  trigger_context_id?: string | null;
  trigger_origin?: string | null;
}

interface Props {
  records: ExecutionRecord[];
  kind: "handler" | "job";
  tableId: string;
}

export function ExecutionTable({ records, kind, tableId }: Props) {
  const showAll = useSignal(false);
  const openRow = useSignal<number | null>(null);

  if (records.length === 0) {
    return kind === "handler"
      ? <EmptyState icon="◌" title="no invocations recorded" body="this handler hasn't been called yet in the current time window." />
      : <EmptyState title="no executions recorded." />;
  }

  const visible = showAll.value ? records : records.slice(0, INITIAL_ROWS);
  const hasMore = records.length > INITIAL_ROWS;

  return (
    <>
      <table class="ht-table ht-table--compact" data-testid={tableId}>
        <thead>
          <tr>
            <th class="ht-col-status" scope="col">Status</th>
            <th class="ht-col-time" scope="col">Timestamp</th>
            <th class="ht-col-duration" scope="col">Duration</th>
            <th class="ht-col-trace" scope="col">Execution ID</th>
            <th class={styles.colArrow} scope="col"><span class="ht-visually-hidden">Details</span></th>
          </tr>
        </thead>
        <tbody>
          {visible.map((rec, i) => {
            const isOpen = openRow.value === i;
            const rowKey = rec.execution_id ?? `${kind}-${i}`;
            const isError = rec.status === "error";
            const isTimeout = rec.status === "timed_out";
            const shortId = rec.execution_id ? rec.execution_id.slice(0, 8) : "—";

            return [
              <tr
                key={rowKey}
                class={clsx(styles.row, isOpen && styles.rowOpen)}
                data-testid={kind === "handler" ? "invocation-row" : "execution-row"}
                tabIndex={0}
                role="row"
                aria-expanded={isOpen}
                onClick={() => openRow.value = isOpen ? null : i}
                onKeyDown={(e: KeyboardEvent) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    openRow.value = isOpen ? null : i;
                  }
                }}
              >
                <td class={styles.statusCell}>
                  <div class={styles.statusCellInner}>
                    <StatusShape kind={executionStatusKind(rec.status)} size={10} />
                    {isError && rec.error_type && (
                      <span class={styles.errorType}>{rec.error_type}</span>
                    )}
                    {isTimeout && (
                      <span class={styles.timeoutType}>timed out</span>
                    )}
                  </div>
                </td>
                <td class="ht-text-mono ht-text-xs">{formatTimestamp(rec.execution_start_ts)}</td>
                <td>{formatDuration(rec.duration_ms)}</td>
                <td class="ht-col-trace ht-text-mono ht-text-xs">{shortId}</td>
                <td class="ht-text-muted">
                  <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
                    <polyline points={isOpen ? "2,4 6,8 10,4" : "4,2 8,6 4,10"} fill="none" stroke="currentColor" stroke-width="1.5" />
                  </svg>
                </td>
              </tr>,
              isOpen && (
                <tr key={`${rowKey}-detail`}>
                  <td colSpan={COL_COUNT} style={{ padding: 0 }}>
                    <DetailPanel
                      kind={kind}
                      status={rec.status}
                      durationMs={rec.duration_ms}
                      executionId={rec.execution_id}
                      errorType={rec.error_type}
                      errorMessage={rec.error_message}
                      errorTraceback={rec.error_traceback}
                      context={rec.trigger_context_id ? {
                        triggerContextId: rec.trigger_context_id,
                        triggerOrigin: rec.trigger_origin,
                      } : undefined}
                      testId={kind === "handler" ? "invocation-detail" : "execution-detail"}
                    />
                  </td>
                </tr>
              ),
            ];
          })}
        </tbody>
      </table>
      {hasMore && <ShowMoreButton showAll={showAll} totalCount={records.length} />}
    </>
  );
}
