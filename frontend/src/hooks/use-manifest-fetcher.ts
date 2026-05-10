import { useSignalEffect } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { getManifests } from "../api/endpoints";
import type { AppState } from "../state/create-app-state";

/**
 * Single-instance manifest fetcher wired at the App level.
 * Fetches on mount and refetches on WebSocket reconnection.
 * Writes to shared state signals so all consumers read the same data.
 */
export function useManifestFetcher(state: AppState): void {
  const requestIdRef = useRef(0);

  const fetch = async () => {
    const id = ++requestIdRef.current;
    state.manifestsLoading.value = true;
    try {
      const result = await getManifests();
      if (requestIdRef.current === id) {
        state.manifests.value = result.manifests;
      }
    } catch {
      // Silently degrade — manifests will remain empty/stale
    } finally {
      if (requestIdRef.current === id) {
        state.manifestsLoading.value = false;
      }
    }
  };

  useEffect(() => { void fetch(); }, []);

  const mountReconnectVersion = useRef(state.reconnectVersion.peek());
  useSignalEffect(() => {
    const v = state.reconnectVersion.value;
    if (v > 0 && v !== mountReconnectVersion.current) {
      void fetch();
    }
  });
}
