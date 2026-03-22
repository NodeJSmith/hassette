import { batch } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import type { AppState } from "../state/create-app-state";
import type { WsServerMessage } from "../api/ws-types";

const MAX_BACKOFF_MS = 30_000;
const INITIAL_BACKOFF_MS = 1_000;
const BACKOFF_MULTIPLIER = 1.5;

export interface UseWebSocketOptions {
  /** Called after reconnection — pages should refetch their data. */
  onReconnect?: () => void;
}

export function useWebSocket(state: AppState, options?: UseWebSocketOptions): void {
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(INITIAL_BACKOFF_MS);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    let unmounted = false;

    function connect() {
      if (unmounted) return;

      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${proto}//${location.host}/api/ws`);
      wsRef.current = socket;

      socket.onopen = () => {
        state.connection.value = "connected";
        backoffRef.current = INITIAL_BACKOFF_MS;
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
              state.sessionId.value = msg.data.session_id;
              // Trigger data refresh on (re)connect
              optionsRef.current?.onReconnect?.();
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
              state.logs.buffer.push(msg.data);
              state.logs.version.value++;
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
        if (unmounted) return;
        state.connection.value = "reconnecting";
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
