import { useSignalEffect } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";

import { getManifests } from "../api/endpoints";
import type { AppState } from "../state/create-app-state";

/**
 * Single-instance manifest fetcher wired at the App level.
 * Fetches on mount and refetches on WebSocket reconnection.
 * Writes to shared state signals so all consumers read the same data.
 * Concurrent refetches (e.g., rapid reconnects) are deduplicated via requestIdRef.
 */
export function useManifestFetcher(state: AppState): void {
  const requestIdRef = useRef(0);

  const fetchManifests = async () => {
    const id = ++requestIdRef.current;
    state.manifestsLoading.value = true;
    state.manifestsError.value = null;
    try {
      const result = await getManifests();
      if (requestIdRef.current === id) {
        state.manifests.value = result.manifests;
      }
    } catch (e) {
      if (requestIdRef.current === id) {
        state.manifestsError.value = e instanceof Error ? e.message : "Failed to fetch manifests";
      }
    } finally {
      if (requestIdRef.current === id) {
        state.manifestsLoading.value = false;
      }
    }
  };

  const fetchRef = useRef(fetchManifests);
  fetchRef.current = fetchManifests;

  useEffect(() => {
    void fetchRef.current();
  }, []);

  const mountReconnectVersion = useRef(state.reconnectVersion.peek());
  useSignalEffect(() => {
    const v = state.reconnectVersion.value;
    if (v > 0 && v !== mountReconnectVersion.current) {
      void fetchRef.current();
    }
  });
}
