import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { getManifests } from "../api/endpoints";
import { ManifestList } from "../components/apps/manifest-list";
import { StatusFilter, type FilterValue } from "../components/apps/status-filter";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";

export function AppsPage() {
  const filter = useRef(signal<FilterValue>("all")).current;
  const { data, loading, error } = useApi(getManifests);

  const manifests = data.value;
  const counts: Record<string, number> = {};
  if (manifests) {
    for (const m of manifests.manifests) {
      counts[m.status] = (counts[m.status] ?? 0) + 1;
    }
  }

  if (loading.value) return <Spinner />;

  return (
    <div>
      <h1 class="ht-heading-4">
        <svg class="ht-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect width="7" height="7" x="3" y="3" rx="1" />
          <rect width="7" height="7" x="14" y="3" rx="1" />
          <rect width="7" height="7" x="14" y="14" rx="1" />
          <rect width="7" height="7" x="3" y="14" rx="1" />
        </svg>
        <span>App Management</span>
      </h1>
      {error.value && <p class="ht-text-danger">{error.value}</p>}
      <StatusFilter active={filter} counts={counts} />
      <ManifestList manifests={manifests?.manifests ?? null} filter={filter} />
    </div>
  );
}
