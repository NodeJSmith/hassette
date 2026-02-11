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
          if (msg.type === "log_entry") {
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

    _reconnect() {
      const delay = Math.min(this._backoff, 30000);
      this._backoff = delay * 1.5;
      setTimeout(() => this.connect(), delay);
    },
  });
});
