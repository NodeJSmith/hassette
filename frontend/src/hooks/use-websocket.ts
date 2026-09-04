import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useLocation } from "wouter";

import { ApiError } from "../api/client";
import { getSystemStatus, WS_PATH } from "../api/endpoints";
import type { WsServerMessage } from "../api/ws-types";
import { validateWsMessage, WsValidationError } from "../api/ws-validator";
import { queryKeys } from "../lib/query-keys";
import { appStatusKey, useAppStore } from "../state/store";
import { LOGIN_PATH } from "../utils/app-routes";

const MAX_BACKOFF_MS = 30_000;
const INITIAL_BACKOFF_MS = 1_000;
const BACKOFF_MULTIPLIER = 1.5;
const HANDSHAKE_TIMEOUT_MS = 10_000;
const AUTH_CHECK_TIMEOUT_MS = 5_000;
const DEFAULT_LOG_LEVEL = "INFO";
const UNAUTHORIZED_STATUS = 401;

function buildSubscribePayload(level: string): string {
  return JSON.stringify({
    type: "subscribe",
    data: { logs: true, min_log_level: level },
  });
}

export function useWebSocket(): void {
  const queryClient = useQueryClient();
  const [, navigate] = useLocation();
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;
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

      // Tracks whether onopen has fired for THIS connection attempt (reset on every connect()
      // call via this closure). A close that arrives before onopen ever fired is this backend's
      // observable signal for a rejected handshake (auth failure) — see onclose below. This is
      // deliberately not `hasConnectedRef`, which tracks the app-level "connected" message across
      // the whole hook lifetime, not per-attempt transport-level open.
      let openedThisAttempt = false;

      let handshakeTimer: ReturnType<typeof setTimeout> | null = null;

      socket.onopen = () => {
        openedThisAttempt = true;
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
            // Intentionally ignored — not consumed by the frontend UI.
            break;

          case "app_manifests_changed":
            // Signal-only message (no payload) — a full app load/reload pass completed.
            // Refetch every manifest-backed query instead of trusting whatever's cached.
            void queryClient.invalidateQueries({ queryKey: queryKeys.manifests() });
            void queryClient.invalidateQueries({ queryKey: queryKeys.manifest.prefix() });
            void queryClient.invalidateQueries({ queryKey: queryKeys.dashboardGrid() });
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

        if (!openedThisAttempt) {
          // Closed before onopen ever fired for this attempt. On this backend a pre-accept
          // auth rejection never delivers a real WS close(1008) frame — it manifests exactly
          // the same way as any other pre-open failure (no WS support on the server, a
          // transient network blip, the server still starting up). The WS handshake itself
          // carries no usable status here, so confirm via a real HTTP response before treating
          // this as an auth rejection — a REST 401 is unambiguous where "closed early" is not.
          void confirmAuthRejection();
          return;
        }

        scheduleReconnect();
      };

      socket.onerror = () => {
        socket.close();
      };

      async function confirmAuthRejection() {
        // Bound the check so a stalled request can't leave the socket disconnected forever —
        // `scheduleReconnect` must still run even if the server never responds.
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), AUTH_CHECK_TIMEOUT_MS);
        try {
          await getSystemStatus(controller.signal);
        } catch (err) {
          if (err instanceof ApiError && err.status === UNAUTHORIZED_STATUS) {
            if (!unmounted) navigateRef.current(LOGIN_PATH);
            return;
          }
        } finally {
          clearTimeout(timeoutId);
        }
        // Either the check succeeded (still authenticated — the WS failure wasn't an auth
        // problem) or it failed for a non-auth reason (network error, 5xx, or the bounded
        // timeout above firing). Neither confirms a rejected handshake, so retry like any
        // other connection failure.
        if (!unmounted) scheduleReconnect();
      }
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
