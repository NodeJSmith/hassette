import { batch } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import type { AppState } from "../state/create-app-state";
import type { WsServerMessage } from "../api/ws-types";

const MAX_BACKOFF_MS = 30_000;
const INITIAL_BACKOFF_MS = 1_000;
const BACKOFF_MULTIPLIER = 1.5;
const HANDSHAKE_TIMEOUT_MS = 10_000;
const DEFAULT_LOG_LEVEL = "INFO";

function buildSubscribePayload(level: string): string {
  return JSON.stringify({
    type: "subscribe",
    data: { logs: true, min_log_level: level },
  });
}

export function useWebSocket(state: AppState): void {
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(INITIAL_BACKOFF_MS);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasConnectedRef = useRef(false);

  useEffect(() => {
    let unmounted = false;

    function connect() {
      if (unmounted) return;

      // When retrying after a first-connection failure, show "Connecting..." instead of "Disconnected"
      if (!hasConnectedRef.current && state.connection.value === "disconnected") {
        state.connection.value = "connecting";
      }

      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${proto}//${location.host}/api/ws`);
      wsRef.current = socket;

      let handshakeTimer: ReturnType<typeof setTimeout> | null = null;

      socket.onopen = () => {
        backoffRef.current = INITIAL_BACKOFF_MS;
        // If server doesn't send "connected" message within timeout, close and retry
        handshakeTimer = setTimeout(() => {
          if (!hasConnectedRef.current || state.connection.value !== "connected") {
            socket.close();
          }
        }, HANDSHAKE_TIMEOUT_MS);
      };

      socket.onmessage = (e: MessageEvent) => {
        let msg: WsServerMessage;
        try {
          msg = JSON.parse(e.data as string) as WsServerMessage;
        } catch {
          return; // Ignore non-JSON frames
        }

        batch(() => {
          switch (msg.type) {
            case "connected":
              if (handshakeTimer) {
                clearTimeout(handshakeTimer);
                handshakeTimer = null;
              }
              state.connection.value = "connected";
              state.sessionId.value = msg.data.session_id;

              // Subscribe to log streaming on every connect/reconnect
              socket.send(buildSubscribePayload(DEFAULT_LOG_LEVEL));

              // Wire the targeted callback so LogTable can update the level
              state.setUpdateLogSubscription((level: string) => {
                if (socket.readyState === WebSocket.OPEN) {
                  socket.send(buildSubscribePayload(level));
                }
              });

              if (hasConnectedRef.current) {
                // Reconnection — clear stale log buffer before re-subscribe populates fresh data
                state.logs.clear();
                // Signal all useApi instances to refetch
                state.reconnectVersion.value = state.reconnectVersion.value + 1;
              } else {
                hasConnectedRef.current = true;
              }
              break;

            case "app_status_changed":
              state.appStatus.value = {
                ...state.appStatus.value,
                [msg.data.app_key]: {
                  status: msg.data.status,
                  index: msg.data.index,
                  previous_status: msg.data.previous_status,
                  instance_name: msg.data.instance_name,
                  class_name: msg.data.class_name,
                  exception: msg.data.exception,
                },
              };
              break;

            case "log":
              state.logs.push(msg.data);
              break;

            case "connectivity":
              // HA connection status — could be surfaced in UI
              break;

            case "state_changed":
            case "service_status":
              // Available for future use
              break;
          }
        });
      };

      socket.onclose = () => {
        if (handshakeTimer) {
          clearTimeout(handshakeTimer);
          handshakeTimer = null;
        }
        // Clear the callback so stale socket references aren't used
        state.setUpdateLogSubscription(() => {});
        if (unmounted) return;
        state.connection.value = hasConnectedRef.current ? "reconnecting" : "disconnected";
        scheduleReconnect();
      };

      socket.onerror = () => {
        socket.close();
      };
    }

    function scheduleReconnect() {
      const delay = Math.min(backoffRef.current, MAX_BACKOFF_MS);
      backoffRef.current = delay * BACKOFF_MULTIPLIER;
      reconnectTimerRef.current = setTimeout(connect, delay);
    }

    connect();

    return () => {
      unmounted = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      wsRef.current?.close();
      state.connection.value = "disconnected";
    };
  }, [state]);
}
