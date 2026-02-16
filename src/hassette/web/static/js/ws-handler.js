/**
 * Hassette WebSocket store for Alpine.js.
 *
 * Maintains a single WebSocket connection to `/api/ws`, dispatches
 * custom DOM events for incoming messages, and handles automatic
 * reconnection with exponential back-off.
 *
 * Custom events dispatched on `document`:
 * - `ht:ws-connected`  — fired when the socket opens
 * - `ht:ws-message`    — fired for every parsed JSON frame
 * - `ht:refresh`       — fired on `app_status_changed` messages
 * - `ht:log-entry`     — fired on `log` messages
 */
document.addEventListener("alpine:init", () => {
  Alpine.store("ws", {
    /** @type {boolean} Whether the WebSocket is currently open. */
    connected: false,
    /** @type {WebSocket | null} The underlying WebSocket instance. */
    _socket: null,
    /** @type {number} Current reconnection delay in milliseconds. */
    _backoff: 1000,

    /**
     * Open a WebSocket connection to the Hassette server.
     *
     * If a connection is already open or connecting this is a no-op.
     * If the socket is in the CLOSING state the method defers until
     * the close completes, then retries.
     */
    connect() {
      if (this._socket) {
        var state = this._socket.readyState;
        if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) return;
        if (state === WebSocket.CLOSING) {
          if (this._socket.readyState === WebSocket.CLOSED) {
            this._socket = null;
            this.connect();
            return;
          }
          this._socket.addEventListener("close", () => this.connect(), { once: true });
          return;
        }
      }
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
          if (msg.type === "app_status_changed") {
            document.dispatchEvent(new CustomEvent("ht:refresh"));
          }
          if (msg.type === "log") {
            document.dispatchEvent(
              new CustomEvent("ht:log-entry", { detail: msg })
            );
          }
          if (msg.type === "dev_reload") {
            var kind = msg.data && msg.data.kind;
            if (kind === "css") {
              document.querySelectorAll('link[rel="stylesheet"][href*="/ui/static/"]').forEach(function (link) {
                var el = /** @type {HTMLLinkElement} */ (link);
                var url = new URL(el.href);
                url.searchParams.set("_r", String(Date.now()));
                el.href = url.toString();
              });
            } else {
              location.reload();
            }
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

    /**
     * Subscribe to real-time log streaming over the WebSocket.
     *
     * @param {string} [minLevel="INFO"] - Minimum log level to receive
     *   (e.g. `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`, `"CRITICAL"`).
     */
    subscribeLogs(minLevel = "INFO") {
      if (this._socket && this._socket.readyState === WebSocket.OPEN) {
        this._socket.send(JSON.stringify({
          type: "subscribe",
          data: { logs: true, min_log_level: minLevel },
        }));
      }
    },

    /**
     * Schedule a reconnection attempt with exponential back-off.
     *
     * Delay is capped at 30 000 ms and grows by a factor of 1.5 on
     * each consecutive failure.
     * @private
     */
    _reconnect() {
      const delay = Math.min(this._backoff, 30000);
      this._backoff = delay * 1.5;
      setTimeout(() => this.connect(), delay);
    },
  });
});
