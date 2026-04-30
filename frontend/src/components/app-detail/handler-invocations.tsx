import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import type { HandlerInvocationData } from "../../api/endpoints";
import { ShowMoreButton } from "../shared/show-more-button";
import { formatDuration, formatTimestamp, truncateId } from "../../utils/format";
import { executionStatusVariant } from "../../utils/status";
import { ErrorCell } from "./error-cell";

const INITIAL_ROWS = 5;
const COL_COUNT = 7;

interface Props {
  invocations: HandlerInvocationData[];
  listenerId: number;
}

export function HandlerInvocations({ invocations, listenerId }: Props) {
  const showAll = useRef(signal(false)).current;
  const expandedTracebacks = useRef(signal<Set<number>>(new Set())).current;

  if (invocations.length === 0) {
    return <p class="ht-text-muted ht-text-xs">No invocations recorded.</p>;
  }
  const visible = showAll.value ? invocations : invocations.slice(0, INITIAL_ROWS);
  const hasMore = invocations.length > INITIAL_ROWS;

  const toggleTraceback = (index: number) => {
    const next = new Set(expandedTracebacks.value);
    if (next.has(index)) next.delete(index); else next.add(index);
    expandedTracebacks.value = next;
  };

  return (
    <>
      <table class="ht-table ht-table--compact" data-testid={`invocation-table-${listenerId}`}>
        <thead>
          <tr>
            <th class="ht-col-status">Status</th>
            <th class="ht-col-time">Timestamp</th>
            <th class="ht-col-duration">Duration</th>
            <th>Error</th>
            <th>Trace ID</th>
            <th>Trigger</th>
            <th>Origin</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((inv, i) => {
            const isExpanded = expandedTracebacks.value.has(i);
            return [
              <tr key={i}>
                <td>
                  <span class={`ht-badge ht-badge--sm ht-badge--${executionStatusVariant(inv.status)}`}>{inv.status}</span>
                </td>
                <td class="ht-text-mono ht-text-xs">{formatTimestamp(inv.execution_start_ts)}</td>
                <td>{formatDuration(inv.duration_ms)}</td>
                <td class="ht-text-secondary ht-text-sm">
                  <ErrorCell
                    traceback={inv.error_traceback}
                    message={inv.error_message}
                    expanded={isExpanded}
                    onToggle={() => toggleTraceback(i)}
                  />
                </td>
                <td class="ht-text-mono ht-text-xs" title={inv.execution_id ?? undefined}>{truncateId(inv.execution_id)}</td>
                <td class="ht-text-mono ht-text-xs" title={inv.trigger_context_id ?? undefined}>{truncateId(inv.trigger_context_id)}</td>
                <td class="ht-text-secondary ht-text-sm">{inv.trigger_origin ?? "—"}</td>
              </tr>,
              isExpanded && inv.error_traceback && (
                <tr key={`${i}-tb`} class="ht-traceback-row">
                  <td colSpan={COL_COUNT}>
                    <pre class="ht-traceback" data-testid="invocation-traceback">{inv.error_traceback}</pre>
                  </td>
                </tr>
              ),
            ];
          })}
        </tbody>
      </table>
      {hasMore && <ShowMoreButton showAll={showAll} totalCount={invocations.length} />}
    </>
  );
}
