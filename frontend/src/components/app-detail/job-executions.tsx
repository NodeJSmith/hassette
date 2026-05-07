import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import type { JobExecutionData } from "../../api/endpoints";
import { ShowMoreButton } from "../shared/show-more-button";
import { formatDuration, formatTimestamp } from "../../utils/format";
import { executionStatusVariant } from "../../utils/status";
import { ErrorCell } from "./error-cell";

const INITIAL_ROWS = 5;
const COL_COUNT = 5;

interface Props {
  executions: JobExecutionData[];
  jobId: number;
}

export function JobExecutions({ executions, jobId }: Props) {
  const showAll = useRef(signal(false)).current;
  const expandedTracebacks = useRef(signal<Set<number>>(new Set())).current;

  if (executions.length === 0) {
    return <p class="ht-text-muted ht-text-xs">No executions recorded.</p>;
  }
  const visible = showAll.value ? executions : executions.slice(0, INITIAL_ROWS);
  const hasMore = executions.length > INITIAL_ROWS;

  const toggleTraceback = (index: number) => {
    const next = new Set(expandedTracebacks.value);
    if (next.has(index)) next.delete(index); else next.add(index);
    expandedTracebacks.value = next;
  };

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
          </tr>
        </thead>
        <tbody>
          {visible.map((ex, i) => {
            const rowKey = ex.execution_id ?? `ex-${i}`;
            const isExpanded = expandedTracebacks.value.has(i);
            return [
              <tr key={rowKey}>
                <td>
                  <span class={`ht-badge ht-badge--sm ht-badge--${executionStatusVariant(ex.status)}`}>{ex.status}</span>
                  {ex.error_message && <span class="ht-exec-error-mobile">{ex.error_message}</span>}
                </td>
                <td class="ht-text-mono ht-text-xs">{formatTimestamp(ex.execution_start_ts)}</td>
                <td>{formatDuration(ex.duration_ms)}</td>
                <td class="ht-col-error ht-text-secondary ht-text-sm">
                  <ErrorCell
                    traceback={ex.error_traceback}
                    message={ex.error_message}
                    expanded={isExpanded}
                    onToggle={() => toggleTraceback(i)}
                  />
                </td>
                <td class="ht-col-trace ht-text-mono ht-text-xs">{ex.execution_id ?? "—"}</td>
              </tr>,
              isExpanded && ex.error_traceback && (
                <tr key={`${rowKey}-tb`} class="ht-traceback-row">
                  <td colSpan={COL_COUNT}>
                    <pre class="ht-traceback" data-testid="execution-traceback">{ex.error_traceback}</pre>
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
