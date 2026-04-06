import type { Signal } from "@preact/signals";
import type { AppManifest } from "../../api/endpoints";
import { useAppState } from "../../state/context";
import { useManifestState, EXPANDED_KEY } from "../../hooks/use-manifest-state";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../../hooks/use-media-query";
import { INACTIVE_STATUSES } from "../../utils/status";
import { ManifestRow } from "./manifest-row";
import { ManifestCardList } from "./manifest-card-list";
import type { FilterValue } from "./status-filter";

export { EXPANDED_KEY };

interface Props {
  manifests: AppManifest[] | null;
  filter: Signal<FilterValue>;
}

export function ManifestList({ manifests, filter }: Props) {
  const { appStatus } = useAppState();
  const { expanded, toggleExpand } = useManifestState(manifests);
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  if (!manifests) return null;

  const filtered =
    filter.value === "all"
      ? manifests
      : manifests.filter((m) => {
          const live = appStatus.value[m.app_key]?.status;
          return (live ?? m.status) === filter.value;
        });

  // Sort active-first then alphabetical (matches app-grid.tsx order).
  // Flat sort here — no DOM split like the dashboard, since the table/card
  // list already has per-row status badges making inactive rows obvious.
  const sorted = [...filtered].sort((a, b) => {
    const aStatus = appStatus.value[a.app_key]?.status ?? a.status;
    const bStatus = appStatus.value[b.app_key]?.status ?? b.status;
    const aInactive = INACTIVE_STATUSES.has(aStatus) ? 1 : 0;
    const bInactive = INACTIVE_STATUSES.has(bStatus) ? 1 : 0;
    if (aInactive !== bInactive) return aInactive - bInactive;
    return a.display_name.localeCompare(b.display_name);
  });

  if (sorted.length === 0) {
    return <p class="ht-text-secondary">No apps match this filter.</p>;
  }

  if (isMobile) {
    return (
      <ManifestCardList
        manifests={sorted}
        expanded={expanded}
        toggleExpand={toggleExpand}
        appStatus={appStatus}
      />
    );
  }

  const expandedValue = expanded.value;

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
        {sorted.map((m) => (
          <ManifestRow
            key={m.app_key}
            manifest={m}
            liveStatus={appStatus.value[m.app_key]?.status}
            isExpanded={m.instance_count > 1 && expandedValue.has(m.app_key)}
            onToggleExpand={() => toggleExpand(m.app_key)}
          />
        ))}
      </tbody>
    </table>
  );
}
