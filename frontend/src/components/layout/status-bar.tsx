import clsx from "clsx";

import { useAppState } from "../../state/context";
import { setStoredValue } from "../../utils/local-storage";
import styles from "./status-bar.module.css";
import { TimePresetSelector } from "./time-preset-selector";

export function StatusBar() {
  const {
    connection,
    theme,
    telemetryDegraded,
    droppedOverflow,
    droppedExhausted,
    droppedNoSession,
    droppedShutdown,
    errorHandlerFailures,
  } = useAppState();
  const status = connection.value;
  const isDegraded = telemetryDegraded.value;
  const overflow = droppedOverflow.value;
  const exhausted = droppedExhausted.value;
  const noSession = droppedNoSession.value;
  const shutdown = droppedShutdown.value;
  const droppedTotal = overflow + exhausted + noSession + shutdown;
  const ehFailures = errorHandlerFailures.value;

  const toggleTheme = () => {
    const next = theme.value === "dark" ? "light" : "dark";
    theme.value = next;
    document.documentElement.setAttribute("data-theme", next);
    setStoredValue("theme", next);
  };

  const statusConfig: Record<typeof status, { dotClass: string; label: string }> = {
    connecting: { dotClass: clsx(styles.pulseDot, styles.pulseDotConnecting), label: "Connecting..." },
    connected: { dotClass: styles.pulseDot, label: "Connected" },
    reconnecting: { dotClass: clsx(styles.pulseDot, styles.pulseDotDisconnected), label: "Reconnecting..." },
    disconnected: { dotClass: clsx(styles.pulseDot, styles.pulseDotDisconnected), label: "Disconnected" },
  };

  const { dotClass, label } = statusConfig[status];

  // "Disconnected" takes visual precedence over "database degraded"
  const showDegraded = isDegraded && status === "connected";

  return (
    <div class={styles.statusBar} data-testid="status-bar">
      <div class={styles.statusBarLeft}>
        <TimePresetSelector />
      </div>
      <div class={styles.statusBarRight}>
        <span class={styles.wsIndicator} role="status" data-testid="ws-indicator">
          <span class={dotClass} />
          {status !== "connected" ? <span class="ht-text-xs">{label}</span> : <span class="ht-sr-only">{label}</span>}
        </span>
        {showDegraded && (
          <span class={styles.wsIndicator} aria-label="database degraded">
            <span class={clsx(styles.pulseDot, styles.pulseDotDegraded)} />
            <span class="ht-text-xs">database degraded</span>
          </span>
        )}
        {droppedTotal > 0 && (
          <span
            class={styles.wsIndicator}
            aria-label={`${droppedTotal} telemetry event${droppedTotal !== 1 ? "s" : ""} dropped`}
            title={`buffer full: ${overflow}, write failed: ${exhausted}, no session: ${noSession}, during shutdown: ${shutdown}`}
            data-testid="dropped-events-indicator"
          >
            <span class={clsx(styles.pulseDot, styles.pulseDotDegraded)} />
            <span class="ht-text-xs">{droppedTotal} dropped</span>
          </span>
        )}
        {ehFailures > 0 && (
          <span
            class={styles.wsIndicator}
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
        <button
          type="button"
          class={styles.themeToggle}
          data-testid="theme-toggle"
          aria-label={`Switch to ${theme.value === "dark" ? "light" : "dark"} mode`}
          onClick={toggleTheme}
        >
          {theme.value === "dark" ? (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="12" r="5" />
              <line x1="12" y1="1" x2="12" y2="3" />
              <line x1="12" y1="21" x2="12" y2="23" />
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
              <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
              <line x1="1" y1="12" x2="3" y2="12" />
              <line x1="21" y1="12" x2="23" y2="12" />
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
              <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}
