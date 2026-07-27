import clsx from "clsx";
import { useState } from "react";
import { useLocation } from "wouter";

import { useRovingTabIndex } from "../../hooks/use-roving-tab-index";
import { executionPath, type HandlerKind } from "../../utils/app-routes";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { formatDuration, formatRelativeTime, formatTimestamp } from "../../utils/format";
import { onActivateKeyDown } from "../../utils/keyboard";
import { executionStatusKind, type StatusKind } from "../../utils/status";
import { Badge } from "./badge";
import { EmptyState } from "./empty-state";
import styles from "./execution-table.module.css";
import { IconArrowRight } from "./icons";
import { ShowMoreButton } from "./show-more-button";
import { StatusShape } from "./status-shape";

const INITIAL_ROWS = 5;

const STATUS_LABEL: Record<StatusKind, string> = {
  ok: "ok",
  err: "failed",
  warn: "timed out",
  cancel: "cancelled",
  mute: "skipped",
};

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
  trigger_mode?: string | null;
  thread_leaked: boolean;
}

interface ExecutionTableProps {
  records: ExecutionRecord[];
  kind: "handler" | "job";
  tableId: string;
  appKey?: string;
  handlerKind?: HandlerKind;
  handlerId?: number;
  instanceQs?: string;
}

export function ExecutionTable({
  records,
  kind,
  tableId,
  appKey,
  handlerKind,
  handlerId,
  instanceQs,
}: ExecutionTableProps) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? records : records.slice(0, INITIAL_ROWS);
  const { containerRef, onContainerKeyDown, getTabIndex, setActiveIndex } = useRovingTabIndex<HTMLTableSectionElement>(
    visible.length,
  );
  const [, navigate] = useLocation();

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
      <table className="ht-table ht-table--compact" data-testid={tableId}>
        <thead>
          <tr>
            <th className={styles.statusColumn} scope="col">
              Status
            </th>
            <th className={styles.executionColumn} scope="col">
              Execution
            </th>
            <th className={styles.durationColumn} scope="col">
              Duration
            </th>
            <th className={styles.timeColumn} scope="col">
              Time
            </th>
            <th className={styles.colArrow} scope="col">
              <span className="ht-visually-hidden">Details</span>
            </th>
          </tr>
        </thead>
        <tbody ref={containerRef} onKeyDown={onContainerKeyDown}>
          {visible.map((record, i) => {
            const rowKey = record.execution_id ?? `${kind}-${i}`;
            const statusKind = executionStatusKind(record.status);
            const isThreadLeaked = record.thread_leaked;
            const canNavigate = appKey && handlerKind && handlerId !== undefined && record.execution_id;
            const goToDetail = () => {
              if (canNavigate) {
                navigate(executionPath(appKey, handlerKind, handlerId, record.execution_id!) + (instanceQs ?? ""));
              }
            };

            return (
              <tr
                key={rowKey}
                className={clsx(styles.row, canNavigate && styles.rowClickable)}
                data-testid={kind === "handler" ? "invocation-row" : "execution-row"}
                tabIndex={getTabIndex(i)}
                role="row"
                aria-label={canNavigate ? "View execution detail" : undefined}
                data-roving-item
                onClick={() => {
                  setActiveIndex(i);
                  goToDetail();
                }}
                onKeyDown={canNavigate ? onActivateKeyDown(goToDetail) : undefined}
              >
                <td className={clsx(styles.statusCell, styles.statusColumn)}>
                  <div className={styles.statusCellInner}>
                    <StatusShape kind={statusKind} size={STATUS_DOT_SIZE} />
                    <span className={statusLabelClass(statusKind)}>{STATUS_LABEL[statusKind]}</span>
                    {isThreadLeaked && (
                      <Badge variant="warning" size="sm" aria-label="thread leaked past timeout">
                        thread leaked
                      </Badge>
                    )}
                    {record.trigger_mode === "manual" && (
                      <Badge variant="info" size="sm" aria-label="manually triggered">
                        manual
                      </Badge>
                    )}
                  </div>
                </td>
                <td className={clsx(styles.executionColumn, "ht-text-mono ht-text-xs")}>
                  {record.execution_id ?? "—"}
                </td>
                <td className={styles.durationColumn}>{formatDuration(record.duration_ms)}</td>
                <td
                  className={clsx(styles.timeColumn, "ht-text-mono ht-text-xs")}
                  title={formatTimestamp(record.execution_start_ts)}
                >
                  {formatRelativeTime(record.execution_start_ts)}
                </td>
                <td
                  className={clsx("ht-text-muted", styles.arrowCell)}
                  aria-label={canNavigate ? "View execution detail" : undefined}
                >
                  {canNavigate && (
                    <span className={styles.arrowIndicator} data-testid="execution-detail-indicator">
                      <IconArrowRight />
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {hasMore && (
        <ShowMoreButton showAll={showAll} onToggle={() => setShowAll((v) => !v)} totalCount={records.length} />
      )}
    </>
  );
}

function statusLabelClass(kind: StatusKind): string {
  switch (kind) {
    case "ok":
      return styles.okLabel;
    case "err":
      return styles.failedLabel;
    case "warn":
      return styles.timeoutLabel;
    case "cancel":
      return styles.cancelledLabel;
    case "mute":
      return styles.statusLabel;
  }
}
