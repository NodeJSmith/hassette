import { signal, useSignalEffect } from "@preact/signals";
import type { Signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import type { AppManifest } from "../api/endpoints";
import { getStoredSet, setStoredSet } from "../utils/local-storage";

export const EXPANDED_KEY = "expanded-apps";

interface ManifestState {
  expanded: Signal<Set<string>>;
  toggleExpand: (appKey: string) => void;
}

/**
 * Manages expanded state for the apps list with localStorage persistence.
 *
 * - Initializes from localStorage
 * - Prunes stale keys when manifests first load
 * - Syncs changes back to localStorage via signal effect
 */
export function useManifestState(manifests: AppManifest[] | null): ManifestState {
  // Single source of truth for expanded app keys.
  // Initialized from localStorage, synced back on changes via useSignalEffect.
  const expandedRef = useRef(signal(getStoredSet(EXPANDED_KEY)));

  // Prune stale keys once after manifests first load.
  const prunedRef = useRef(false);
  useEffect(() => {
    if (!manifests || prunedRef.current) return;
    prunedRef.current = true;

    const current = expandedRef.current.value;
    const validKeys = new Set(manifests.map((m) => m.app_key));
    const pruned = new Set([...current].filter((k) => validKeys.has(k)));
    if (pruned.size !== current.size) {
      expandedRef.current.value = pruned;
    }
  }, [manifests]);

  // Persist expanded state to localStorage only when the signal changes —
  // useSignalEffect subscribes to the signal, not the render cycle.
  const isFirstRef = useRef(true);
  useSignalEffect(() => {
    const current = expandedRef.current.value;
    // Skip the initial value (already in localStorage from getStoredSet).
    if (isFirstRef.current) {
      isFirstRef.current = false;
      return;
    }
    setStoredSet(EXPANDED_KEY, current);
  });

  const toggleExpand = (appKey: string) => {
    const current = expandedRef.current.value;
    const next = new Set(current);
    if (next.has(appKey)) {
      next.delete(appKey);
    } else {
      next.add(appKey);
    }
    expandedRef.current.value = next;
  };

  return { expanded: expandedRef.current, toggleExpand };
}
