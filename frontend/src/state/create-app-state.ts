import { signal } from "@preact/signals";
import { RingBuffer } from "../utils/ring-buffer";
import type { WsLogPayload } from "../api/ws-types";

export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";

export interface AppStatusEntry {
  status: string;
  index: number;
  previous_status?: string | null;
  instance_name?: string | null;
  class_name?: string | null;
  exception?: string | null;
}

export function createAppState() {
  return {
    /** Per-app status keyed by app_key, updated via WS. */
    appStatus: signal<Record<string, AppStatusEntry>>({}),

    /** WebSocket connection state machine. */
    connection: signal<ConnectionStatus>("disconnected"),

    /** Log entries in a ring buffer with a version signal for efficient rendering. */
    logs: {
      buffer: new RingBuffer<WsLogPayload>(1000),
      version: signal(0),
    },

    /** Dark/light theme (initialized from localStorage if available). */
    theme: signal<"dark" | "light">(
      (typeof globalThis.localStorage?.getItem === "function" && localStorage.getItem("ht-theme") === "light") ? "light" : "dark"
    ),

    /** Current Hassette session ID (from WS connected message). */
    sessionId: signal<number | null>(null),
  };
}

export type AppState = ReturnType<typeof createAppState>;
