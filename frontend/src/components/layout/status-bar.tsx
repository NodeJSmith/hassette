import { useAppState } from "../../state/context";

export function StatusBar() {
  const { connection, theme } = useAppState();
  const status = connection.value;

  const toggleTheme = () => {
    const next = theme.value === "dark" ? "light" : "dark";
    theme.value = next;
    document.documentElement.setAttribute("data-theme", next);
  };

  return (
    <div class="ht-status-bar">
      <div class="ht-status-bar-start">
        <span
          class={`ht-connection-dot ht-connection-${status}`}
          title={`WebSocket: ${status}`}
        />
        <span class="ht-text-secondary ht-text-xs">
          {status === "connected" ? "Connected" : status === "reconnecting" ? "Reconnecting..." : "Disconnected"}
        </span>
      </div>
      <div class="ht-status-bar-end">
        <button
          class="ht-btn ht-btn-ghost ht-btn-sm"
          onClick={toggleTheme}
          title={`Switch to ${theme.value === "dark" ? "light" : "dark"} mode`}
        >
          {theme.value === "dark" ? "☀" : "☾"}
        </button>
      </div>
    </div>
  );
}
