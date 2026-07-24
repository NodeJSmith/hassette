import clsx from "clsx";

import { useAppState } from "../../state/context";
import type { ConnectionStatus } from "../../state/create-app-state";
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
  const ehFailures = errorHandlerFailures.value;

  const { dotClass, label } = STATUS_CONFIG[status];

  // "Disconnected" takes visual precedence over "database degraded"
  const showDegraded = telemetryDegraded.value && status === "connected";
  const stacked = variant === "stacked";

  return (
    <div class={clsx(styles.cluster, stacked ? styles.clusterStacked : styles.clusterCompact)}>
      <span class={styles.indicator} role="status" data-testid="ws-indicator">
        <span class={dotClass} />
        {stacked || status !== "connected" ? (
          <span class="ht-text-xs">{label}</span>
        ) : (
          <span class="ht-visually-hidden">{label}</span>
        )}
      </span>

      {showDegraded && (
        <span class={styles.indicator} aria-label="database degraded">
          <span class={clsx(styles.pulseDot, styles.pulseDotDegraded)} />
          <span class="ht-text-xs">database degraded</span>
        </span>
      )}

      {droppedTotal > 0 && (
        <span
          class={styles.indicator}
          aria-label={`${droppedTotal} telemetry event${droppedTotal !== 1 ? "s" : ""} dropped`}
          title={`buffer full: ${overflow}, write failed: ${exhausted}, during shutdown: ${shutdown}`}
          data-testid="dropped-events-indicator"
        >
          <span class={clsx(styles.pulseDot, styles.pulseDotDegraded)} />
          <span class="ht-text-xs">{droppedTotal} dropped</span>
        </span>
      )}

      {ehFailures > 0 && (
        <span
          class={styles.indicator}
          aria-label={`${ehFailures} handler error${ehFailures !== 1 ? "s" : ""}`}
          title={`${ehFailures} user error handler invocation${ehFailures !== 1 ? "s" : ""} raised or timed out`}
          data-testid="error-handler-failures-indicator"
        >
          <span class={clsx(styles.pulseDot, styles.pulseDotDegraded)} />
          <span class="ht-text-xs">
            {ehFailures} handler error{ehFailures !== 1 ? "s" : ""}
          </span>
        </span>
      )}
    </div>
  );
}
