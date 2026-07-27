import clsx from "clsx";
import type { MouseEvent as ReactMouseEvent } from "react";
import { useState } from "react";

import { ActionButtons } from "../components/shared/action-buttons";
import { AppLink } from "../components/shared/app-link";
import { Badge } from "../components/shared/badge";
import { Chip } from "../components/shared/chip";
import { IconChevron } from "../components/shared/icons";
import { MiniSparkline } from "../components/shared/mini-sparkline";
import { StatusShape } from "../components/shared/status-shape";
import { useRelativeTime } from "../hooks/use-relative-time";
import { type AppStatusEntry, appStatusKey } from "../state/store";
import { appLiveStatus, type AppRow } from "../utils/app-data";
import { formatTimestamp } from "../utils/format";
import { onActivateKeyDown } from "../utils/keyboard";
import { INACTIVE_STATUSES, statusToKind, statusToVariant } from "../utils/status";
import styles from "./apps.module.css";

export function AppTableRow({
  app,
  appStatuses,
  isExpanded,
  onToggle,
  muteStatus = false,
}: {
  app: AppRow;
  appStatuses: Record<string, AppStatusEntry>;
  isExpanded: boolean;
  onToggle: () => void;
  muteStatus?: boolean;
}) {
  const [errorExpanded, setErrorExpanded] = useState(false);
  const showErrorExpanded = errorExpanded && !!app.error_message;
  const lastErrorLabel = useRelativeTime(app.last_error_ts ?? null);
  const lastActivityLabel = useRelativeTime(app.last_activity_ts ?? null);
  const status = appLiveStatus(appStatuses, app);
  const kind = statusToKind(status);
  const isMulti = app.instance_count > 1;
  const isDimmed = INACTIVE_STATUSES.has(status);
  const totalRuns = app.total_invocations + app.total_executions;

  return (
    <>
      <tr className={clsx(styles.row, isDimmed && styles.rowDimmed)} data-testid={`app-row-${app.app_key}`}>
        {/* Name */}
        <td className={styles.nameCell}>
          <div className={styles.nameCellInner}>
            <span className={styles.expandGutter}>
              {isMulti && (
                <button
                  type="button"
                  className={styles.expand}
                  onClick={onToggle}
                  aria-expanded={isExpanded}
                  aria-label={`${isExpanded ? "Collapse" : "Expand"} ${app.app_key}`}
                  data-testid="app-row-expand"
                >
                  <IconChevron open={isExpanded} />
                </button>
              )}
            </span>
            <StatusShape kind={kind} size={7} muted={muteStatus} />
            <AppLink appKey={app.app_key} />
            <span className={styles.className}>{app.class_name}</span>
            {app.auto_loaded && <Chip variant="muted">auto</Chip>}
            {!app.autostart && (
              <Chip variant="muted" data-testid="no-autostart-chip">
                no autostart
              </Chip>
            )}
            {!app.in_current_config && (
              <Chip variant="muted" data-testid="removed-chip">
                removed
              </Chip>
            )}
          </div>
        </td>
        {/* Status */}
        <td>
          <Badge variant={statusToVariant(status)} size="sm" data-testid="status-pill">
            {status}
          </Badge>
          {isMulti && <span className={styles.instanceCount}>{app.instance_count} instances</span>}
        </td>
        {/* Error */}
        <td
          className={clsx(styles.errorCell, showErrorExpanded && styles.errorCellExpanded)}
          {...(app.error_message
            ? {
                role: "button",
                tabIndex: 0,
                "aria-label": `${showErrorExpanded ? "Collapse" : "Expand"} error: ${app.error_message}`,
                onClick: (e: ReactMouseEvent) => {
                  e.stopPropagation();
                  setErrorExpanded(!errorExpanded);
                },
                onKeyDown: onActivateKeyDown(() => setErrorExpanded(!errorExpanded)),
              }
            : {})}
        >
          {app.error_message ? (
            <span className="ht-text-mono ht-text-sm ht-text-danger">
              {app.error_message}
              {app.last_error_ts && <span className={styles.errorAge}> · {lastErrorLabel}</span>}
            </span>
          ) : (
            "—"
          )}
        </td>
        {/* Runs + sparkline */}
        <td className={styles.runsCell}>
          <div className={styles.runsCellInner}>
            <MiniSparkline buckets={app.activity_buckets} height={16} />
            <span className="ht-text-mono">{totalRuns}</span>
          </div>
        </td>
        {/* Last fired */}
        <td className="ht-text-mono ht-text-muted ht-text-sm">
          {app.last_activity_ts ? <span title={formatTimestamp(app.last_activity_ts)}>{lastActivityLabel}</span> : "—"}
        </td>
        {/* Actions */}
        <td className={styles.actionsCell}>
          <ActionButtons appKey={app.app_key} status={status} />
        </td>
      </tr>
      {isMulti &&
        isExpanded &&
        app.instances?.map((inst) => {
          const instStatus = appStatuses[appStatusKey(app.app_key, inst.index)]?.status ?? inst.status;
          const instKind = statusToKind(instStatus);
          return (
            <tr
              key={`${app.app_key}-${inst.index}`}
              className={clsx(styles.row, styles.rowInstance)}
              data-testid={`instance-row-${app.app_key}-${inst.index}`}
            >
              <td className={styles.nameCell}>
                <div className={styles.nameCellInner}>
                  <span className={styles.instanceCorner}>└</span>
                  <StatusShape kind={instKind} size={6} muted={muteStatus} />
                  <AppLink appKey={app.app_key} instanceIndex={inst.index}>
                    {inst.instance_name}
                  </AppLink>
                </div>
              </td>
              <td>
                <Badge variant={statusToVariant(instStatus)} size="sm">
                  {instStatus}
                </Badge>
              </td>
              <td className={styles.errorCell}>
                {inst.error_message ? (
                  <span className="ht-text-mono ht-text-sm ht-text-danger" title={inst.error_message}>
                    {inst.error_message}
                  </span>
                ) : (
                  "—"
                )}
              </td>
              <td />
              <td />
              <td className={styles.actionsCell}>
                <ActionButtons appKey={app.app_key} status={instStatus} />
              </td>
            </tr>
          );
        })}
    </>
  );
}
