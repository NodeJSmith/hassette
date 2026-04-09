import { useAppState } from "../../state/context";
import { setStoredValue } from "../../utils/local-storage";
import { SessionScopeToggle } from "./session-scope-toggle";

export function StatusBar() {
  const { connection, theme, telemetryDegraded, droppedOverflow, droppedExhausted, droppedNoSession, droppedShutdown } =
    useAppState();
  const status = connection.value;
  const isDegraded = telemetryDegraded.value;
  const overflow = droppedOverflow.value ?? 0;
  const exhausted = droppedExhausted.value ?? 0;
  const noSession = droppedNoSession.value ?? 0;
  const shutdown = droppedShutdown.value ?? 0;
  const droppedTotal = overflow + exhausted + noSession + shutdown;

  const toggleTheme = () => {
    const next = theme.value === "dark" ? "light" : "dark";
    theme.value = next;
    document.documentElement.setAttribute("data-theme", next);
    setStoredValue("theme", next);
  };

  const statusConfig: Record<typeof status, { className: string; dotClass: string; label: string }> = {
    connecting: { className: "is-connecting", dotClass: "ht-pulse-dot connecting", label: "Connecting..." },
    connected: { className: "is-connected", dotClass: "ht-pulse-dot", label: "Connected" },
    reconnecting: { className: "is-disconnected", dotClass: "ht-pulse-dot disconnected", label: "Reconnecting..." },
    disconnected: { className: "is-disconnected", dotClass: "ht-pulse-dot disconnected", label: "Disconnected" },
  };

  const { className, dotClass, label } = statusConfig[status];

  // "Disconnected" takes visual precedence over "DB degraded"
  const showDegraded = isDegraded && status === "connected";

  return (
    <div class="ht-status-bar">
      <span class={`ht-ws-indicator ${className}`} aria-label={label}>
        <span class={dotClass} />
        {status !== "connected" && <span class="ht-text-xs">{label}</span>}
      </span>
      {showDegraded && (
        <span class="ht-ws-indicator is-degraded" aria-label="DB degraded">
          <span class="ht-pulse-dot degraded" />
          <span class="ht-text-xs">DB degraded</span>
        </span>
      )}
      {droppedTotal > 0 && (
        <span
          class="ht-ws-indicator is-degraded"
          aria-label={`${droppedTotal} telemetry event${droppedTotal !== 1 ? "s" : ""} dropped`}
          title={`Overflow: ${overflow}, Exhausted: ${exhausted}, No-session: ${noSession}, Shutdown: ${shutdown}`}
          data-testid="dropped-events-indicator"
        >
          <span class="ht-pulse-dot degraded" />
          <span class="ht-text-xs">{droppedTotal} dropped</span>
        </span>
      )}
      <SessionScopeToggle />
      <button
        class="ht-theme-toggle"
        data-testid="theme-toggle"
        aria-label={`Switch to ${theme.value === "dark" ? "light" : "dark"} mode`}
        onClick={toggleTheme}
      >
        {theme.value === "dark" ? (
          <svg viewBox="0 0 24 24">
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
          <svg viewBox="0 0 24 24">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        )}
      </button>
    </div>
  );
}
