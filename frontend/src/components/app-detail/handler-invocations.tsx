import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import type { HandlerInvocationData } from "../../api/endpoints";
import { formatDuration, formatTimestamp } from "../../utils/format";
import { ErrorCell } from "./error-cell";

const INITIAL_ROWS = 5;
const COL_COUNT = 4;

interface Props {
  invocations: HandlerInvocationData[];
  listenerId: number;
}

export function HandlerInvocations({ invocations, listenerId }: Props) {
  if (invocations.length === 0) {
    return <p class="ht-text-muted ht-text-xs">No invocations recorded.</p>;
  }

  const showAll = useRef(signal(false)).current;
  const expandedTracebacks = useRef(signal<Set<number>>(new Set())).current;
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
          </tr>
        </thead>
        <tbody>
          {visible.map((inv, i) => {
            const isExpanded = expandedTracebacks.value.has(i);
            return [
              <tr key={i}>
                <td>
                  <span class={`ht-badge ht-badge--sm ht-badge--${inv.status === "success" ? "success" : "danger"}`}>{inv.status}</span>
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
      {hasMore && (
        <button
          type="button"
          class="ht-btn ht-btn--xs ht-btn--ghost ht-show-more"
          onClick={() => { showAll.value = !showAll.value; }}
        >
          {showAll.value ? "Show less" : `Show all ${invocations.length}`}
        </button>
      )}
    </>
  );
}
