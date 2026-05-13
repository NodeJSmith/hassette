import clsx from "clsx";
import { useSignal } from "../../hooks/use-signal";
import type { JobExecutionData } from "../../api/endpoints";
import { ShowMoreButton } from "../shared/show-more-button";
import { ExecutionLogs } from "../shared/execution-logs";
import { formatDuration, formatTimestamp } from "../../utils/format";
import { executionStatusKind } from "../../utils/status";
import { EmptyState } from "../shared/empty-state";
import { StatusShape } from "../shared/status-shape";
import { ErrorCell } from "./error-cell";
import styles from "./job-executions.module.css";

const INITIAL_ROWS = 5;
const COL_COUNT = 6;

interface Props {
  executions: JobExecutionData[];
  jobId: number;
}

export function JobExecutions({ executions, jobId }: Props) {
  const showAll = useSignal(false);
  const openRow = useSignal<number | null>(null);

  if (executions.length === 0) {
    return <EmptyState title="no executions recorded." />;
  }
  const visible = showAll.value ? executions : executions.slice(0, INITIAL_ROWS);
  const hasMore = executions.length > INITIAL_ROWS;

  return (
    <>
      <table class="ht-table ht-table--compact" data-testid={`execution-table-${jobId}`}>
        <thead>
          <tr>
            <th class="ht-col-status" scope="col">Status</th>
            <th class="ht-col-time" scope="col">Timestamp</th>
            <th class="ht-col-duration" scope="col">Duration</th>
            <th class="ht-col-error" scope="col">Error</th>
            <th class="ht-col-trace" scope="col">Trace ID</th>
            <th class={styles.exColArrow} scope="col"><span class="ht-visually-hidden">Details</span></th>
          </tr>
        </thead>
        <tbody>
          {visible.map((ex, i) => {
            const isOpen = openRow.value === i;
            const rowKey = ex.execution_id ?? `ex-${i}`;
            return [
              <tr
                key={rowKey}
                class={clsx(styles.exRow, isOpen && styles.exRowOpen)}
                data-testid="execution-row"
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
                <td><StatusShape kind={executionStatusKind(ex.status)} size={10} /></td>
                <td class="ht-text-mono ht-text-xs">{formatTimestamp(ex.execution_start_ts)}</td>
                <td>{formatDuration(ex.duration_ms)}</td>
                <td class="ht-col-error ht-text-secondary ht-text-sm">
                  <ErrorCell
                    traceback={null}
                    message={ex.error_message}
                    expanded={false}
                    onToggle={() => {}}
                  />
                </td>
                <td class="ht-col-trace ht-text-mono ht-text-xs">{ex.execution_id ?? "—"}</td>
                <td class="ht-text-muted">
                  <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
                    <polyline points={isOpen ? "2,4 6,8 10,4" : "4,2 8,6 4,10"} fill="none" stroke="currentColor" stroke-width="1.5" />
                  </svg>
                </td>
              </tr>,
              isOpen && (
                <tr key={`${rowKey}-detail`}>
                  <td colSpan={COL_COUNT} style={{ padding: 0 }}>
                    <ExecutionDetail ex={ex} />
                  </td>
                </tr>
              ),
            ];
          })}
        </tbody>
      </table>
      {hasMore && <ShowMoreButton showAll={showAll} totalCount={executions.length} />}
    </>
  );
}

function ExecutionDetail({ ex }: { ex: JobExecutionData }) {
  const isError = ex.status === "error";
  const isTimeout = ex.status === "timed_out";
  const bg = isError
    ? "var(--err-bg)"
    : isTimeout
      ? "var(--warn-bg)"
      : undefined;

  return (
    <div class={styles.exDetail} style={bg ? { background: bg } : undefined} data-testid="execution-detail">
      <div class={styles.exDetailGrid} data-testid="execution-detail-grid">
        <div>
          <span class={styles.exDetailLabel}>execution id</span>
          <div class={styles.exDetailCodeBox}>
            <pre class="ht-text-mono">{ex.execution_id ?? "—"}</pre>
          </div>
        </div>
        <div>
          <span class={styles.exDetailLabel}>
            {isError ? "traceback" : isTimeout ? "timeout" : "result"}
          </span>
          <div class={styles.exDetailCodeBox}>
            {isError && ex.error_traceback ? (
              <pre class="ht-text-mono ht-text-danger" data-testid="execution-traceback">
                {ex.error_traceback}
              </pre>
            ) : isTimeout ? (
              <pre class="ht-text-mono ht-text-warning">
                {`job exceeded ${formatDuration(ex.duration_ms)} budget\ntask cancelled by job runner`}
              </pre>
            ) : isError && ex.error_message ? (
              <pre class="ht-text-mono ht-text-danger">
                {`${ex.error_type ?? "Error"}: ${ex.error_message}`}
              </pre>
            ) : (
              <pre class="ht-text-mono">completed in {formatDuration(ex.duration_ms)}</pre>
            )}
          </div>
        </div>
      </div>

      <div class={styles.exLogsSectionWrapper}>
        {ex.execution_id ? (
          <ExecutionLogs executionId={ex.execution_id} />
        ) : (
          <div data-testid="execution-logs-section">
            <span class={styles.exDetailLabel}>logs</span>
            <p class={styles.exLogsMessage}>No execution ID — logs unavailable.</p>
          </div>
        )}
      </div>
    </div>
  );
}
