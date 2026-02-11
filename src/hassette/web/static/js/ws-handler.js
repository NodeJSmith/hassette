/* Hassette WebSocket store for Alpine.js */
document.addEventListener("alpine:init", () => {
  Alpine.store("ws", {
    connected: false,
    _socket: null,
    _backoff: 1000,

    connect() {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${proto}//${location.host}/api/ws`;
      const socket = new WebSocket(url);
      this._socket = socket;

      socket.addEventListener("open", () => {
        this.connected = true;
        this._backoff = 1000;
        document.dispatchEvent(new CustomEvent("ht:ws-connected"));
      });

      socket.addEventListener("message", (event) => {
        try {
          const msg = JSON.parse(event.data);
          document.dispatchEvent(
            new CustomEvent("ht:ws-message", { detail: msg })
          );
          if (msg.type === "state_changed" || msg.type === "app_status_changed") {
            document.dispatchEvent(new CustomEvent("ht:refresh"));
          }
          if (msg.type === "log") {
            document.dispatchEvent(
              new CustomEvent("ht:log-entry", { detail: msg })
            );
          }
        } catch { /* ignore non-JSON frames */ }
      });

      socket.addEventListener("close", () => {
        this.connected = false;
        this._reconnect();
      });

      socket.addEventListener("error", () => {
        socket.close();
      });
    },

    subscribeLogs(minLevel = "INFO") {
      if (this._socket && this._socket.readyState === WebSocket.OPEN) {
        this._socket.send(JSON.stringify({
          type: "subscribe",
          data: { logs: true, min_log_level: minLevel },
        }));
      }
    },

    _reconnect() {
      const delay = Math.min(this._backoff, 30000);
      this._backoff = delay * 1.5;
      setTimeout(() => this.connect(), delay);
    },
  });
});
