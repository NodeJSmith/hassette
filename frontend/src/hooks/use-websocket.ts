import { useQueryClient } from "@tanstack/preact-query";
import { useEffect, useRef } from "preact/hooks";

import { WS_PATH } from "../api/endpoints";
import type { WsServerMessage } from "../api/ws-types";
import { validateWsMessage, WsValidationError } from "../api/ws-validator";
import { appStatusKey, useAppStore } from "../state/store";

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

export function useWebSocket(): void {
  const queryClient = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(INITIAL_BACKOFF_MS);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasConnectedRef = useRef(false);

  useEffect(() => {
    let unmounted = false;
    let currentLogLevel = DEFAULT_LOG_LEVEL;

    function connect() {
      if (unmounted) return;

      // When retrying after a first-connection failure, show "Connecting..." instead of "Disconnected"
      if (!hasConnectedRef.current && useAppStore.getState().connection === "disconnected") {
        useAppStore.getState().setConnection("connecting");
      }

      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${proto}//${location.host}${WS_PATH}`);
      wsRef.current = socket;

      let handshakeTimer: ReturnType<typeof setTimeout> | null = null;

      socket.onopen = () => {
        handshakeTimer = setTimeout(() => {
          if (!hasConnectedRef.current || useAppStore.getState().connection !== "connected") {
            socket.close();
          }
        }, HANDSHAKE_TIMEOUT_MS);
      };

      socket.onmessage = (e: MessageEvent) => {
        let msg: WsServerMessage;
        try {
          const raw: unknown = JSON.parse(e.data as string);
          msg = validateWsMessage(raw);
        } catch (err) {
          if (err instanceof WsValidationError) {
            console.warn("[ws] invalid message:", err.errors);
            return;
          }
          if (err instanceof SyntaxError) {
            return; // Ignore non-JSON frames
          }
          throw err;
        }

        switch (msg.type) {
          case "connected": {
            if (handshakeTimer) {
              clearTimeout(handshakeTimer);
              handshakeTimer = null;
            }
            // Reset backoff here (not in onopen) — only a fully completed handshake should reset retry delay
            backoffRef.current = INITIAL_BACKOFF_MS;

            const isReconnect = hasConnectedRef.current;
            useAppStore.getState().handleWsConnected(msg.data, isReconnect);

            if (isReconnect) {
              // Invalidate all TanStack Query caches so data is re-fetched after reconnect
              void queryClient.invalidateQueries();
            } else {
              hasConnectedRef.current = true;
            }

            // Subscribe to log streaming on every connect/reconnect
            socket.send(buildSubscribePayload(currentLogLevel));

            // Wire the targeted callback so LogTable can update the level
            useAppStore.getState().setSendLogLevel((level: string) => {
              currentLogLevel = level;
              if (socket.readyState === WebSocket.OPEN) {
                socket.send(buildSubscribePayload(level));
              }
            });
            break;
          }

          case "app_status_changed":
            useAppStore.getState().updateAppStatus(appStatusKey(msg.data.app_key, msg.data.index), {
              status: msg.data.status,
              index: msg.data.index,
              previous_status: msg.data.previous_status,
              instance_name: msg.data.instance_name,
              class_name: msg.data.class_name,
              exception: msg.data.exception,
            });
            break;

          case "log":
            useAppStore.getState().pushLog(msg.data);
            break;

          case "service_status":
            useAppStore.getState().updateServiceStatus(msg.data.resource_name, {
              resource_name: msg.data.resource_name,
              role: msg.data.role,
              status: msg.data.status,
              previous_status: msg.data.previous_status,
              exception: msg.data.exception,
              retry_at: msg.data.retry_at ?? null,
              ready: msg.data.ready ?? false,
              ready_phase: msg.data.ready_phase ?? null,
            });
            break;

          case "execution_completed":
            useAppStore.getState().setExecutionCompleted(msg.data);
            break;

          case "connectivity":
          case "state_changed":
            // Intentionally ignored — not consumed by the frontend UI.
            break;

          default: {
            const _exhaustive: never = msg;
            void _exhaustive;
            break;
          }
        }
      };

      socket.onclose = () => {
        if (handshakeTimer) {
          clearTimeout(handshakeTimer);
          handshakeTimer = null;
        }
        // Clear the callback so stale socket references aren't used
        useAppStore.getState().setSendLogLevel(() => {});
        if (unmounted) return;
        useAppStore.getState().setConnection(hasConnectedRef.current ? "reconnecting" : "disconnected");
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
        reconnectTimerRef.current = null;
      }
      wsRef.current?.close();
      useAppStore.getState().setConnection("disconnected");
    };
  }, [queryClient]);
}
