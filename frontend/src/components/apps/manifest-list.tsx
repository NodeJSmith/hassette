import { signal, useSignalEffect } from "@preact/signals";
import type { Signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import type { AppManifest } from "../../api/endpoints";
import { getStoredSet, setStoredSet } from "../../utils/local-storage";
import { useAppState } from "../../state/context";
import { ManifestRow } from "./manifest-row";
import type { FilterValue } from "./status-filter";

export const EXPANDED_KEY = "expanded-apps";

interface Props {
  manifests: AppManifest[] | null;
  filter: Signal<FilterValue>;
}

export function ManifestList({ manifests, filter }: Props) {
  const { appStatus } = useAppState();

  // Single source of truth for expanded app keys — owned by this component.
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

  if (!manifests) return null;

  const filtered =
    filter.value === "all"
      ? manifests
      : manifests.filter((m) => {
          const live = appStatus.value[m.app_key]?.status;
          return (live ?? m.status) === filter.value;
        });

  if (filtered.length === 0) {
    return <p class="ht-text-secondary">No apps match this filter.</p>;
  }

  const expanded = expandedRef.current.value;

  return (
    <table class="ht-table ht-table--dense">
      <thead>
        <tr>
          <th>App Key</th>
          <th>Name</th>
          <th>Status</th>
          <th>Error</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {filtered.map((m) => (
          <ManifestRow
            key={m.app_key}
            manifest={m}
            liveStatus={appStatus.value[m.app_key]?.status}
            isExpanded={m.instance_count > 1 && expanded.has(m.app_key)}
            onToggleExpand={() => toggleExpand(m.app_key)}
          />
        ))}
      </tbody>
    </table>
  );
}
