import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import type { HandlerInvocationData } from "../../api/endpoints";
import { ShowMoreButton } from "../shared/show-more-button";
import { formatDuration, formatTimestamp } from "../../utils/format";
import { statusToKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";

const INITIAL_ROWS = 5;
const COL_COUNT = 5;

interface Props {
  invocations: HandlerInvocationData[];
  listenerId: number;
}

export function HandlerInvocations({ invocations, listenerId }: Props) {
  const showAll = useRef(signal(false)).current;
  const openRow = useRef(signal<number | null>(null)).current;

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

  return (
    <>
      <table class="ht-table ht-table--compact ht-invocation-table" data-testid={`invocation-table-${listenerId}`}>
        <thead>
          <tr>
            <th class="ht-inv-col-status"></th>
            <th class="ht-inv-col-time">Time</th>
            <th>Trigger</th>
            <th class="ht-inv-col-dur">Duration</th>
            <th>Note</th>
            <th class="ht-inv-col-arrow"></th>
          </tr>
        </thead>
        <tbody>
          {visible.map((inv, i) => {
            const isOpen = openRow.value === i;
            const isError = inv.status === "error" || inv.status === "timed_out";
            const noteText = inv.error_message
              || (inv.status === "success" ? `completed in ${formatDuration(inv.duration_ms)}` : "—");
            const noteTone = isError ? "var(--err)" : inv.status === "timed_out" ? "var(--warn)" : "var(--ink-2)";
            return [
              <tr
                key={i}
                class={`ht-inv-row${isOpen ? " is-open" : ""}`}
                onClick={() => openRow.value = isOpen ? null : i}
              >
                <td><StatusShape kind={statusToKind(inv.status)} size={10} /></td>
                <td class="ht-text-mono ht-text-xs">{formatTimestamp(inv.execution_start_ts)}</td>
                <td class="ht-inv-trigger">
                  {inv.trigger_context_id ? (
                    <span class="ht-text-mono ht-text-xs">{inv.trigger_origin ?? "LOCAL"}</span>
                  ) : (
                    <span class="ht-text-mono ht-text-xs ht-text-muted">—</span>
                  )}
                  {inv.trigger_origin && inv.trigger_origin !== "LOCAL" && (
                    <span class="ht-inv-origin-chip">{inv.trigger_origin.toLowerCase()}</span>
                  )}
                </td>
                <td class="ht-text-mono ht-text-xs">{formatDuration(inv.duration_ms)}</td>
                <td class="ht-inv-note" style={{ color: noteTone }}>
                  {noteText}
                  {isError && inv.error_message && <span class="ht-exec-error-mobile">{inv.error_message}</span>}
                </td>
                <td class="ht-text-mono ht-text-xs ht-text-muted">{isOpen ? "▾" : "▸"}</td>
              </tr>,
              isOpen && (
                <tr key={`${i}-detail`}>
                  <td colSpan={COL_COUNT + 1} class="ht-inv-detail-cell" style={{ padding: 0 }}>
                    <InvocationDetail inv={inv} />
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

function InvocationDetail({ inv }: { inv: HandlerInvocationData }) {
  const isError = inv.status === "error";
  const isTimeout = inv.status === "timed_out";
  const borderColor = isError ? "var(--err)" : isTimeout ? "var(--warn)" : "var(--ink-3)";

  return (
    <div class="ht-inv-detail" style={{ borderLeftColor: borderColor }} data-testid="invocation-detail">
      {inv.trigger_context_id && (
        <div class="ht-inv-detail__context">
          <span class="ht-inv-detail__label">context</span>
          <span class="ht-text-mono ht-text-xs">{inv.trigger_context_id}</span>
          <span class="ht-text-mono ht-text-xs ht-text-muted">· origin {inv.trigger_origin ?? "LOCAL"}</span>
        </div>
      )}

      <div class="ht-inv-detail__grid">
        <div>
          <span class="ht-inv-detail__label">execution id</span>
          <div class="ht-inv-detail__code-box">
            <pre class="ht-text-mono">{inv.execution_id ?? "—"}</pre>
          </div>
        </div>
        <div>
          <span class="ht-inv-detail__label">
            {isError ? "traceback" : isTimeout ? "timeout" : "result"}
          </span>
          <div class="ht-inv-detail__code-box">
            {isError && inv.error_traceback ? (
              <pre class="ht-text-mono" style={{ color: "var(--err)" }} data-testid="invocation-traceback">
                {inv.error_traceback}
              </pre>
            ) : isTimeout ? (
              <pre class="ht-text-mono" style={{ color: "var(--warn)" }}>
                {`handler exceeded ${formatDuration(inv.duration_ms)} budget\ntask cancelled by handler runner`}
              </pre>
            ) : isError && inv.error_message ? (
              <pre class="ht-text-mono" style={{ color: "var(--err)" }}>
                {`${inv.error_type ?? "Error"}: ${inv.error_message}`}
              </pre>
            ) : (
              <pre class="ht-text-mono">completed in {formatDuration(inv.duration_ms)}</pre>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
