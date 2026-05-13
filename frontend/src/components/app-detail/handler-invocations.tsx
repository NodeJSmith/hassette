import clsx from "clsx";
import { useSignal } from "../../hooks/use-signal";
import type { HandlerInvocationData } from "../../api/endpoints";
import { ShowMoreButton } from "../shared/show-more-button";
import { ExecutionLogs } from "../shared/execution-logs";
import { formatDuration, formatTimestamp } from "../../utils/format";
import { executionStatusKind } from "../../utils/status";
import { EmptyState } from "../shared/empty-state";
import { StatusShape } from "../shared/status-shape";
import { Chip } from "../shared/chip";
import styles from "./handler-invocations.module.css";

const INITIAL_ROWS = 5;
const COL_COUNT = 6;

interface Props {
  invocations: HandlerInvocationData[];
  listenerId: number;
}

export function HandlerInvocations({ invocations, listenerId }: Props) {
  const showAll = useSignal(false);
  const openRow = useSignal<number | null>(null);

  if (invocations.length === 0) {
    return (
      <EmptyState icon="◌" title="no invocations recorded" body="this handler hasn't been called yet in the current time window." />
    );
  }
  const visible = showAll.value ? invocations : invocations.slice(0, INITIAL_ROWS);
  const hasMore = invocations.length > INITIAL_ROWS;

  return (
    <>
      <table class={clsx("ht-table ht-table--compact", styles.invocationTable)} data-testid={`invocation-table-${listenerId}`}>
        <thead>
          <tr>
            <th class={styles.invColStatus} scope="col"><span class="ht-visually-hidden">Status</span></th>
            <th class={styles.invColTime} scope="col">Time</th>
            <th scope="col">Trigger</th>
            <th class={styles.invColDur} scope="col">Duration</th>
            <th scope="col">Note</th>
            <th class={styles.invColArrow} scope="col"><span class="ht-visually-hidden">Details</span></th>
          </tr>
        </thead>
        <tbody>
          {visible.map((inv, i) => {
            const isOpen = openRow.value === i;
            const isError = inv.status === "error";
            const isTimeout = inv.status === "timed_out";
            const noteText = inv.error_message
              || (inv.status === "success" ? `completed in ${formatDuration(inv.duration_ms)}` : "—");
            const noteTone = isError ? "var(--err)" : isTimeout ? "var(--warn)" : "var(--ink-2)";
            const rowKey = inv.execution_id ?? `inv-${i}`;
            return [
              <tr
                key={rowKey}
                class={clsx(styles.invRow, isOpen && styles.invRowOpen)}
                data-testid="invocation-row"
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
                <td><StatusShape kind={executionStatusKind(inv.status)} size={10} /></td>
                <td class="ht-text-mono ht-text-xs">{formatTimestamp(inv.execution_start_ts)}</td>
                <td class={styles.invTrigger}>
                  {inv.trigger_context_id ? (
                    <span class="ht-text-mono ht-text-xs">{inv.trigger_origin ?? "LOCAL"}</span>
                  ) : (
                    <span class="ht-text-mono ht-text-xs ht-text-muted">—</span>
                  )}
                  {inv.trigger_origin && inv.trigger_origin !== "LOCAL" && (
                    <Chip variant="origin">{inv.trigger_origin.toLowerCase()}</Chip>
                  )}
                </td>
                <td class="ht-text-mono ht-text-xs">{formatDuration(inv.duration_ms)}</td>
                <td class={styles.invNote} style={{ color: noteTone }}>
                  {noteText}
                  {isError && inv.error_message && <span class="ht-exec-error-mobile">{inv.error_message}</span>}
                </td>
                <td class="ht-text-muted">
                  <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
                    <polyline points={isOpen ? "2,4 6,8 10,4" : "4,2 8,6 4,10"} fill="none" stroke="currentColor" stroke-width="1.5" />
                  </svg>
                </td>
              </tr>,
              isOpen && (
                <tr key={`${rowKey}-detail`}>
                  <td colSpan={COL_COUNT} style={{ padding: 0 }}>
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
  const bg = isError
    ? "var(--err-bg)"
    : isTimeout
      ? "var(--warn-bg)"
      : undefined;

  return (
    <div class={styles.invDetail} style={bg ? { background: bg } : undefined} data-testid="invocation-detail">
      {inv.trigger_context_id && (
        <div class={styles.invDetailContext}>
          <span class={styles.invDetailLabel}>context</span>
          <span class="ht-text-mono ht-text-xs">{inv.trigger_context_id}</span>
          <span class="ht-text-mono ht-text-xs ht-text-muted">· origin {inv.trigger_origin ?? "LOCAL"}</span>
        </div>
      )}

      <div class={styles.invDetailGrid} data-testid="invocation-detail-grid">
        <div>
          <span class={styles.invDetailLabel}>execution id</span>
          <div class={styles.invDetailCodeBox}>
            <pre class="ht-text-mono">{inv.execution_id ?? "—"}</pre>
          </div>
        </div>
        <div>
          <span class={styles.invDetailLabel}>
            {isError ? "traceback" : isTimeout ? "timeout" : "result"}
          </span>
          <div class={styles.invDetailCodeBox}>
            {isError && inv.error_traceback ? (
              <pre class="ht-text-mono ht-text-danger" data-testid="invocation-traceback">
                {inv.error_traceback}
              </pre>
            ) : isTimeout ? (
              <pre class="ht-text-mono ht-text-warning">
                {`handler exceeded ${formatDuration(inv.duration_ms)} budget\ntask cancelled by handler runner`}
              </pre>
            ) : isError && inv.error_message ? (
              <pre class="ht-text-mono ht-text-danger">
                {`${inv.error_type ?? "Error"}: ${inv.error_message}`}
              </pre>
            ) : (
              <pre class="ht-text-mono">completed in {formatDuration(inv.duration_ms)}</pre>
            )}
          </div>
        </div>
      </div>

      <div class={styles.invLogsSectionWrapper}>
        {inv.execution_id ? (
          <ExecutionLogs executionId={inv.execution_id} />
        ) : (
          <div data-testid="execution-logs-section">
            <span class={styles.invDetailLabel}>logs</span>
            <p class={styles.invLogsMessage}>No execution ID — logs unavailable.</p>
          </div>
        )}
      </div>
    </div>
  );
}
