import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import type { HandlerInvocationData } from "../../api/endpoints";
import { ShowMoreButton } from "../shared/show-more-button";
import { formatDuration, formatTimestamp } from "../../utils/format";
import { executionStatusVariant } from "../../utils/status";

const INITIAL_ROWS = 5;
const COL_COUNT = 5;

interface Props {
  invocations: HandlerInvocationData[];
  listenerId: number;
}

export function HandlerInvocations({ invocations, listenerId }: Props) {
  const showAll = useRef(signal(false)).current;
  const expandedTracebacks = useRef(signal<Set<number>>(new Set())).current;

  if (invocations.length === 0) {
    return (
      <div class="ht-log-empty">
        <div class="ht-log-empty__icon">◌</div>
        <div class="ht-log-empty__title">no invocations recorded</div>
        <div class="ht-log-empty__body">this handler hasn't been called yet in the current time window.</div>
      </div>
    );
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
            <th class="ht-col-time">Time</th>
            <th>Trigger</th>
            <th class="ht-col-duration">Duration</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((inv, i) => {
            const isExpanded = expandedTracebacks.value.has(i);
            const hasTraceback = !!inv.error_traceback;
            const noteContent = inv.error_message || (inv.trigger_origin ? `origin: ${inv.trigger_origin}` : "—");
            const isError = inv.status === "error" || inv.status === "timed_out";
            return [
              <tr key={i}>
                <td>
                  <span class={`ht-badge ht-badge--sm ht-badge--${executionStatusVariant(inv.status)}`}>{inv.status}</span>
                  {isError && inv.error_message && <span class="ht-exec-error-mobile">{inv.error_message}</span>}
                </td>
                <td class="ht-text-mono ht-text-xs">{formatTimestamp(inv.execution_start_ts)}</td>
                <td class="ht-col-trigger ht-text-mono ht-text-xs">
                  {inv.trigger_context_id ? (
                    <span title={inv.trigger_context_id}>{inv.trigger_origin ?? "LOCAL"}</span>
                  ) : (
                    <span class="ht-text-muted">—</span>
                  )}
                </td>
                <td>{formatDuration(inv.duration_ms)}</td>
                <td class={`ht-col-note ht-text-sm${isError ? " ht-text-danger" : " ht-text-secondary"}`}>
                  {isError && inv.error_message ? (
                    <span
                      class={hasTraceback ? "ht-invocation-note--expandable" : ""}
                      onClick={hasTraceback ? () => toggleTraceback(i) : undefined}
                      role={hasTraceback ? "button" : undefined}
                      tabIndex={hasTraceback ? 0 : undefined}
                    >
                      {inv.error_message}
                      {hasTraceback && <span class="ht-text-xs ht-text-muted"> {isExpanded ? "▾" : "▸"}</span>}
                    </span>
                  ) : (
                    <span class="ht-text-muted">{noteContent}</span>
                  )}
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
      {hasMore && <ShowMoreButton showAll={showAll} totalCount={invocations.length} />}
    </>
  );
}
