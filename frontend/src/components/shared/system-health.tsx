import clsx from "clsx";

import { BREAKPOINT_MOBILE, useMediaQuery } from "../../hooks/use-media-query";
import type { ConnectionStatus } from "../../state/store";
import { useAppStore } from "../../state/store";
import { pluralize } from "../../utils/format";
import styles from "./system-health.module.css";

const STATUS_CONFIG: Record<ConnectionStatus, { dotClass: string; label: string }> = {
  connecting: { dotClass: clsx(styles.pulseDot, styles.pulseDotConnecting), label: "Connecting..." },
  connected: { dotClass: styles.pulseDot, label: "Connected" },
  reconnecting: { dotClass: clsx(styles.pulseDot, styles.pulseDotDisconnected), label: "Reconnecting..." },
  disconnected: { dotClass: clsx(styles.pulseDot, styles.pulseDotDisconnected), label: "Disconnected" },
};

/**
 * `stacked` is the sidebar footer — vertical, labels always visible.
 * `compact` is the status bar fallback shown when the sidebar is hidden, and matches
 * the old top-bar behavior: the connection label appears only when something is wrong.
 */
export type SystemHealthVariant = "stacked" | "compact";

interface Props {
  variant: SystemHealthVariant;
}

/**
 * Connection state plus the three telemetry alert indicators.
 *
 * Rendered in exactly one place at a time — the sidebar footer when the sidebar is on
 * screen, the status bar otherwise. Two copies would mean two `role="status"` live
 * regions announcing the same connection change, so callers must gate on
 * `useSidebarHidden()` rather than rendering both and hiding one with CSS.
 */
export function SystemHealth({ variant }: Props) {
  const connection = useAppStore((s) => s.connection);
  const telemetryDegraded = useAppStore((s) => s.telemetryDegraded);
  const droppedOverflow = useAppStore((s) => s.droppedOverflow);
  const droppedExhausted = useAppStore((s) => s.droppedExhausted);
  const droppedShutdown = useAppStore((s) => s.droppedShutdown);
  const errorHandlerFailures = useAppStore((s) => s.errorHandlerFailures);

  const droppedTotal = droppedOverflow + droppedExhausted + droppedShutdown;

  const { dotClass, label } = STATUS_CONFIG[connection];

  // "Disconnected" takes visual precedence over "database degraded"
  const showDegraded = telemetryDegraded && connection === "connected";
  const stacked = variant === "stacked";

  /*
   * On a phone the status bar already carries the hamburger, the breadcrumb trail and the
   * time selector, and the labels below run to ~200px on their own — enough to push this
   * cluster clean off the edge. Compact drops to bare dots there.
   *
   * The labels are clipped rather than dropped: `display: none` would also pull them out
   * of the accessibility tree, and the connection span is a live region whose whole job is
   * announcing that it changed.
   */
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const clipLabels = !stacked && isMobile;
  // Compact on desktop keeps the old behavior: spell the connection out only when
  // something is wrong, and clip it the rest of the time.
  const clipConnectionLabel = clipLabels || (!stacked && connection === "connected");

  const labelClass = clipLabels ? "ht-visually-hidden" : "ht-text-xs";
  const connectionLabelClass = clipConnectionLabel ? "ht-visually-hidden" : "ht-text-xs";

  return (
    <div className={clsx(styles.cluster, stacked ? styles.clusterStacked : styles.clusterCompact)}>
      <span className={styles.indicator} role="status" data-testid="ws-indicator">
        <span className={dotClass} />
        <span className={connectionLabelClass} data-testid="health-label">
          {label}
        </span>
      </span>

      {showDegraded && (
        <span className={styles.indicator} aria-label="database degraded">
          <span className={clsx(styles.pulseDot, styles.pulseDotDegraded)} />
          <span className={labelClass} data-testid="health-label">
            database degraded
          </span>
        </span>
      )}

      {droppedTotal > 0 && (
        <span
          className={styles.indicator}
          aria-label={`${pluralize(droppedTotal, "telemetry event")} dropped`}
          title={`buffer full: ${droppedOverflow}, write failed: ${droppedExhausted}, during shutdown: ${droppedShutdown}`}
          data-testid="dropped-events-indicator"
        >
          <span className={clsx(styles.pulseDot, styles.pulseDotDegraded)} />
          <span className={labelClass} data-testid="health-label">
            {droppedTotal} dropped
          </span>
        </span>
      )}

      {errorHandlerFailures > 0 && (
        <span
          className={styles.indicator}
          aria-label={pluralize(errorHandlerFailures, "handler error")}
          title={`${pluralize(errorHandlerFailures, "user error handler invocation")} raised or timed out`}
          data-testid="error-handler-failures-indicator"
        >
          <span className={clsx(styles.pulseDot, styles.pulseDotDegraded)} />
          <span className={labelClass} data-testid="health-label">
            {pluralize(errorHandlerFailures, "handler error")}
          </span>
        </span>
      )}
    </div>
  );
}
