import { useState } from "preact/hooks";
import clsx from "clsx";
import { type AppRow } from "../utils/app-data";
import { statusToKind, statusToVariant, INACTIVE_STATUSES } from "../utils/status";
import { formatTimestamp } from "../utils/format";
import { useRelativeTime } from "../hooks/use-relative-time";
import { AppLink } from "../components/shared/app-link";
import { StatusShape } from "../components/shared/status-shape";
import { Badge } from "../components/shared/badge";
import { Chip } from "../components/shared/chip";
import { MiniSparkline } from "../components/shared/mini-sparkline";
import { ActionButtons } from "../components/shared/action-buttons";
import styles from "./apps.module.css";

export function AppTableRow({ app, liveStatus, isExpanded, onToggle }: {
  app: AppRow;
  liveStatus?: string;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const [errorExpanded, setErrorExpanded] = useState(false);
  const showErrorExpanded = errorExpanded && !!app.error_message;
  const lastErrorLabel = useRelativeTime(app.last_error_ts ?? null);
  const lastActivityLabel = useRelativeTime(app.last_activity_ts ?? null);
  const status = liveStatus ?? app.status;
  const kind = statusToKind(status);
  const isMulti = app.instance_count > 1;
  const isDimmed = INACTIVE_STATUSES.has(status);
  const totalRuns = app.total_invocations + app.total_executions;

  return (
    <>
      <tr
        class={clsx(styles.row, isDimmed && styles.rowDimmed)}
        data-testid={`app-row-${app.app_key}`}
      >
        {/* Name */}
        <td class={styles.nameCell}>
          <div class={styles.nameCellInner}>
            <span class={styles.expandGutter}>
              {isMulti && (
                <button type="button" class={styles.expand} onClick={onToggle} aria-expanded={isExpanded} aria-label={`${isExpanded ? "Collapse" : "Expand"} ${app.app_key}`} data-testid="app-row-expand">
                  <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
                    <polyline points={isExpanded ? "2,4 6,8 10,4" : "4,2 8,6 4,10"} fill="none" stroke="currentColor" stroke-width="1.5" />
                  </svg>
                </button>
              )}
            </span>
            <StatusShape kind={kind} size={7} />
            <AppLink appKey={app.app_key} />
            <span class={styles.className}>{app.class_name}</span>
            {app.auto_loaded && <Chip variant="muted">auto</Chip>}
          </div>
        </td>
        {/* Status */}
        <td>
          <Badge variant={statusToVariant(status)} size="sm" data-testid="status-pill">{status}</Badge>
          {isMulti && <span class={styles.instanceCount}>{app.instance_count} instances</span>}
        </td>
        {/* Error */}
        <td
          class={clsx(styles.errorCell, showErrorExpanded && styles.errorCellExpanded)}
          {...(app.error_message ? {
            role: "button", tabIndex: 0,
            "aria-label": `${showErrorExpanded ? "Collapse" : "Expand"} error: ${app.error_message}`,
            onClick: (e: Event) => { e.stopPropagation(); setErrorExpanded(!errorExpanded); },
            onKeyDown: (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setErrorExpanded(!errorExpanded); } },
          } : {})}
        >
          {app.error_message ? (
            <span class="ht-text-mono ht-text-sm ht-text-danger">
              {app.error_message}
              {app.last_error_ts && (
                <span class={styles.errorAge}> · {lastErrorLabel}</span>
              )}
            </span>
          ) : "—"}
        </td>
        {/* Runs + sparkline */}
        <td class={styles.runsCell}>
          <div class={styles.runsCellInner}>
            <MiniSparkline buckets={app.activity_buckets} height={16} />
            <span class="ht-text-mono">{totalRuns}</span>
          </div>
        </td>
        {/* Last fired */}
        <td class="ht-text-mono ht-text-muted ht-text-sm">
          {app.last_activity_ts ? (
            <span title={formatTimestamp(app.last_activity_ts)}>{lastActivityLabel}</span>
          ) : "—"}
        </td>
        {/* Actions */}
        <td class={styles.actionsCell}>
          <ActionButtons appKey={app.app_key} status={status} />
        </td>
      </tr>
      {isMulti && isExpanded && app.instances?.map((inst) => {
        const instStatus = liveStatus ?? inst.status;
        const instKind = statusToKind(instStatus);
        return (
          <tr key={`${app.app_key}-${inst.index}`} class={clsx(styles.row, styles.rowInstance)} data-testid={`instance-row-${app.app_key}-${inst.index}`}>
            <td class={styles.nameCell}>
              <div class={styles.nameCellInner}>
                <span class={styles.instanceCorner}>└</span>
                <StatusShape kind={instKind} size={6} />
                <AppLink appKey={app.app_key} instanceIndex={inst.index}>{inst.instance_name}</AppLink>
              </div>
            </td>
            <td><Badge variant={statusToVariant(instStatus)} size="sm">{instStatus}</Badge></td>
            <td class={styles.errorCell}>
              {inst.error_message ? (
                <span class="ht-text-mono ht-text-sm ht-text-danger" title={inst.error_message}>{inst.error_message}</span>
              ) : "—"}
            </td>
            <td />
            <td />
            <td class={styles.actionsCell}>
              <ActionButtons appKey={app.app_key} status={instStatus} />
            </td>
          </tr>
        );
      })}
    </>
  );
}
