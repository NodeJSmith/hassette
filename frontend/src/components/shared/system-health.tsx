import clsx from "clsx";

import { BREAKPOINT_MOBILE, useMediaQuery } from "../../hooks/use-media-query";
import { useAppState } from "../../state/context";
import type { ConnectionStatus } from "../../state/create-app-state";
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
  const { connection, telemetryDegraded, droppedOverflow, droppedExhausted, droppedShutdown, errorHandlerFailures } =
    useAppState();

  const status = connection.value;
  const overflow = droppedOverflow.value;
  const exhausted = droppedExhausted.value;
  const shutdown = droppedShutdown.value;
  const droppedTotal = overflow + exhausted + shutdown;
  const handlerFailures = errorHandlerFailures.value;

  const { dotClass, label } = STATUS_CONFIG[status];

  // "Disconnected" takes visual precedence over "database degraded"
  const showDegraded = telemetryDegraded.value && status === "connected";
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
  const clipConnectionLabel = clipLabels || (!stacked && status === "connected");

  const labelClass = clipLabels ? "ht-visually-hidden" : "ht-text-xs";
  const connectionLabelClass = clipConnectionLabel ? "ht-visually-hidden" : "ht-text-xs";

  return (
    <div class={clsx(styles.cluster, stacked ? styles.clusterStacked : styles.clusterCompact)}>
      <span class={styles.indicator} role="status" data-testid="ws-indicator">
        <span class={dotClass} />
        <span class={connectionLabelClass} data-testid="health-label">
          {label}
        </span>
      </span>

      {showDegraded && (
        <span class={styles.indicator} aria-label="database degraded">
          <span class={clsx(styles.pulseDot, styles.pulseDotDegraded)} />
          <span class={labelClass} data-testid="health-label">
            database degraded
          </span>
        </span>
      )}

      {droppedTotal > 0 && (
        <span
          class={styles.indicator}
          aria-label={`${pluralize(droppedTotal, "telemetry event")} dropped`}
          title={`buffer full: ${overflow}, write failed: ${exhausted}, during shutdown: ${shutdown}`}
          data-testid="dropped-events-indicator"
        >
          <span class={clsx(styles.pulseDot, styles.pulseDotDegraded)} />
          <span class={labelClass} data-testid="health-label">
            {droppedTotal} dropped
          </span>
        </span>
      )}

      {handlerFailures > 0 && (
        <span
          class={styles.indicator}
          aria-label={pluralize(handlerFailures, "handler error")}
          title={`${pluralize(handlerFailures, "user error handler invocation")} raised or timed out`}
          data-testid="error-handler-failures-indicator"
        >
          <span class={clsx(styles.pulseDot, styles.pulseDotDegraded)} />
          <span class={labelClass} data-testid="health-label">
            {pluralize(handlerFailures, "handler error")}
          </span>
        </span>
      )}
    </div>
  );
}
