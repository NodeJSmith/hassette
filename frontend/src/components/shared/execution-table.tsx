import clsx from "clsx";

import { useRovingTabIndex } from "../../hooks/use-roving-tab-index";
import { useSignal } from "../../hooks/use-signal";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { formatDuration, formatTimestamp, truncateId } from "../../utils/format";
import { onActivateKeyDown } from "../../utils/keyboard";
import { executionStatusKind } from "../../utils/status";
import { Badge } from "./badge";
import { DetailPanel } from "./detail-panel";
import { EmptyState } from "./empty-state";
import styles from "./execution-table.module.css";
import { IconChevron } from "./icons";
import { ShowMoreButton } from "./show-more-button";
import { StatusShape } from "./status-shape";

const INITIAL_ROWS = 5;
const COL_COUNT = 5;

export interface ExecutionRecord {
  execution_start_ts: number;
  duration_ms: number;
  status: string;
  error_type: string | null;
  error_message: string | null;
  error_traceback?: string | null;
  execution_id?: string | null;
  trigger_context_id?: string | null;
  trigger_origin?: string | null;
  thread_leaked: boolean;
}

interface ExecutionTableProps {
  records: ExecutionRecord[];
  kind: "handler" | "job";
  tableId: string;
}

export function ExecutionTable({ records, kind, tableId }: ExecutionTableProps) {
  const showAll = useSignal(false);
  const openRow = useSignal<number | null>(null);
  const visible = showAll.value ? records : records.slice(0, INITIAL_ROWS);
  const { containerRef, onContainerKeyDown, getTabIndex, setActiveIndex } = useRovingTabIndex<HTMLTableSectionElement>(
    visible.length,
  );

  if (records.length === 0) {
    return kind === "handler" ? (
      <EmptyState
        icon="◌"
        title="no invocations recorded"
        body="this handler hasn't been called yet in the current time window."
      />
    ) : (
      <EmptyState title="no executions recorded." />
    );
  }

  const hasMore = records.length > INITIAL_ROWS;

  return (
    <>
      <table class="ht-table ht-table--compact" data-testid={tableId}>
        <thead>
          <tr>
            <th class="ht-col-status" scope="col">
              Status
            </th>
            <th class="ht-col-time" scope="col">
              Timestamp
            </th>
            <th class="ht-col-duration" scope="col">
              Duration
            </th>
            <th class="ht-col-trace" scope="col">
              Execution ID
            </th>
            <th class={styles.colArrow} scope="col">
              <span class="ht-visually-hidden">Details</span>
            </th>
          </tr>
        </thead>
        <tbody ref={containerRef} onKeyDown={onContainerKeyDown}>
          {visible.map((record, i) => {
            const isOpen = openRow.value === i;
            const rowKey = record.execution_id ?? `${kind}-${i}`;
            const statusKind = executionStatusKind(record.status);
            const isThreadLeaked = record.thread_leaked;
            const toggleRow = () => {
              openRow.value = isOpen ? null : i;
            };

            return [
              <tr
                key={rowKey}
                class={clsx(styles.row, isOpen && styles.rowOpen)}
                data-testid={kind === "handler" ? "invocation-row" : "execution-row"}
                tabIndex={getTabIndex(i)}
                role="row"
                aria-expanded={isOpen}
                data-roving-item
                onClick={() => {
                  setActiveIndex(i);
                  toggleRow();
                }}
                onKeyDown={onActivateKeyDown(toggleRow)}
              >
                <td class={styles.statusCell}>
                  <div class={styles.statusCellInner}>
                    <StatusShape kind={statusKind} size={STATUS_DOT_SIZE} />
                    {statusKind === "err" && record.error_type && (
                      <span class={styles.errorType}>{record.error_type}</span>
                    )}
                    {statusKind === "warn" && <span class={styles.timeoutType}>timed out</span>}
                    {statusKind === "cancel" && <span class={styles.cancelledType}>cancelled</span>}
                    {isThreadLeaked && (
                      <Badge variant="warning" size="sm" aria-label="thread leaked past timeout">
                        thread leaked
                      </Badge>
                    )}
                  </div>
                </td>
                <td class="ht-text-mono ht-text-xs">{formatTimestamp(record.execution_start_ts)}</td>
                <td>{formatDuration(record.duration_ms)}</td>
                <td class="ht-col-trace ht-text-mono ht-text-xs">{truncateId(record.execution_id)}</td>
                <td class="ht-text-muted">
                  <IconChevron open={isOpen} />
                </td>
              </tr>,
              isOpen && (
                <tr key={`${rowKey}-detail`}>
                  <td colSpan={COL_COUNT} class={styles.detailCell}>
                    <DetailPanel
                      status={record.status}
                      durationMs={record.duration_ms}
                      executionId={record.execution_id}
                      errorType={record.error_type}
                      errorMessage={record.error_message}
                      errorTraceback={record.error_traceback}
                      context={
                        record.trigger_context_id
                          ? {
                              triggerContextId: record.trigger_context_id,
                              triggerOrigin: record.trigger_origin,
                            }
                          : undefined
                      }
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
