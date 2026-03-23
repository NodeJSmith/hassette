import type { Signal } from "@preact/signals";
import type { AppManifest } from "../../api/endpoints";
import { useAppState } from "../../state/context";
import { ManifestRow } from "./manifest-row";
import type { FilterValue } from "./status-filter";

interface Props {
  manifests: AppManifest[] | null;
  filter: Signal<FilterValue>;
}

export function ManifestList({ manifests, filter }: Props) {
  const { appStatus } = useAppState();

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

  return (
    <table class="ht-table">
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
          />
        ))}
      </tbody>
    </table>
  );
}
